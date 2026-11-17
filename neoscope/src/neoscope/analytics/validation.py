"""Kiểm chứng ngoài mẫu: sai số, bootstrap theo cụm phiên, độ phủ PI,
giá trị xây dựng của LHS, sức dự báo của OBI, precision/recall cảnh báo.

Vì sao bootstrap THEO PHIÊN (không theo lệnh): các lệnh trong cùng phiên
chung chế độ thị trường → sai số tương quan nội phiên; gom cụm theo phiên
là đơn vị độc lập gần đúng nhất (5 cụm test — công bố hạn chế công suất
thống kê, khoảng CI rộng là trung thực, không phải lỗi).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ..config import Settings
from ..data.store import list_session_dirs, session_date_of


# ------------------------------------------------------------------ sai số
def metrics_table(preds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (model, grp), g in preds.groupby(["model", "group"]):
        e = g["e_is_bps"] - g["realized_is_bps"]
        rows.append({"model": model, "group": grp, "n": len(g),
                     "mae_bps": float(e.abs().mean()), "rmse_bps": float(np.sqrt((e ** 2).mean())),
                     "bias_bps": float(e.mean())})
    for model, g in preds.groupby("model"):
        e = g["e_is_bps"] - g["realized_is_bps"]
        rows.append({"model": model, "group": "ALL", "n": len(g),
                     "mae_bps": float(e.abs().mean()), "rmse_bps": float(np.sqrt((e ** 2).mean())),
                     "bias_bps": float(e.mean())})
    return pd.DataFrame(rows)


def session_bootstrap(preds: pd.DataFrame, model_a: str, model_b: str,
                      reps: int = 2000, seed: int = 7) -> dict:
    """So sánh MAE cặp đôi theo cụm phiên: Δ = MAE_a − MAE_b (âm = a tốt hơn)."""
    a = preds[preds["model"] == model_a].copy()
    b = preds[preds["model"] == model_b].copy()
    a["loss"] = (a["e_is_bps"] - a["realized_is_bps"]).abs()
    b["loss"] = (b["e_is_bps"] - b["realized_is_bps"]).abs()
    la = a.groupby("session_date")["loss"].mean()
    lb = b.groupby("session_date")["loss"].mean()
    d = (la - lb).dropna()
    sessions = d.index.to_numpy()
    vals = d.to_numpy()
    rng = np.random.default_rng(seed)
    boots = np.array([vals[rng.integers(0, len(vals), len(vals))].mean() for _ in range(reps)])
    lo, hi = np.quantile(boots, [0.025, 0.975])
    p_two = float(min(1.0, 2 * min((boots >= 0).mean(), (boots <= 0).mean())))
    return {"model_a": model_a, "model_b": model_b,
            "delta_mae_bps": float(vals.mean()), "ci95_lo": float(lo), "ci95_hi": float(hi),
            "p_two_sided": p_two, "n_sessions": len(vals),
            "per_session": {str(s): float(v) for s, v in zip(sessions, vals)}}


# ------------------------------------------------------------------ độ phủ PI
def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return float(center - half), float(center + half)


def pi_coverage(preds: pd.DataFrame) -> pd.DataFrame:
    full = preds[preds["model"] == "full"]
    rows = []
    for grp, g in [("ALL", full)] + list(full.groupby("group")):
        ok = ((g["realized_is_bps"] >= g["lo_bps"]) & (g["realized_is_bps"] <= g["hi_bps"])).sum()
        n = len(g)
        lo, hi = _wilson(int(ok), n)
        rows.append({"group": grp, "n": n, "covered": int(ok),
                     "coverage": float(ok / n) if n else np.nan,
                     "wilson_lo": lo, "wilson_hi": hi,
                     "mean_width_bps": float((g["hi_bps"] - g["lo_bps"]).mean())})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ LHS / OBI
def lhs_forward_ic(bars_lhs: pd.DataFrame, test_dates: list[str]) -> pd.DataFrame:
    """Giá trị xây dựng: Spearman(LHS_t, ILLIQ 15' tương lai) chéo mã, theo phiên."""
    rows = []
    for ds in test_dates:
        day = bars_lhs[bars_lhs["session_date"] == ds].sort_values(["symbol", "bar_ts"])
        fwd_absret = day.groupby("symbol")["ret_bps"].transform(
            lambda s: s.abs().shift(-1).rolling(15, min_periods=10).sum().shift(-14))
        fwd_val = day.groupby("symbol")["d_val"].transform(
            lambda s: s.shift(-1).rolling(15, min_periods=10).sum().shift(-14))
        day = day.assign(fwd_illiq=np.where(fwd_val > 0, fwd_absret / (fwd_val / 1e9), np.nan))
        ics = []
        for _, g in day.groupby("bar_ts"):
            m = g[["lhs", "fwd_illiq"]].dropna()
            if len(m) >= 6:
                rho, _ = stats.spearmanr(m["lhs"], m["fwd_illiq"])
                if np.isfinite(rho):
                    ics.append(rho)
        if ics:
            rows.append({"session_date": ds, "mean_ic": float(np.mean(ics)),
                         "std_ic": float(np.std(ics)), "n_obs": len(ics)})
    return pd.DataFrame(rows)


def obi_direction_table(bars: pd.DataFrame, test_dates: list[str]) -> pd.DataFrame:
    """Sức dự báo hướng giá 1 phút của OBI theo ngũ phân vị (ngoài mẫu)."""
    b = bars[bars["session_date"].isin(test_dates)].sort_values(["symbol", "session_date", "bar_ts"]).copy()
    grp_key = ["symbol", "session_date"]
    b["ret_next"] = b.groupby(grp_key)["ret_bps"].shift(-1)
    dt_next = b.groupby(grp_key)["bar_ts"].shift(-1) - b["bar_ts"]
    b.loc[dt_next > pd.Timedelta(seconds=90), "ret_next"] = np.nan
    m = b[["obi_last", "ret_next"]].dropna()
    if m.empty:
        return pd.DataFrame()
    m["quintile"] = pd.qcut(m["obi_last"], 5, labels=False, duplicates="drop") + 1
    out = m.groupby("quintile").agg(
        n=("ret_next", "size"),
        obi_mean=("obi_last", "mean"),
        p_up=("ret_next", lambda s: float((s > 0).mean())),
        mean_ret_bps=("ret_next", "mean"),
    ).reset_index()
    return out


# ------------------------------------------------------------------ alerts PR
ALERT_EVENT_MAP = {
    "SPREAD_WIDEN": {"DEPTH_EVAPORATION", "FLASH_MOVE"},
    "DEPTH_EVAPORATION": {"DEPTH_EVAPORATION"},
    "OBI_EXTREME": {"DEPTH_EVAPORATION", "TRADE_BURST", "FLASH_MOVE"},
    "TRADE_BURST": {"TRADE_BURST", "FLASH_MOVE"},
    "FOREIGN_BURST": {"FOREIGN_BURST"},
}


def alert_precision_recall(alerts: pd.DataFrame, settings: Settings,
                           tolerance_s: float = 30.0) -> pd.DataFrame:
    """Đối chiếu cảnh báo với sự kiện ground-truth (CHỈ có ở chế độ SYNTHETIC).

    Mỗi cảnh báo là TP nếu rơi vào cửa sổ [start−30s, end+30s] của một sự kiện
    cùng mã, loại tương ứng theo ALERT_EVENT_MAP (công bố trong docs).
    Recall tính theo SỰ KIỆN: tỷ lệ sự kiện có ≥1 cảnh báo khớp.
    Đây là kiểm chứng CƠ CHẾ cảnh báo, không phải hiệu quả ngoài đời thật.
    """
    truth = []
    for d in list_session_dirs(settings.data_path(), settings.mode):
        p = d / "events_truth.json"
        if p.exists():
            ev = json.loads(p.read_text(encoding="utf-8"))["events"]
            for e in ev:
                e["session_date"] = session_date_of(d)
                truth.append(e)
    if not truth or alerts.empty:
        return pd.DataFrame()
    tdf = pd.DataFrame(truth)
    tdf["start"] = pd.to_datetime(tdf["start_ts"]) - pd.Timedelta(seconds=tolerance_s)
    tdf["end"] = pd.to_datetime(tdf["end_ts"]) + pd.Timedelta(seconds=tolerance_s)
    matched_events: set[int] = set()
    tp_flags = []
    for _, a in alerts.iterrows():
        cand = tdf[(tdf["symbol"] == a["symbol"]) & (tdf["session_date"] == a["session_date"])
                   & (tdf["type"].isin(ALERT_EVENT_MAP.get(a["type"], set())))
                   & (tdf["start"] <= a["ts"]) & (tdf["end"] >= a["ts"])]
        tp_flags.append(len(cand) > 0)
        for idx in cand.index:
            matched_events.add(int(idx))
    alerts = alerts.assign(tp=tp_flags)
    rows = []
    for atype, g in alerts.groupby("type"):
        ev_types = ALERT_EVENT_MAP.get(atype, set())
        ev_pool = tdf[tdf["type"].isin(ev_types)]
        ev_hit = ev_pool.index.isin(matched_events).sum()
        rows.append({"alert_type": atype, "n_alerts": len(g), "tp": int(g["tp"].sum()),
                     "precision": float(g["tp"].mean()),
                     "n_events_mapped": len(ev_pool), "events_detected": int(ev_hit),
                     "recall": float(ev_hit / len(ev_pool)) if len(ev_pool) else np.nan})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ summary
def build_summary(settings: Settings, metrics: pd.DataFrame, boot_full_ladder: dict,
                  boot_full_naive: dict, coverage: pd.DataFrame, ic: pd.DataFrame,
                  obi_tab: pd.DataFrame, pr: pd.DataFrame, fold_params: pd.DataFrame,
                  orders: pd.DataFrame, preds: pd.DataFrame,
                  lhs_sens: pd.DataFrame, resilience_stats: dict,
                  quality_meta: pd.DataFrame, snaps_all: pd.DataFrame) -> dict:
    dates = sorted(snaps_all["session_date"].unique())
    test_dates = dates[int(settings.validation.min_train_sessions):]
    summary = {
        "mode": settings.mode,
        "synthetic": settings.mode == "SYNTHETIC",
        "dataset": {
            "n_sessions": len(dates), "dates": dates,
            "n_symbols": snaps_all["symbol"].nunique(),
            "symbols": sorted(snaps_all["symbol"].unique().tolist()),
            "n_snapshots": len(snaps_all),
            "test_dates": test_dates,
        },
        "quality": {
            "n_raw_total": int(quality_meta["n_raw"].sum()) if not quality_meta.empty else None,
            "n_curated_total": int(quality_meta["n_curated"].sum()) if not quality_meta.empty else None,
            "n_duplicates_dropped": int(quality_meta["n_duplicates_dropped"].sum()) if not quality_meta.empty else None,
        },
        "orders": {"n": len(orders),
                   "mean_notional_vnd": float(orders["notional_vnd"].mean()) if len(orders) else None,
                   "mean_unfilled_frac": float(orders["unfilled_frac"].mean()) if len(orders) else None},
        "metrics": metrics.to_dict(orient="records"),
        "bootstrap_full_vs_ladder": boot_full_ladder,
        "bootstrap_full_vs_naive": boot_full_naive,
        "pi_coverage": coverage.to_dict(orient="records"),
        "lhs_forward_ic": ic.to_dict(orient="records"),
        "lhs_ic_overall": float(ic["mean_ic"].mean()) if not ic.empty else None,
        "obi_direction": obi_tab.to_dict(orient="records") if not obi_tab.empty else [],
        "alert_pr": pr.to_dict(orient="records") if not pr.empty else [],
        "fold_params": fold_params.to_dict(orient="records"),
        "lhs_sensitivity": lhs_sens.to_dict(orient="records"),
        "resilience": resilience_stats,
        "config_hash": settings.config_hash,
    }
    return summary
