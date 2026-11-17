"""Chỉ báo vi cấu trúc sổ lệnh — thuần hàm, không I/O, dễ kiểm thử tính tay.

Quy ước: mọi hàm nhận mảng numpy (hoặc scalar) và trả về cùng shape;
giá trị thiếu lan truyền thành NaN (không điền 0 im lặng).

Cơ sở học thuật:
- Quoted spread & relative spread: Roll (1984); Chordia, Roll & Subrahmanyam (2000).
- Order-book imbalance (OBI) và sức dự báo hướng giá ngắn hạn:
  Cont, Kukanov & Stoikov (2014); Gould & Bonart (2016).
- Micro-price: Stoikov (2018).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BPS = 1e4


def mid_price(bid1, ask1):
    """m = (bid1 + ask1)/2. NaN nếu thiếu một phía."""
    b, a = np.asarray(bid1, dtype=float), np.asarray(ask1, dtype=float)
    return (b + a) / 2.0


def spread_bps(bid1, ask1):
    """s = (ask1 − bid1)/m × 10^4 (bps). Chi phí tức thời của lệnh nhỏ."""
    b, a = np.asarray(bid1, dtype=float), np.asarray(ask1, dtype=float)
    m = (b + a) / 2.0
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(m > 0, (a - b) / m * BPS, np.nan)


def depth_vnd(p1, p2, p3, v1, v2, v3):
    """Độ sâu tiền một phía: D = Σ p_i·v_i (VND), bỏ qua mức thiếu (đã gắn cờ)."""
    ps = [np.asarray(p, dtype=float) for p in (p1, p2, p3)]
    vs = [np.asarray(v, dtype=float) for v in (v1, v2, v3)]
    total = np.zeros(np.broadcast(ps[0], vs[0]).shape, dtype=float)
    any_valid = np.zeros_like(total, dtype=bool)
    for p, v in zip(ps, vs):
        ok = np.isfinite(p) & np.isfinite(v)
        total = total + np.where(ok, p * v, 0.0)
        any_valid |= ok
    return np.where(any_valid, total, np.nan)


def obi(vb1, vb2, vb3, va1, va2, va3):
    """OBI = (ΣV_bid − ΣV_ask)/(ΣV_bid + ΣV_ask) ∈ [−1, 1].

    Áp lực cung– cầu hiển thị; Cont et al. (2014) chứng minh quan hệ với
    biến động giá ngắn hạn. NaN khi cả hai phía trống.
    """
    vb = sum(np.nan_to_num(np.asarray(v, dtype=float)) for v in (vb1, vb2, vb3))
    va = sum(np.nan_to_num(np.asarray(v, dtype=float)) for v in (va1, va2, va3))
    tot = vb + va
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, (vb - va) / tot, np.nan)


def microprice(bid1, ask1, vb1, va1):
    """Micro-price (Stoikov 2018): (bid1·V_ask1 + ask1·V_bid1)/(V_bid1 + V_ask1).

    Ước lượng giá tương lai tốt hơn mid khi sổ lệch: phía mỏng bị 'kéo' về phía dày.
    """
    b, a = np.asarray(bid1, dtype=float), np.asarray(ask1, dtype=float)
    vb, va = np.asarray(vb1, dtype=float), np.asarray(va1, dtype=float)
    tot = vb + va
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, (b * va + a * vb) / tot, np.nan)


def depth_hhi(v1, v2, v3):
    """HHI độ sâu = Σ w_i², w_i = v_i/Σv. 1/3 = trải đều; →1 = dồn một mức ('tường ảo' mong manh)."""
    vs = [np.nan_to_num(np.asarray(v, dtype=float)) for v in (v1, v2, v3)]
    tot = sum(vs)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, sum((v / tot) ** 2 for v in vs), np.nan)


def book_slope_bps_per_k(p1, p3, mid, v1, v2, v3):
    """Độ dốc sổ: |p3 − p1|/mid×10^4 chia cho tổng KL (nghìn cổ phiếu).

    Sổ 'dốc' = quét càng sâu càng đắt. NaN khi thiếu mức 3 hoặc tổng KL = 0.
    """
    p1, p3, m = (np.asarray(x, dtype=float) for x in (p1, p3, mid))
    tot = sum(np.nan_to_num(np.asarray(v, dtype=float)) for v in (v1, v2, v3))
    with np.errstate(invalid="ignore", divide="ignore"):
        run_bps = np.abs(p3 - p1) / m * BPS
        return np.where((tot > 0) & np.isfinite(run_bps), run_bps / (tot / 1000.0), np.nan)


def add_microstructure_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Tính toàn bộ chỉ báo sổ lệnh trên khung snapshot chuẩn hóa (vectorized).

    Tick bị cờ CROSSED_BOOK/NO_BOOK/ATO_ATC → chỉ báo sổ lệnh đặt NaN
    (không tính trên sổ không hợp lệ), nhưng giữ các trường giao dịch.
    """
    out = df.copy()
    bad = out["flags"].apply(
        lambda fl: any(f in fl for f in ("CROSSED_BOOK", "NO_BOOK", "ATO_ATC", "BEYOND_BAND"))
    )
    b1 = out["bid1"].mask(bad)
    a1 = out["ask1"].mask(bad)
    out["mid"] = mid_price(b1, a1)
    out["spread_bps"] = spread_bps(b1, a1)
    out["depth_bid_vnd"] = depth_vnd(
        out["bid1"].mask(bad), out["bid2"].mask(bad), out["bid3"].mask(bad),
        out["bidvol1"], out["bidvol2"], out["bidvol3"],
    )
    out["depth_ask_vnd"] = depth_vnd(
        out["ask1"].mask(bad), out["ask2"].mask(bad), out["ask3"].mask(bad),
        out["askvol1"], out["askvol2"], out["askvol3"],
    )
    out["obi"] = obi(
        out["bidvol1"].mask(bad), out["bidvol2"].mask(bad), out["bidvol3"].mask(bad),
        out["askvol1"].mask(bad), out["askvol2"].mask(bad), out["askvol3"].mask(bad),
    )
    out["microprice"] = microprice(b1, a1, out["bidvol1"], out["askvol1"])
    out["hhi_bid"] = depth_hhi(out["bidvol1"], out["bidvol2"], out["bidvol3"])
    out["hhi_ask"] = depth_hhi(out["askvol1"], out["askvol2"], out["askvol3"])
    out["slope_bid"] = book_slope_bps_per_k(
        out["bid1"].mask(bad), out["bid3"].mask(bad), out["mid"],
        out["bidvol1"], out["bidvol2"], out["bidvol3"],
    )
    out["slope_ask"] = book_slope_bps_per_k(
        out["ask1"].mask(bad), out["ask3"].mask(bad), out["mid"],
        out["askvol1"], out["askvol2"], out["askvol3"],
    )
    return out
