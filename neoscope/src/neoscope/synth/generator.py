"""Bộ mô phỏng phiên giao dịch NEO API — CHẾ ĐỘ SYNTHETIC, GẮN NHÃN CÔNG KHAI.

⚠️ TOÀN BỘ DỮ LIỆU DO MODULE NÀY SINH RA LÀ MÔ PHỎNG, KHÔNG PHẢI DỮ LIỆU
THỊ TRƯỜNG THẬT. Mỗi tệp raw mang meta `synthetic: true`, tên thư mục tiền
tố SYNTH_, dashboard treo banner cảnh báo. Tuân thủ quy định liêm chính của
đề bài: "Không dùng dữ liệu giả để tạo kết quả đẹp mà không công bố rõ".

THIẾT KẾ (reduced-form, không phải agent-based LOB đầy đủ — công bố hạn chế):
- Mid theo khuếch tán + trôi phụ thuộc OBI:  r_t = κ·OBI_{t−1} + σ_t·ε_t.
  Nhờ vậy OBI CÓ sức dự báo hướng giá thật trong thế giới mô phỏng
  (tương tự cơ chế Cont, Kukanov & Stoikov 2014) — kiểm chứng không bị
  "dàn xếp" vì κ chỉ được ƯỚC LƯỢNG lại từ dữ liệu, không đọc từ cấu hình.
- OBI tiềm ẩn AR(1); độ sâu hai phía lệch theo OBI.
- Thanh khoản & biến động hình chữ U nội ngày (mở/đóng cửa dày, giữa phiên mỏng).
- Sổ lệnh 3 mức trên lưới bước giá HOSE thật; biên độ ±7%; lô 100.
- Sự kiện ground-truth (bốc hơi độ sâu, bùng nổ KL, nhảy giá, burst ngoại)
  được ghi log để chấm precision/recall của alert engine.
- Bơm đúng các "bẫy" dữ liệu NEO thật: giá mức 1 dạng chuỗi/ATO/ATC,
  totalBidQTTY null, bộ đếm lũy kế, thông điệp lặp/sai thứ tự/đến muộn,
  thiếu trường, khoảng trống "mất kết nối".
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import Settings
from ..constants import LOT_SIZE, VN_TZ, round_to_tick, tick_size
from ..data.store import RawWriter

GENERATOR_VERSION = "1.0.0"
N_LO_STEPS_PER_MIN = 12  # nhịp 5s


def _session_dates(end_date: str, n: int) -> list[str]:
    days = pd.bdate_range(end=end_date, periods=n)
    return [d.strftime("%Y-%m-%d") for d in days]


def _lo_timeline(date_str: str, interval_s: int) -> list[datetime]:
    """Timeline phiên liên tục: 09:15–11:30 và 13:00–14:30 (bỏ nghỉ trưa)."""
    d = date.fromisoformat(date_str)
    out = []
    for start, minutes in ((time(9, 15), 135), (time(13, 0), 90)):
        t0 = datetime.combine(d, start, tzinfo=VN_TZ)
        n = int(minutes * 60 / interval_s)
        out.extend(t0 + timedelta(seconds=i * interval_s) for i in range(n))
    return out


def _u_shape(timeline: list[datetime]) -> np.ndarray:
    """Hệ số thanh khoản/biến động hình chữ U theo phút trong phiên."""
    mins = np.array([(t.hour * 60 + t.minute + t.second / 60) for t in timeline])
    am_open, am_close = 9 * 60 + 15, 11 * 60 + 30
    pm_open, pm_close = 13 * 60, 14 * 60 + 30
    u = np.ones_like(mins)
    u += 0.8 * np.exp(-np.maximum(mins - am_open, 0) / 25.0) * (mins <= am_close)
    u += 0.5 * np.exp(-np.maximum(am_close - mins, 0) / 15.0) * (mins <= am_close)
    u += 0.4 * np.exp(-np.maximum(mins - pm_open, 0) / 20.0) * (mins > am_close)
    u += 0.7 * np.exp(-np.maximum(pm_close - mins, 0) / 18.0) * (mins > am_close)
    return u


class SessionSimulator:
    def __init__(self, settings: Settings, date_str: str, session_idx: int):
        self.cfg = settings
        self.date_str = date_str
        self.seed = int(settings.synth.seed) + session_idx * 101
        self.rng = np.random.default_rng(self.seed)
        self.interval = int(settings.synth.snapshot_interval_s)
        self.timeline = _lo_timeline(date_str, self.interval)
        self.n = len(self.timeline)
        self.u = _u_shape(self.timeline)
        self.events: list[dict[str, Any]] = []
        self._schedule_events()

    # ---------------- sự kiện ground-truth ----------------
    def _schedule_events(self) -> None:
        syms = self.cfg.watchlist()
        ev = self.cfg.synth.events.as_dict()
        plan = (
            [("DEPTH_EVAPORATION", int(ev["evap_per_session"])),
             ("TRADE_BURST", int(ev["burst_per_session"])),
             ("FLASH_MOVE", int(ev["flash_per_session"])),
             ("FOREIGN_BURST", int(ev["foreign_burst_per_session"]))]
        )
        for etype, count in plan:
            for _ in range(count):
                sym = str(self.rng.choice(syms))
                start = int(self.rng.integers(60, self.n - 120))
                dur = {"DEPTH_EVAPORATION": int(self.rng.integers(36, 96)),   # 3–8 phút
                       "TRADE_BURST": int(self.rng.integers(12, 36)),          # 1–3 phút
                       "FLASH_MOVE": int(self.rng.integers(6, 12)),            # 30–60s
                       "FOREIGN_BURST": int(self.rng.integers(6, 18))}[etype]
                direction = int(self.rng.choice([-1, 1]))
                self.events.append({
                    "type": etype, "symbol": sym,
                    "start_ts": self.timeline[start].isoformat(),
                    "end_ts": self.timeline[min(start + dur, self.n - 1)].isoformat(),
                    "start_step": start, "end_step": min(start + dur, self.n - 1),
                    "direction": direction, "synthetic": True,
                })

    def _active(self, symbol: str, step: int, etype: str) -> dict | None:
        for e in self.events:
            if e["symbol"] == symbol and e["type"] == etype and e["start_step"] <= step <= e["end_step"]:
                return e
        return None

    # ---------------- mô phỏng một mã ----------------
    def simulate_symbol(self, symbol: str) -> dict[str, np.ndarray | list]:
        p = self.cfg.synth.as_dict()["symbols"][symbol]
        rng = self.rng
        n = self.n
        ref = float(p["ref"]) * (1 + rng.normal(0, 0.004))  # gap qua đêm
        ref = round_to_tick(ref)
        ceiling = round_to_tick(ref * 1.07, "down")
        floor = round_to_tick(ref * 0.93, "up")

        sigma_step = float(p["sigma_daily_bps"]) / np.sqrt(n) * np.sqrt(self.u)
        kappa = float(p["kappa_obi_bps"])

        obi = np.empty(n)
        mid = np.empty(n)
        spread_ticks = np.empty(n, dtype=int)
        depth_mult = np.ones(n)
        trade_mult = np.ones(n)
        extra_drift = np.zeros(n)

        # áp dụng sự kiện vào tham số
        for e in self.events:
            if e["symbol"] != symbol:
                continue
            s, t = e["start_step"], e["end_step"]
            if e["type"] == "DEPTH_EVAPORATION":
                depth_mult[s:t + 1] *= 0.15
                spread_ticks[s:t + 1] += 2
            elif e["type"] == "TRADE_BURST":
                trade_mult[s:t + 1] *= 6.0
                extra_drift[s:t + 1] += e["direction"] * sigma_step[s:t + 1] * 0.8
            elif e["type"] == "FLASH_MOVE":
                extra_drift[s] += e["direction"] * rng.uniform(150, 250)  # bps nhảy
                extra_drift[s + 1:min(s + 13, n)] -= e["direction"] * rng.uniform(40, 90) / 12
            elif e["type"] == "FOREIGN_BURST":
                pass  # xử lý ở luồng ngoại

        o = 0.0
        m = ref
        base_spread = 1 if self.cfg.group_of(symbol) == "large" else 2
        for i in range(n):
            o = float(np.clip(0.97 * o + rng.normal(0, 0.12), -0.95, 0.95))
            r_bps = kappa * o + sigma_step[i] * rng.normal() + extra_drift[i]
            m = float(np.clip(m * (1 + r_bps / 1e4), floor, ceiling))
            obi[i] = o
            mid[i] = m
            if spread_ticks[i] == 0:
                spread_ticks[i] = base_spread + (1 if rng.random() < (0.15 if base_spread == 1 else 0.35) else 0)

        # sổ lệnh 3 mức
        book: dict[str, np.ndarray] = {}
        tick0 = tick_size(ref)
        best_bid = np.array([round_to_tick(mid[i] - spread_ticks[i] * tick_size(mid[i]) / 2, "down") for i in range(n)])
        best_ask = best_bid + spread_ticks * np.array([tick_size(mid[i]) for i in range(n)])
        best_bid = np.clip(best_bid, floor, ceiling)
        best_ask = np.clip(best_ask, floor, ceiling)
        decay = np.array([1.0, 0.65, 0.40])
        for side, sign in (("bid", +1), ("ask", -1)):
            base_vol = float(p["depth_base"]) * self.u * depth_mult
            for lvl in (1, 2, 3):
                px = best_bid - (lvl - 1) * tick0 if side == "bid" else best_ask + (lvl - 1) * tick0
                px = np.clip(px, floor, ceiling)
                vol = base_vol * decay[lvl - 1] * rng.lognormal(0, 0.45, n) * (1 + sign * 0.6 * obi)
                vol = np.maximum(np.round(vol / LOT_SIZE) * LOT_SIZE, LOT_SIZE)
                book[f"{side}{lvl}"] = px
                book[f"{side}vol{lvl}"] = vol

        # giao dịch (nhịp 5s, một phía chủ đạo mỗi nhịp — giản lược công bố)
        lam_shares = float(p["adv_shares"]) / n * self.u * trade_mult
        d_vol = rng.poisson(np.maximum(lam_shares, 1) / LOT_SIZE) * LOT_SIZE
        buy_prob = 1 / (1 + np.exp(-1.5 * obi))
        is_buy = rng.random(n) < buy_prob
        trade_px = np.where(is_buy, best_ask, best_bid)
        d_val = d_vol * trade_px
        last_vol = np.minimum(d_vol, np.round(rng.lognormal(np.log(700), 0.8, n) / LOT_SIZE) * LOT_SIZE)
        last_vol = np.where(d_vol > 0, np.maximum(last_vol, LOT_SIZE), 0)
        cum_vol = np.cumsum(d_vol)
        cum_val = np.cumsum(d_val)
        last_price = np.where(d_vol > 0, trade_px, np.nan)
        open_px = trade_px[np.argmax(d_vol > 0)] if (d_vol > 0).any() else ref
        high = np.maximum.accumulate(np.where(d_vol > 0, trade_px, -np.inf))
        low = np.minimum.accumulate(np.where(d_vol > 0, trade_px, np.inf))
        high = np.where(np.isfinite(high), high, np.nan)
        low = np.where(np.isfinite(low), low, np.nan)
        avg_px = np.where(cum_vol > 0, np.round(cum_val / np.maximum(cum_vol, 1)), np.nan)

        # dòng tiền ngoại
        fi = float(p["foreign_intensity"])
        bias = rng.normal(0, 0.6)
        f_active = rng.random(n) < 0.12 * fi * self.u
        f_buy = f_active & (rng.random(n) < 1 / (1 + np.exp(-bias)))
        f_size = np.round(rng.lognormal(np.log(2500), 0.9, n) / LOT_SIZE) * LOT_SIZE
        f_buy_vol = np.where(f_buy, f_size, 0)
        f_sell_vol = np.where(f_active & ~f_buy, f_size, 0)
        for e in self.events:
            if e["symbol"] == symbol and e["type"] == "FOREIGN_BURST":
                chunk = int(rng.integers(200, 800)) * LOT_SIZE
                if e["direction"] > 0:
                    f_buy_vol[e["start_step"]] += chunk
                else:
                    f_sell_vol[e["start_step"]] += chunk
        f_buy_val = np.cumsum(f_buy_vol * best_ask)
        f_sell_val = np.cumsum(f_sell_vol * best_bid)
        f_room = float(p["adv_shares"]) * rng.uniform(30, 60)
        f_remain = f_room - np.cumsum(f_buy_vol - f_sell_vol) * 0.1  # giản lược công bố

        return {
            "ref": ref, "ceiling": ceiling, "floor": floor,
            "obi": obi, "mid": mid, "book": book,
            "d_vol": d_vol, "d_val": d_val, "cum_vol": cum_vol, "cum_val": cum_val,
            "last_price": last_price, "last_vol": last_vol,
            "open": open_px, "high": high, "low": low, "avg": avg_px,
            "f_buy_vol": np.cumsum(f_buy_vol), "f_sell_vol": np.cumsum(f_sell_vol),
            "f_buy_val": f_buy_val, "f_sell_val": f_sell_val,
            "f_remain": f_remain, "f_room": f_room,
        }

    # ---------------- phát thông điệp định dạng NEO ----------------
    def emit(self, writer: RawWriter) -> dict[str, Any]:
        traps = self.cfg.synth.traps.as_dict()
        rng = self.rng
        sims = {s: self.simulate_symbol(s) for s in self.cfg.watchlist()}

        # khoảng trống "mất kết nối": mỗi phiên vài mã bị ngắt 20–60s
        gaps: dict[str, tuple[int, int]] = {}
        for _ in range(int(traps["gap_events_per_session"])):
            sym = str(rng.choice(self.cfg.watchlist()))
            start = int(rng.integers(100, self.n - 100))
            gaps[sym] = (start, start + int(rng.integers(4, 12)))

        # phiên ATO: 2 snapshot với ký tự ATO
        d = date.fromisoformat(self.date_str)
        for mm in (5, 10):
            ts = datetime.combine(d, time(9, mm), tzinfo=VN_TZ)
            for sym, sim in sims.items():
                writer.write("stockInfo", self._payload(sym, sim, 0, ato="ATO"), ts)
        writer.write("marketSession", {"marketCode": "HOSE", "marketStatus": "ATO",
                                       "time": datetime.combine(d, time(9, 0), tzinfo=VN_TZ).isoformat()},
                     datetime.combine(d, time(9, 0), tzinfo=VN_TZ))
        writer.write("marketSession", {"marketCode": "HOSE", "marketStatus": "LO",
                                       "time": self.timeline[0].isoformat()}, self.timeline[0])

        prev_payload: dict[str, dict] = {}
        for i, ts in enumerate(self.timeline):
            for sym, sim in sims.items():
                if sym in gaps and gaps[sym][0] <= i < gaps[sym][1]:
                    continue  # mất kết nối: không phát, bộ đếm vẫn tích lũy
                payload = self._payload(sym, sim, i)
                arrival = ts
                r = rng.random()
                if r < traps["late_p"]:
                    arrival = ts + timedelta(seconds=float(rng.uniform(3, 10)))
                elif r < traps["late_p"] + traps["out_of_order_p"]:
                    arrival = ts - timedelta(seconds=self.interval)
                writer.write("stockInfo", payload, arrival)
                if rng.random() < traps["duplicate_p"] and sym in prev_payload:
                    writer.write("stockInfo", prev_payload[sym], ts)  # lặp nguyên payload
                prev_payload[sym] = payload

            if i % 3 == 0:  # chỉ số mỗi 15s
                self._emit_index(writer, sims, i, ts)

        # ATC + đóng cửa
        for mm, status in ((35, "ATC"), (44, "ATC")):
            ts = datetime.combine(d, time(14, mm), tzinfo=VN_TZ)
            for sym, sim in sims.items():
                writer.write("stockInfo", self._payload(sym, sim, self.n - 1, ato="ATC"), ts)
        writer.write("marketSession", {"marketCode": "HOSE", "marketStatus": "ATC",
                                       "time": datetime.combine(d, time(14, 30), tzinfo=VN_TZ).isoformat()},
                     datetime.combine(d, time(14, 30), tzinfo=VN_TZ))
        writer.write("marketSession", {"marketCode": "HOSE", "marketStatus": "C",
                                       "time": datetime.combine(d, time(15, 0), tzinfo=VN_TZ).isoformat()},
                     datetime.combine(d, time(15, 0), tzinfo=VN_TZ))
        return {"events_truth": self.events, "gaps": {k: [int(a), int(b)] for k, (a, b) in gaps.items()}}

    def _payload(self, sym: str, sim: dict, i: int, ato: str | None = None) -> dict[str, Any]:
        rng = self.rng
        traps = self.cfg.synth.traps.as_dict()
        book = sim["book"]
        p: dict[str, Any] = {"symbol": sym}
        p["ceilingPrice"] = float(sim["ceiling"])
        p["floorPrice"] = float(sim["floor"])
        p["refPrice"] = float(sim["ref"])
        for side in ("bid", "ask"):
            for lvl in (1, 2, 3):
                px = float(book[f"{side}{lvl}"][i])
                vol = int(book[f"{side}vol{lvl}"][i])
                if lvl == 1:
                    p[f"{side}Price1"] = ato if ato else f"{px:.1f}"  # chuỗi như docs
                else:
                    p[f"{side}Price{lvl}"] = px
                if lvl == 3 and rng.random() < traps["missing_field_p"]:
                    continue  # thiếu trường mức 3
                p[f"{side}Vol{lvl}"] = vol
        lp = sim["last_price"][i]
        p["closePrice"] = float(lp) if np.isfinite(lp) else float(sim["ref"])
        p["closeVol"] = int(sim["last_vol"][i])
        p["priceChange"] = p["closePrice"] - p["refPrice"]
        p["percentPriceChange"] = round(p["priceChange"] / p["refPrice"] * 100, 2)
        p["openPrice"] = float(sim["open"])
        p["highPrice"] = float(sim["high"][i]) if np.isfinite(sim["high"][i]) else p["closePrice"]
        p["lowPrice"] = float(sim["low"][i]) if np.isfinite(sim["low"][i]) else p["closePrice"]
        p["averagePrice"] = float(sim["avg"][i]) if np.isfinite(sim["avg"][i]) else p["closePrice"]
        p["totalTradingVolume"] = int(sim["cum_vol"][i])
        p["totalTradingValue"] = int(sim["cum_val"][i])
        null_p = traps["null_total_qty_p"]
        p["totalBidQTTY"] = None if rng.random() < null_p else int(sum(book[f"bidvol{l}"][i] for l in (1, 2, 3)) * rng.uniform(1.2, 2.0))
        p["totalAskQTTY"] = None if rng.random() < null_p else int(sum(book[f"askvol{l}"][i] for l in (1, 2, 3)) * rng.uniform(1.2, 2.0))
        p["foreignBuyVolume"] = int(sim["f_buy_vol"][i])
        p["foreignSellVolume"] = int(sim["f_sell_vol"][i])
        p["foreignBuyValue"] = int(sim["f_buy_val"][i])
        p["foreignSellValue"] = int(sim["f_sell_val"][i])
        p["foreignNetValue"] = int(sim["f_buy_val"][i] - sim["f_sell_val"][i])
        p["foreignRemain"] = int(sim["f_remain"][i])
        p["foreignRoom"] = int(sim["f_room"])
        p["breakEvenPoint"] = 0
        return p

    def _emit_index(self, writer: RawWriter, sims: dict, i: int, ts: datetime) -> None:
        rng = self.rng
        ratios = np.array([sim["mid"][i] / sim["ref"] for sim in sims.values()])
        agg = float(np.mean(ratios))
        total_vol = int(sum(sim["cum_vol"][i] for sim in sims.values()))
        total_val = int(sum(sim["cum_val"][i] for sim in sims.values()))
        bg = rng.normal(agg - 1, 0.004, 30)
        advances = int((bg > 0.0005).sum())
        declines = int((bg < -0.0005).sum())
        for code, base in (("VNINDEX", 1250.0), ("VN30", 1310.0)):
            val = base * agg * (1 + rng.normal(0, 0.0002))
            payload = {
                "dateString": self.date_str, "indexCode": code,
                "indexValue": f"{val:.2f}",  # chuỗi như docs
                "indexTime": ts.strftime("%H:%M:%S"),
                "indexChange": round(val - base, 2),
                "indexPercentChange": round((val / base - 1) * 100, 2),
                "totalVolume": total_vol * (18 if code == "VNINDEX" else 8),
                "totalValue": total_val * (18 if code == "VNINDEX" else 8),
                "marketStatus": "LO", "marketCode": code,
                "advances": advances * 12, "declines": declines * 12,
                "noChange": (30 - advances - declines) * 12,
                "numberOfCe": int(rng.integers(0, 4)), "numberOfFl": int(rng.integers(0, 3)),
                "oddLotTotalVolume": 0, "oddLotTotalValue": 0,
            }
            writer.write("marketInfo", payload, ts)
            writer.write("marketVolume", {"indexCode": code, "indexValue": f"{val:.2f}",
                                          "indexTime": ts.strftime("%H:%M:%S"),
                                          "totalVolume": payload["totalVolume"],
                                          "volume": int(rng.integers(1000, 50000))}, ts)


def generate_dataset(settings: Settings, n_sessions: int | None = None) -> list[Path]:
    """Sinh toàn bộ bộ dữ liệu SYNTHETIC (raw JSONL.gz + events truth)."""
    n = n_sessions or int(settings.synth.n_sessions)
    dates = _session_dates(str(settings.synth.end_date), n)
    out: list[Path] = []
    for idx, ds in enumerate(dates):
        session_dir = settings.data_path("raw", f"SYNTH_{ds}")
        if (session_dir / "manifest.json").exists():
            out.append(session_dir)
            continue
        sim = SessionSimulator(settings, ds, idx)
        writer = RawWriter(session_dir, "SYNTHETIC", meta={
            "seed": sim.seed, "session_date": ds,
            "generator_version": GENERATOR_VERSION,
            "config_hash": settings.config_hash,
        })
        info = sim.emit(writer)
        truth_path = session_dir / "events_truth.json"
        truth_path.write_text(json.dumps(
            {"synthetic": True, "events": info["events_truth"], "gaps": info["gaps"]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        writer.close()
        out.append(session_dir)
    return out
