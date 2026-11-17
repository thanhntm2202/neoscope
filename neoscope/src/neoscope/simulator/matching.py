"""Buồng thử khớp lệnh MÔ PHỎNG — không bao giờ phát sinh lệnh thật.

Giao thức thực thi (công bố đầy đủ trong docs/methodology.md):
1. Tại t0: lệnh chủ động quét sổ hiển thị 3 mức (giả định tiếp cận toàn bộ
   KL hiển thị — KHÔNG mô phỏng ưu tiên hàng đợi; đây là hạn chế đã nêu).
2. Phần dư: tham gia thị trường — mỗi nhịp 5s hấp thụ tối đa ρ×KL khớp thực
   của nhịp đó, tại giá phía tốt nhất hiện hành (bid1 cho bán, ask1 cho mua).
3. Sau chân trời H: phần chưa khớp định giá theo mid (opportunity cost).

Thời gian hoàn thành phụ thuộc QUY MÔ lệnh → rủi ro thời điểm tăng theo
√(Q_res/V) một cách NỘI SINH (định luật căn bậc hai xuất hiện từ giao thức,
không bị áp đặt). Lưu ý trung thực: sổ lệnh tương lai không phản hồi lệnh
của ta (không own-impact) → realized là cận dưới của chi phí thật với lệnh
rất lớn. Điều này được nêu trong báo cáo và tab Kiểm chứng.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..finance.execution import ladder_walk, trading_costs_bps
from ..finance.microstructure import BPS


@dataclass
class SimResult:
    realized_is_bps: float
    vwap_exec: float
    mid_arr: float
    filled_frac: float
    unfilled_frac: float
    exec_time_s: float
    n_steps: int
    fee_vnd: float
    tax_vnd: float
    flags: list[str] = field(default_factory=list)
    ok: bool = True


def simulate_order(
    snaps: pd.DataFrame,
    ts0: pd.Timestamp,
    side: int,
    qty: float,
    rho: float,
    horizon_s: float,
    fee_rate: float,
    sell_tax_rate: float,
) -> SimResult:
    """Khớp lệnh mô phỏng trên chuỗi snapshot CHUẨN HÓA của một mã-phiên.

    `snaps` phải sắp xếp theo ts và chỉ chứa một mã trong một phiên.
    """
    idx = int(snaps["ts"].searchsorted(ts0, side="right")) - 1
    if idx < 0:
        return SimResult(np.nan, np.nan, np.nan, 0, 1, 0, 0, 0, 0, ["NO_ARRIVAL_SNAP"], ok=False)
    arr = snaps.iloc[idx]
    mid_arr = float(arr["mid"]) if pd.notna(arr["mid"]) else np.nan
    if not np.isfinite(mid_arr) or mid_arr <= 0:
        return SimResult(np.nan, np.nan, np.nan, 0, 1, 0, 0, 0, 0, ["NO_BOOK"], ok=False)

    if side == -1:
        prices = [arr.get("bid1"), arr.get("bid2"), arr.get("bid3")]
        vols = [arr.get("bidvol1"), arr.get("bidvol2"), arr.get("bidvol3")]
    else:
        prices = [arr.get("ask1"), arr.get("ask2"), arr.get("ask3")]
        vols = [arr.get("askvol1"), arr.get("askvol2"), arr.get("askvol3")]
    prices = [float(p) if pd.notna(p) else None for p in prices]
    vols = [float(v) if pd.notna(v) else None for v in vols]

    lad = ladder_walk(side, qty, prices, vols, mid_arr)
    filled = lad.filled_vis
    notional = (lad.vwap_vis or 0.0) * filled
    remaining = qty - filled
    flags: list[str] = []
    if not lad.ok:
        flags.append("EMPTY_VISIBLE_BOOK")

    t_end = ts0 + pd.Timedelta(seconds=horizon_s)
    post = snaps[(snaps["ts"] > ts0) & (snaps["ts"] <= t_end)]
    n_steps = 0
    exec_time = 0.0
    px_col = "bid1" if side == -1 else "ask1"
    for _, row in post.iterrows():
        if remaining <= 0:
            break
        dv = row.get("d_vol")
        cap = rho * float(dv) if pd.notna(dv) else 0.0
        px = row.get(px_col)
        if cap <= 0 or pd.isna(px):
            continue
        take = min(remaining, cap)
        notional += take * float(px)
        remaining -= take
        filled += take
        n_steps += 1
        exec_time = float((row["ts"] - ts0).total_seconds())

    if remaining > 0:
        mid_h = post["mid"].dropna()
        mark_px = float(mid_h.iloc[-1]) if len(mid_h) else mid_arr
        notional += remaining * mark_px
        flags.append("UNFILLED_PARTIAL")

    vwap = notional / qty
    realized = side * (vwap - mid_arr) / mid_arr * BPS
    executed_notional = notional - (remaining * (mark_px if remaining > 0 else 0.0))
    costs = trading_costs_bps(executed_notional, side, fee_rate, sell_tax_rate)
    return SimResult(
        realized_is_bps=float(realized), vwap_exec=float(vwap), mid_arr=mid_arr,
        filled_frac=filled / qty, unfilled_frac=remaining / qty,
        exec_time_s=exec_time, n_steps=n_steps,
        fee_vnd=costs["fee_vnd"], tax_vnd=costs["tax_vnd"], flags=flags, ok=True,
    )


def generate_orders(
    snaps_session: pd.DataFrame,
    symbols: list[str],
    orders_per_symbol: int,
    size_range_vnd: tuple[float, float],
    seed: int,
    horizon_s: float,
) -> pd.DataFrame:
    """Sinh lệnh thử nghiệm TẤT ĐỊNH theo seed — phân bố đều trong phiên LO.

    Loại 3 phút đầu (ổn định sau ATO) và đoạn cuối ngắn hơn chân trời H
    (để mọi lệnh có đủ cửa sổ mô phỏng). Quy mô log-uniform trong dải cấu hình.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    lo = snaps_session[snaps_session["session"].isin(["LO_AM", "LO_PM"])]
    for sym in symbols:
        s = lo[lo["symbol"] == sym].sort_values("ts")
        if s.empty:
            continue
        t_min = s["ts"].min() + pd.Timedelta(minutes=3)
        t_max = s["ts"].max() - pd.Timedelta(seconds=horizon_s + 30)
        span = (t_max - t_min).total_seconds()
        if span <= 0:
            continue
        for k in range(orders_per_symbol):
            ts = t_min + pd.Timedelta(seconds=float(rng.uniform(0, span)))
            side = int(rng.choice([-1, 1]))
            notional = float(np.exp(rng.uniform(np.log(size_range_vnd[0]), np.log(size_range_vnd[1]))))
            idx = int(s["ts"].searchsorted(ts, side="right")) - 1
            if idx < 0:
                continue
            mid = s.iloc[idx]["mid"]
            if pd.isna(mid) or mid <= 0:
                continue
            qty = max(round(notional / float(mid) / 100) * 100, 100)
            rows.append({
                "order_id": f"{sym}-{seed}-{k}",
                "symbol": sym, "ts": ts, "side": side,
                "qty_shares": float(qty),
                "notional_vnd": qty * float(mid),
                "mid_arr": float(mid),
            })
    return pd.DataFrame(rows)
