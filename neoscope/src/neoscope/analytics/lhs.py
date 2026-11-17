"""Liquidity Health Score (LHS) — chỉ số tổng hợp THIẾT KẾ MỚI của NeoScope.

LHS = 100 × Σ w_k · percentile_rank_chéo_mã(c_k)

Cấu phần (cửa sổ trượt 15 phút, đo trên bar 1 phút):
  tightness  = −spread_bps trung bình          (độ chặt — Roll 1984)
  depth      = log(1 + độ sâu tiền trung bình) (sức hấp thụ hiển thị)
  immediacy  = −ILLIQ 15'                      (tác động giá — Amihud 2002)
  stability  = −std(spread_bps) 15'            (ổn định chi phí tức thời)
  balance    = −|OBI| trung bình 15'           (cân bằng cung– cầu — Cont et al. 2014)

Vì sao percentile thay vì ngưỡng thô: (1) không có 'con số ma thuật';
(2) bền vững với outlier và khác biệt thang đo giữa các mã; (3) diễn giải
được: 'mã này chặt hơn 80% watchlist tại cùng thời điểm'. Kiểm tra độ nhạy:
nhân đôi lần lượt từng trọng số → tương quan thứ hạng Spearman với LHS gốc
(báo cáo trong tab Kiểm chứng). Giá trị xây dựng (construct validity) được
kiểm chứng bằng tương quan thứ hạng với ILLIQ tương lai — validation.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Settings

COMPONENTS = ["tightness", "depth", "immediacy", "stability", "balance"]


def compute_lhs(bars: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    win = int(settings.lhs.trailing_min)
    weights = {k: float(v) for k, v in settings.lhs.weights.as_dict().items()}
    out = bars.sort_values(["symbol", "session_date", "bar_ts"]).copy()
    g = out.groupby(["symbol", "session_date"], sort=False)

    spread_m = g["spread_bps"].transform(lambda s: s.rolling(win, min_periods=5).mean())
    spread_sd = g["spread_bps"].transform(lambda s: s.rolling(win, min_periods=5).std())
    depth_mid = (out["depth_bid_vnd"] + out["depth_ask_vnd"]) / 2.0
    depth_m = depth_mid.groupby([out["symbol"], out["session_date"]]).transform(
        lambda s: s.rolling(win, min_periods=5).mean())
    absret_sum = out["ret_bps"].abs().groupby([out["symbol"], out["session_date"]]).transform(
        lambda s: s.rolling(win, min_periods=5).sum())
    val_sum = out["d_val"].groupby([out["symbol"], out["session_date"]]).transform(
        lambda s: s.rolling(win, min_periods=5).sum())
    obi_m = out["obi_last"].abs().groupby([out["symbol"], out["session_date"]]).transform(
        lambda s: s.rolling(win, min_periods=5).mean())

    out["c_tightness"] = -spread_m
    out["c_depth"] = np.log1p(depth_m.clip(lower=0))
    with np.errstate(invalid="ignore", divide="ignore"):
        out["c_immediacy"] = -np.where(val_sum > 0, absret_sum / (val_sum / 1e9), np.nan)
    out["c_stability"] = -spread_sd
    out["c_balance"] = -obi_m

    # hạng percentile chéo mã tại từng thời điểm (chỉ trên mã đủ dữ liệu)
    valid = out[[f"c_{c}" for c in COMPONENTS]].notna().all(axis=1)
    ranks = pd.DataFrame(index=out.index, columns=[f"r_{c}" for c in COMPONENTS], dtype=float)
    for c in COMPONENTS:
        col = out[f"c_{c}"].where(valid)
        ranks[f"r_{c}"] = col.groupby(out["bar_ts"]).rank(pct=True)

    w = np.array([weights[c] for c in COMPONENTS])
    w = w / w.sum()
    rmat = ranks.to_numpy(dtype=float)
    out["lhs"] = 100.0 * np.nansum(rmat * w, axis=1)
    out.loc[ranks.isna().any(axis=1), "lhs"] = np.nan
    for c in COMPONENTS:
        out[f"r_{c}"] = ranks[f"r_{c}"]
    return out


def lhs_sensitivity(bars_lhs: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Độ nhạy: nhân đôi từng trọng số, đo Spearman thứ hạng chéo mã với LHS gốc."""
    weights = {k: float(v) for k, v in settings.lhs.weights.as_dict().items()}
    base = bars_lhs.dropna(subset=["lhs"])
    rows = []
    for perturbed in COMPONENTS:
        w = dict(weights)
        w[perturbed] *= 2.0
        wv = np.array([w[c] for c in COMPONENTS])
        wv = wv / wv.sum()
        rmat = base[[f"r_{c}" for c in COMPONENTS]].to_numpy(dtype=float)
        alt = 100.0 * np.nansum(rmat * wv, axis=1)
        tmp = base[["bar_ts", "lhs"]].copy()
        tmp["alt"] = alt
        cors = tmp.groupby("bar_ts").apply(
            lambda d: d["lhs"].corr(d["alt"], method="spearman") if len(d) >= 4 else np.nan,
            include_groups=False,
        )
        rows.append({"perturbed_weight": perturbed, "mean_spearman": float(cors.mean()),
                     "min_spearman": float(cors.min())})
    return pd.DataFrame(rows)
