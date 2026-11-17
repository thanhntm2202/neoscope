"""Hiệu chỉnh tham số & WALK-FORWARD ngoài mẫu — trái tim của kiểm chứng.

Giao thức (docs/validation_protocol.md):
- Phiên sắp xếp theo thời gian; fold k: train = phiên 1..k, test = phiên k+1
  (k = 5..9 với 10 phiên). KHÔNG xáo trộn, KHÔNG nhìn trước.
- κ (trôi giá trên mỗi đơn vị OBI): hồi quy qua gốc lợi nhuận phút kế tiếp
  lên OBI hiện tại, CHỈ trên bar phiên train, theo nhóm mã.
- v̂ (profile khối lượng): trung bình KL khớp/nhịp theo mã × bucket 15' train.
- σ̂ tại thời điểm đặt: std lợi nhuận phút trượt 15' TRONG phiên (quy đổi
  bps/√giây); thiếu → fallback trung vị nhóm × bucket từ train.
- Y (tỷ lệ rủi ro thời điểm): hiệu chỉnh để khoảng dự báo 90% đạt độ phủ
  danh nghĩa trên lệnh train: Y = q90(|e|/x)/1.6449, x = σ̂·√τ_eff.
  Báo cáo thêm Y_rmse để minh bạch.
- Ba mô hình so sánh: naive_mid (E=0), ladder_only (phần dư tại giá tốt
  nhất hiện hành, không trôi giá), full (ladder + hs + κ·OBI·τ/2 + rủi ro √).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from ..config import Settings
from ..finance.execution import expected_is_bps, ladder_walk
from ..simulator.matching import generate_orders, simulate_order

PI_Z = 1.6449


# ------------------------------------------------------------------ profile
def volume_profile(bars_train: pd.DataFrame) -> dict[tuple, float]:
    """v̂ (cổ phiếu/giây) theo (symbol, bucket); fallback (group, bucket) rồi symbol."""
    out: dict[tuple, float] = {}
    g = bars_train.groupby(["symbol", "bucket"])["d_vol"].mean() / 60.0
    for (sym, b), v in g.items():
        out[(sym, int(b))] = float(v)
    gg = bars_train.groupby(["group", "bucket"])["d_vol"].mean() / 60.0
    for (grp, b), v in gg.items():
        out[("GRP", grp, int(b))] = float(v)
    gs = bars_train.groupby("symbol")["d_vol"].mean() / 60.0
    for sym, v in gs.items():
        out[("SYM", sym)] = float(v)
    return out


def lookup_v_rate(profile: dict, symbol: str, group: str, bucket: int) -> float:
    return profile.get((symbol, bucket),
                       profile.get(("GRP", group, bucket),
                                   profile.get(("SYM", symbol), np.nan)))


def sigma_fallback(bars_train: pd.DataFrame) -> dict[tuple, float]:
    """σ bps/√giây pooled theo nhóm × bucket (dùng khi σ trượt thiếu mẫu)."""
    out: dict[tuple, float] = {}
    for (grp, b), g in bars_train.groupby(["group", "bucket"]):
        sd = g["ret_bps"].std()
        if np.isfinite(sd):
            out[(grp, int(b))] = float(sd / np.sqrt(60.0))
    return out


# ------------------------------------------------------------------ kappa
def fit_kappa(bars_train: pd.DataFrame) -> pd.DataFrame:
    """κ: hồi quy qua gốc r_{t+1} = κ·OBI_t + ε, theo nhóm mã, chỉ bar liền kề."""
    b = bars_train.sort_values(["symbol", "session_date", "bar_ts"]).copy()
    grp_key = ["symbol", "session_date"]
    b["ret_next"] = b.groupby(grp_key)["ret_bps"].shift(-1)
    dt_next = b.groupby(grp_key)["bar_ts"].shift(-1) - b["bar_ts"]
    b.loc[dt_next > pd.Timedelta(seconds=90), "ret_next"] = np.nan
    rows = []
    for grp, g in b.groupby("group"):
        m = g[["obi_last", "ret_next"]].dropna()
        x = m["obi_last"].to_numpy()
        y = m["ret_next"].to_numpy()
        xx = float((x * x).sum())
        if len(m) < 50 or xx <= 0:
            rows.append({"group": grp, "kappa_bps_per_s": 0.0, "se": np.nan, "r2": np.nan, "n": len(m)})
            continue
        k_min = float((x * y).sum() / xx)
        resid = y - k_min * x
        se = float(np.sqrt((resid ** 2).sum() / (len(m) - 1) / xx))
        r2 = float(1 - (resid ** 2).sum() / max((y ** 2).sum(), 1e-12))
        k_clip = max(k_min, 0.0)  # tiên nghiệm kinh tế: OBI dương → trôi lên
        rows.append({"group": grp, "kappa_bps_per_s": k_clip / 60.0,
                     "kappa_raw_bps_per_min": k_min, "se": se / 60.0, "r2": r2, "n": len(m)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ features
def static_features(order: dict, snaps_sym: pd.DataFrame, bars_sym: pd.DataFrame,
                    settings: Settings) -> dict[str, Any] | None:
    """Phần đặc trưng KHÔNG phụ thuộc fold: sổ lệnh tại t0, hs, OBI, σ trượt."""
    ts0 = order["ts"]
    idx = int(snaps_sym["ts"].searchsorted(ts0, side="right")) - 1
    if idx < 0:
        return None
    arr = snaps_sym.iloc[idx]
    mid = float(arr["mid"]) if pd.notna(arr["mid"]) else np.nan
    if not np.isfinite(mid):
        return None
    side = int(order["side"])
    if side == -1:
        prices = [arr.get("bid1"), arr.get("bid2"), arr.get("bid3")]
        vols = [arr.get("bidvol1"), arr.get("bidvol2"), arr.get("bidvol3")]
    else:
        prices = [arr.get("ask1"), arr.get("ask2"), arr.get("ask3")]
        vols = [arr.get("askvol1"), arr.get("askvol2"), arr.get("askvol3")]
    prices = [float(p) if pd.notna(p) else None for p in prices]
    vols = [float(v) if pd.notna(v) else None for v in vols]
    lad = ladder_walk(side, float(order["qty_shares"]), prices, vols, mid)
    if not lad.ok:
        return None
    hs = float(arr["spread_bps"]) / 2.0 if pd.notna(arr["spread_bps"]) else np.nan
    obi_now = float(arr["obi"]) if pd.notna(arr["obi"]) else 0.0
    bucket = int(arr["bucket"])
    # σ trượt trong phiên tại bar gần nhất ≤ t0
    bs = bars_sym[bars_sym["bar_ts"] <= ts0]
    sig = np.nan
    if len(bs) >= 5:
        sd = bs["ret_bps"].tail(15).std()
        if np.isfinite(sd):
            sig = float(sd / np.sqrt(60.0))
    return {"ladder": lad, "hs_bps": hs, "obi_now": obi_now, "bucket": bucket,
            "sigma_trail": sig, "mid_arr": mid}


def predict_all_models(feat: dict, order: dict, v_rate: float, sigma: float,
                       kappa: float, y_risk: float, settings: Settings) -> dict[str, dict]:
    side = int(order["side"])
    qty = float(order["qty_shares"])
    ex = settings.execution
    full = expected_is_bps(
        side, qty, feat["ladder"], feat["hs_bps"], feat["obi_now"], kappa,
        v_rate, sigma, float(ex.participation_rate), float(ex.horizon_s),
        y_risk, float(ex.pi_z),
    )
    lad = feat["ladder"]
    hs = feat["hs_bps"] if np.isfinite(feat["hs_bps"]) else 0.0
    w_vis = lad.filled_vis / qty
    w_res = lad.qty_res / qty
    ladder_only_e = w_vis * lad.cost_vis_bps + w_res * hs
    return {
        "naive_mid": {"e": 0.0, "sigma": 0.0, "lo": 0.0, "hi": 0.0},
        "ladder_only": {"e": float(ladder_only_e), "sigma": 0.0,
                        "lo": float(ladder_only_e), "hi": float(ladder_only_e)},
        "full": {"e": full.e_is_bps, "sigma": full.sigma_is_bps,
                 "lo": full.lo_bps, "hi": full.hi_bps},
        "_full_obj": full,
    }


def fit_y(train_rows: list[dict]) -> tuple[float, float, int]:
    """Y phủ 90% và Y_rmse từ các lệnh train (e = realized − E_full, x = σ√τ_eff)."""
    xs, es = [], []
    for r in train_rows:
        x = r["sigma_used"] * np.sqrt(max(r["tau_eff"], 0.0))
        if x > 1e-9 and np.isfinite(r["e_resid"]):
            xs.append(x)
            es.append(r["e_resid"])
    if len(xs) < 30:
        return 1.0, 1.0, len(xs)
    ratio = np.abs(np.array(es)) / np.array(xs)
    y_cov = float(np.quantile(ratio, 0.90) / PI_Z)
    y_rmse = float(np.sqrt(np.mean(ratio ** 2)))
    return max(y_cov, 0.05), max(y_rmse, 0.05), len(xs)


# ------------------------------------------------------------------ walk-forward
def run_walk_forward(settings: Settings, snaps_all: pd.DataFrame,
                     bars_all: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = sorted(snaps_all["session_date"].unique())
    n = len(dates)
    min_train = int(settings.validation.min_train_sessions)
    if n <= min_train:
        raise RuntimeError(f"Cần > {min_train} phiên để walk-forward; hiện có {n}.")
    ex = settings.execution
    symbols = settings.watchlist()

    # ---- 1) sinh lệnh + mô phỏng realized cho MỌI phiên (seed tất định) ----
    orders_rows: list[dict] = []
    feats: dict[str, dict] = {}
    snaps_by = { (ds, sym): g.sort_values("ts").reset_index(drop=True)
                 for (ds, sym), g in snaps_all.groupby(["session_date", "symbol"]) }
    bars_by = { (ds, sym): g.sort_values("bar_ts").reset_index(drop=True)
                for (ds, sym), g in bars_all.groupby(["session_date", "symbol"]) }
    for i, ds in enumerate(dates):
        snap_day = snaps_all[snaps_all["session_date"] == ds]
        orders = generate_orders(
            snap_day, symbols, int(ex.orders_per_symbol_session),
            (float(ex.order_sizes_vnd[0]), float(ex.order_sizes_vnd[1])),
            seed=50_000 + i, horizon_s=float(ex.horizon_s),
        )
        for _, o in orders.iterrows():
            od = o.to_dict()
            od["session_date"] = ds
            od["group"] = settings.group_of(od["symbol"])
            key = (ds, od["symbol"])
            sim = simulate_order(
                snaps_by[key], od["ts"], int(od["side"]), float(od["qty_shares"]),
                float(ex.participation_rate), float(ex.horizon_s),
                float(ex.fee_rate), float(ex.sell_tax_rate),
            )
            if not sim.ok or not np.isfinite(sim.realized_is_bps):
                continue
            od.update({
                "realized_is_bps": sim.realized_is_bps, "filled_frac": sim.filled_frac,
                "unfilled_frac": sim.unfilled_frac, "exec_time_s": sim.exec_time_s,
                "sim_flags": ",".join(sim.flags),
            })
            f = static_features(od, snaps_by[key], bars_by[key], settings)
            if f is None:
                continue
            feats[od["order_id"]] = f
            orders_rows.append(od)
    orders_df = pd.DataFrame(orders_rows)
    logger.info("Walk-forward: {} lệnh mô phỏng hợp lệ trên {} phiên", len(orders_df), n)

    # ---- 2) các fold ----
    pred_rows: list[dict] = []
    param_rows: list[dict] = []
    orders_by_date = {ds: g for ds, g in orders_df.groupby("session_date")}
    for k in range(min_train, n):
        train_dates, test_date = dates[:k], dates[k]
        bars_train = bars_all[bars_all["session_date"].isin(train_dates)]
        profile = volume_profile(bars_train)
        sig_fb = sigma_fallback(bars_train)
        kappa_df = fit_kappa(bars_train)
        kappa_map = {r["group"]: float(r["kappa_bps_per_s"]) for _, r in kappa_df.iterrows()}

        # hiệu chỉnh Y trên lệnh train (κ đã fit trên train; công bố trong docs)
        train_fit_rows: dict[str, list[dict]] = {"large": [], "thin": []}
        for ds in train_dates:
            for _, od in orders_by_date.get(ds, pd.DataFrame()).iterrows():
                f = feats[od["order_id"]]
                grp = od["group"]
                sigma = f["sigma_trail"] if np.isfinite(f["sigma_trail"]) else sig_fb.get((grp, f["bucket"]), np.nan)
                vr = lookup_v_rate(profile, od["symbol"], grp, f["bucket"])
                preds = predict_all_models(f, od.to_dict(), vr, sigma, kappa_map.get(grp, 0.0), 1.0, settings)
                full = preds["_full_obj"]
                train_fit_rows[grp].append({
                    "e_resid": od["realized_is_bps"] - full.e_is_bps,
                    "sigma_used": full.detail["sigma_bps_per_s"], "tau_eff": full.detail["tau_eff"],
                })
        y_map: dict[str, tuple[float, float, int]] = {}
        for grp in ("large", "thin"):
            y_map[grp] = fit_y(train_fit_rows[grp])

        # dự báo lệnh test
        for _, od in orders_by_date.get(test_date, pd.DataFrame()).iterrows():
            f = feats[od["order_id"]]
            grp = od["group"]
            sigma = f["sigma_trail"] if np.isfinite(f["sigma_trail"]) else sig_fb.get((grp, f["bucket"]), np.nan)
            vr = lookup_v_rate(profile, od["symbol"], grp, f["bucket"])
            y_cov = y_map[grp][0]
            preds = predict_all_models(f, od.to_dict(), vr, sigma, kappa_map.get(grp, 0.0), y_cov, settings)
            full = preds["_full_obj"]
            for model in ("naive_mid", "ladder_only", "full"):
                p = preds[model]
                pred_rows.append({
                    "fold": k, "session_date": test_date, "order_id": od["order_id"],
                    "symbol": od["symbol"], "group": grp, "model": model,
                    "e_is_bps": p["e"], "sigma_is_bps": p["sigma"],
                    "lo_bps": p["lo"], "hi_bps": p["hi"],
                    "realized_is_bps": od["realized_is_bps"],
                    "notional_vnd": od["notional_vnd"], "side": od["side"],
                    "coverage": full.coverage, "tau_s": full.tau_s,
                    "w_res": full.w_res, "w_unf": full.w_unf,
                    "flags": ",".join(full.flags),
                })
        for grp in ("large", "thin"):
            kr = kappa_df[kappa_df["group"] == grp].iloc[0]
            param_rows.append({
                "fold": k, "test_date": test_date, "group": grp,
                "kappa_bps_per_s": kr["kappa_bps_per_s"], "kappa_se": kr["se"],
                "kappa_r2": kr["r2"], "n_kappa": int(kr["n"]),
                "y_cov": y_map[grp][0], "y_rmse": y_map[grp][1], "n_train_orders": y_map[grp][2],
            })
        logger.info("Fold {}: train {} phiên → test {} | κ={} | Y={}",
                    k, k, test_date,
                    {g: round(kappa_map.get(g, 0), 4) for g in ('large', 'thin')},
                    {g: round(y_map[g][0], 3) for g in ('large', 'thin')})
    return orders_df, pd.DataFrame(pred_rows), pd.DataFrame(param_rows)
