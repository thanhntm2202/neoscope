"""Alert engine — ngưỡng SUY TỪ THỐNG KÊ, không đặt tùy ý.

Cơ sở (docs/thresholds.md):
- Thanh khoản nội ngày hình chữ U → mọi chuẩn hóa theo bucket 15 phút
  giờ-trong-phiên, baseline từ CÁC PHIÊN TRƯỚC (expanding, không nhìn trước).
- Kích hoạt đồng thời ba điều kiện: |z| >= 3 VÀ vượt phân vị 99% thực nghiệm
  CỦA CHÍNH MÃ × BUCKET VÀ dai dẳng >= 3 tick liên tiếp; cooldown 60s chống spam.
  (z-score một mình không đủ vì phân phối thanh khoản đuôi dày — phân vị
  thực nghiệm là lớp bảo vệ phi tham số.)
- Mỗi cảnh báo mang EVIDENCE đầy đủ (giá trị, μ, σ, z, phân vị, n mẫu)
  → người dùng bấm vào thấy 'vì sao', đúng yêu cầu diễn giải có trách nhiệm.
- Phiên warmup đầu tiên chỉ tích lũy baseline, không cảnh báo (công bố).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Settings

# metric → (cột nguồn, chiều bất thường, biến đổi)
METRICS: dict[str, tuple[str, str, str]] = {
    "SPREAD_WIDEN": ("spread_bps", "high", "raw"),
    "DEPTH_EVAPORATION": ("depth_bid_vnd", "low", "raw"),
    "OBI_EXTREME": ("obi", "high", "abs"),
    "TRADE_BURST": ("d_vol", "high", "raw"),
    "FOREIGN_BURST": ("d_f_net_val", "high", "abs"),
}


def _metric_values(snaps: pd.DataFrame, alert_type: str) -> np.ndarray:
    col, _, transform = METRICS[alert_type]
    v = snaps[col].to_numpy(dtype=float)
    if transform == "abs":
        v = np.abs(v)
    return v


def build_baseline(train_snaps: pd.DataFrame, alert_type: str) -> dict:
    """Baseline theo symbol × bucket từ các phiên huấn luyện (trước phiên hiện tại)."""
    col, _, transform = METRICS[alert_type]
    df = train_snaps[["symbol", "bucket", col]].copy()
    if transform == "abs":
        df[col] = df[col].abs()
    df = df.dropna()
    out: dict = {}
    for (sym, bucket), g in df.groupby(["symbol", "bucket"]):
        vals = np.sort(g[col].to_numpy(dtype=float))
        if len(vals) < 30:  # quá ít mẫu → không cảnh báo bucket này (công bố)
            continue
        mu = float(vals.mean())
        sd = float(vals.std(ddof=1))
        spread_iqr = float(np.quantile(vals, 0.95) - np.quantile(vals, 0.05))
        sigma_eff = max(sd, 0.05 * spread_iqr, 1e-9)  # sàn σ chống bucket suy biến
        out[(sym, int(bucket))] = {"sorted": vals, "mu": mu, "sigma": sigma_eff, "n": len(vals)}
    return out


def run_alerts(settings: Settings, snaps_all: pd.DataFrame) -> pd.DataFrame:
    snaps_all = snaps_all.copy()
    if "d_f_net_val" not in snaps_all.columns:
        snaps_all["d_f_net_val"] = snaps_all["d_f_buy_val"] - snaps_all["d_f_sell_val"]
    cfg = settings.alerts
    z_thr = float(cfg.z_threshold)
    pct_thr = float(cfg.pct_threshold)
    persist_n = int(cfg.persistence_n)
    cooldown = pd.Timedelta(seconds=float(cfg.cooldown_s))
    warmup = int(cfg.warmup_sessions)
    types = list(cfg.types)

    dates = sorted(snaps_all["session_date"].unique())
    alerts: list[dict] = []
    for i, ds in enumerate(dates):
        if i < warmup:
            continue
        train = snaps_all[snaps_all["session_date"].isin(dates[:i])]
        today = snaps_all[snaps_all["session_date"] == ds]
        for atype in types:
            baseline = build_baseline(train, atype)
            if not baseline:
                continue
            _, direction, _ = METRICS[atype]
            for sym, g in today.groupby("symbol"):
                g = g.sort_values("ts")
                vals = _metric_values(g, atype)
                buckets = g["bucket"].to_numpy()
                ts_arr = g["ts"].to_numpy()
                trig = np.zeros(len(g), dtype=bool)
                z_arr = np.full(len(g), np.nan)
                pct_arr = np.full(len(g), np.nan)
                mu_arr = np.full(len(g), np.nan)
                sd_arr = np.full(len(g), np.nan)
                n_arr = np.zeros(len(g), dtype=int)
                for j in range(len(g)):
                    b = baseline.get((sym, int(buckets[j])))
                    if b is None or not np.isfinite(vals[j]):
                        continue
                    z = (vals[j] - b["mu"]) / b["sigma"]
                    pct = float(np.searchsorted(b["sorted"], vals[j], side="right")) / b["n"]
                    ok = (z >= z_thr and pct >= pct_thr) if direction == "high" else \
                         (z <= -z_thr and pct <= 1.0 - pct_thr)
                    trig[j] = ok
                    z_arr[j], pct_arr[j] = z, pct
                    mu_arr[j], sd_arr[j], n_arr[j] = b["mu"], b["sigma"], b["n"]
                # dai dẳng + cooldown
                streak = 0
                last_fire: pd.Timestamp | None = None
                for j in range(len(g)):
                    if not trig[j]:
                        streak = 0
                        continue
                    streak += 1
                    if streak < persist_n:
                        continue
                    ts_j = pd.Timestamp(ts_arr[j])
                    if last_fire is not None and ts_j - last_fire < cooldown:
                        continue
                    last_fire = ts_j
                    streak = 0
                    raw_v = g.iloc[j]
                    alerts.append({
                        "session_date": ds, "symbol": sym,
                        "group": settings.group_of(sym),
                        "ts": ts_j, "type": atype, "direction": direction,
                        "value": float(vals[j]),
                        "signed_value": float(raw_v[METRICS[atype][0]]) if pd.notna(raw_v[METRICS[atype][0]]) else np.nan,
                        "mu": mu_arr[j], "sigma": sd_arr[j], "z": z_arr[j],
                        "pct": pct_arr[j], "bucket": int(buckets[j]), "n_train": int(n_arr[j]),
                    })
    return pd.DataFrame(alerts)
