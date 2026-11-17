"""Thanh khoản động: Amihud nội ngày, biến động thực hiện, khả năng phục hồi.

Cơ sở học thuật:
- ILLIQ: Amihud (2002) — |lợi nhuận| / giá trị giao dịch; ở đây dùng biến thể
  nội ngày theo phút, chuẩn hóa về bps trên mỗi tỷ đồng để so sánh chéo mã.
- Resilience (khả năng phục hồi độ sâu sau cú sốc khối lượng): khái niệm
  thanh khoản động trong O'Hara (1995); Foucault, Pagano & Röell (2013).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .microstructure import BPS


def amihud_bps_per_bn(ret_bps, value_vnd):
    """ILLIQ nội ngày = |ret_bps| / (GTGD / 1e9)  →  bps dịch giá trên mỗi tỷ đồng.

    NaN khi GTGD = 0 hoặc thiếu (không có giao dịch thì không đo được tác động).
    """
    r = np.asarray(ret_bps, dtype=float)
    v = np.asarray(value_vnd, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(v > 0, np.abs(r) / (v / 1e9), np.nan)


def realized_sigma_bps_per_s(ret_bps_series: pd.Series, window_bars: int = 15) -> pd.Series:
    """σ nội ngày từ lợi nhuận phút, quy đổi về bps/√giây theo khuếch tán.

    σ_phút = std(ret_bps, cửa sổ trượt);  σ_giây = σ_phút/√60.
    Giả định khuếch tán (variance tuyến tính theo thời gian) được công bố
    trong docs/methodology.md; sai lệch do tự tương quan vi cấu trúc là
    một hạn chế đã nêu.
    """
    sd = ret_bps_series.rolling(window_bars, min_periods=5).std()
    return sd / np.sqrt(60.0)


def resilience_episodes(
    snaps: pd.DataFrame,
    burst_quantile: float = 0.95,
    recovery_frac: float = 0.80,
    pre_window_s: float = 60.0,
    max_horizon_s: float = 300.0,
) -> pd.DataFrame:
    """Đo thời gian độ sâu phía mua phục hồi sau các nhịp khớp lớn (vectorized).

    Định nghĩa sự kiện: d_vol tại tick > phân vị `burst_quantile` của mã-phiên.
    Mức chuẩn: trung vị depth_bid trong `pre_window_s` trước sự kiện.
    Phục hồi: depth_bid >= `recovery_frac` × mức chuẩn, trong `max_horizon_s`.
    """
    df = snaps.dropna(subset=["d_vol", "depth_bid_vnd"]).sort_values("ts")
    cols = ["ts", "pre_depth", "recover_s", "unrecovered"]
    if len(df) < 50:
        return pd.DataFrame(columns=cols)
    ts = df["ts"].values.astype("datetime64[ns]")
    depth = df["depth_bid_vnd"].to_numpy(dtype=float)
    dvol = df["d_vol"].to_numpy(dtype=float)
    thr = np.quantile(dvol, burst_quantile)
    event_idx = np.where(dvol > thr)[0]
    pre_td = np.timedelta64(int(pre_window_s * 1e9), "ns")
    hor_td = np.timedelta64(int(max_horizon_s * 1e9), "ns")
    rows = []
    for i in event_idx:
        t0 = ts[i]
        lo = int(np.searchsorted(ts, t0 - pre_td, side="left"))
        if i - lo < 3:
            continue
        base = float(np.median(depth[lo:i]))
        if not np.isfinite(base) or base <= 0:
            continue
        post_hi = int(np.searchsorted(ts, t0 + hor_td, side="right"))
        post = depth[i + 1:post_hi]
        hits = np.where(post >= recovery_frac * base)[0]
        if len(hits):
            rec_s = float((ts[i + 1 + hits[0]] - t0) / np.timedelta64(1, "s"))
            rows.append({"ts": pd.Timestamp(t0), "pre_depth": base, "recover_s": rec_s, "unrecovered": False})
        else:
            rows.append({"ts": pd.Timestamp(t0), "pre_depth": base, "recover_s": np.nan, "unrecovered": True})
    return pd.DataFrame(rows, columns=cols)
