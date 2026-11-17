"""Mô hình chi phí thực thi: quét sổ lệnh + kỳ vọng trôi giá + rủi ro thời điểm.

KHUNG LÝ THUYẾT (chi tiết trong docs/methodology.md):
Implementation Shortfall (Perold 1988) đo bằng bps so với mid lúc đến lệnh:
    IS = s·(VWAP_thực hiện − mid_đến)/mid_đến × 10^4,  s = +1 (mua), −1 (bán).

Lệnh Q cổ phiếu chia làm hai phần:
1) Phần khớp ngay trong sổ hiển thị 3 mức — chi phí TẤT ĐỊNH, tính bằng
   cách đi dọc thang giá (ladder walk).
2) Phần dư Q_res vượt sổ hiển thị — thực thi dần theo tham gia thị trường:
   mỗi nhịp hấp thụ tối đa ρ×KL khớp của nhịp (giả định participation,
   không mô phỏng hàng đợi). Thời gian hoàn thành kỳ vọng τ = Q_res/(ρ·v̂).

Kỳ vọng chi phí phần dư (giá trôi với tốc độ μ bps/s, nửa spread hs bps):
    E[IS_res] = hs + s·μ·τ/2          (VWAP của quá trình trôi đều trên [0, τ])
    E[IS_unf] = s·μ·H                 (phần chưa khớp sau H định giá theo mid)
    μ̂ = κ·OBI                         (κ hiệu chỉnh ngoài mẫu; Cont et al. 2014)

Rủi ro thời điểm (timing risk) — định luật căn bậc hai (Almgren et al. 2005;
Tóth et al. 2011): phương sai VWAP của khuếch tán trên [0, τ] là σ²τ/3, nên
    σ_IS ≈ Y·σ̂·sqrt(w_res²·τ/3 + w_unf²·H)
với Y hiệu chỉnh để khoảng dự báo 90% đạt độ phủ danh nghĩa ngoài mẫu.

Mọi tham số (κ, Y, v̂, σ̂) chỉ dùng thông tin ĐẾN THỜI ĐIỂM ĐẶT LỆNH và
các phiên HUẤN LUYỆN trước đó — không nhìn trước tương lai.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .microstructure import BPS


@dataclass
class LadderResult:
    filled_vis: float                 # KL khớp được trong sổ hiển thị
    qty_res: float                    # phần dư vượt sổ
    vwap_vis: float | None            # VWAP phần hiển thị
    cost_vis_bps: float | None        # chi phí phần hiển thị so với mid (bps)
    coverage: float                   # tỷ lệ sổ hiển thị đáp ứng lệnh
    fills: list[dict[str, float]] = field(default_factory=list)
    ok: bool = True


def ladder_walk(side: int, qty: float, prices: list[float | None],
                vols: list[float | None], mid: float | None) -> LadderResult:
    """Đi dọc thang giá 3 mức cho lệnh chủ động `side` (+1 mua quét ask, −1 bán quét bid).

    Trả về chi phí TẤT ĐỊNH của phần khớp trong sổ hiển thị. Mức thiếu (NaN)
    bị bỏ qua. Sổ trống → ok=False (không ước tính được).
    """
    if qty <= 0 or mid is None or not np.isfinite(mid) or mid <= 0:
        return LadderResult(0.0, qty, None, None, 0.0, [], ok=False)
    remaining = float(qty)
    notional = 0.0
    filled = 0.0
    fills = []
    for p, v in zip(prices, vols):
        if remaining <= 0:
            break
        if p is None or v is None or not np.isfinite(p) or not np.isfinite(v) or v <= 0:
            continue
        take = min(remaining, float(v))
        notional += take * float(p)
        filled += take
        remaining -= take
        fills.append({"price": float(p), "qty": take})
    if filled <= 0:
        return LadderResult(0.0, float(qty), None, None, 0.0, [], ok=False)
    vwap = notional / filled
    cost_bps = side * (vwap - mid) / mid * BPS  # mua: vwap>mid → dương; bán: vwap<mid → dương
    return LadderResult(filled, remaining, vwap, float(cost_bps), filled / qty, fills, ok=True)


@dataclass
class CostEstimate:
    e_is_bps: float
    sigma_is_bps: float
    lo_bps: float
    hi_bps: float
    tau_s: float
    w_vis: float
    w_res: float
    w_unf: float
    cost_vis_bps: float
    coverage: float
    flags: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def expected_is_bps(
    side: int,
    qty: float,
    ladder: LadderResult,
    hs_bps: float,
    obi_now: float,
    kappa_bps_per_s: float,
    v_rate_shares_per_s: float,
    sigma_bps_per_s: float,
    rho: float,
    horizon_s: float,
    y_risk: float,
    pi_z: float = 1.6449,
) -> CostEstimate:
    """Ước tính E[IS] và khoảng dự báo 90% — chỉ dùng thông tin tại thời điểm đặt.

    Xem derivation trong module docstring. Các ca suy biến được xử lý tường minh:
    - Sổ trống → flag NO_BOOK, không trả số.
    - Không có profile khối lượng (v̂=0) → kỳ vọng không khớp được phần dư.
    """
    flags: list[str] = []
    if not ladder.ok:
        return CostEstimate(np.nan, np.nan, np.nan, np.nan, np.nan,
                            0.0, 0.0, 1.0, np.nan, 0.0, ["NO_BOOK"])
    w_vis = ladder.filled_vis / qty
    q_res = ladder.qty_res
    mu = kappa_bps_per_s * (obi_now if np.isfinite(obi_now) else 0.0)  # bps/s

    if q_res <= 0:
        e = ladder.cost_vis_bps
        return CostEstimate(e, 0.0, e, e, 0.0, 1.0, 0.0, 0.0,
                            ladder.cost_vis_bps, 1.0, [],
                            {"mu_bps_per_s": mu, "hs_bps": hs_bps, "tau_eff": 0.0,
                             "v_rate": v_rate_shares_per_s,
                             "sigma_bps_per_s": sigma_bps_per_s if np.isfinite(sigma_bps_per_s) else 0.0})

    if not np.isfinite(v_rate_shares_per_s) or v_rate_shares_per_s <= 0 or rho <= 0:
        tau, w_res, w_unf = horizon_s, 0.0, 1.0
        flags.append("NO_LIQUIDITY_PROFILE")
    else:
        tau_full = q_res / (rho * v_rate_shares_per_s)
        if tau_full <= horizon_s:
            tau, w_res, w_unf = tau_full, q_res / qty, 0.0
        else:
            filled_res = rho * v_rate_shares_per_s * horizon_s
            tau = horizon_s
            w_res = filled_res / qty
            w_unf = q_res / qty - w_res
            flags.append("HORIZON_CAPPED")

    hs = hs_bps if np.isfinite(hs_bps) else 0.0
    e_res = hs + side * mu * tau / 2.0
    e_unf = side * mu * horizon_s
    e = w_vis * ladder.cost_vis_bps + w_res * e_res + w_unf * e_unf

    sig = sigma_bps_per_s if np.isfinite(sigma_bps_per_s) and sigma_bps_per_s > 0 else 0.0
    tau_eff = (w_res ** 2) * tau / 3.0 + (w_unf ** 2) * horizon_s
    sigma = y_risk * sig * math.sqrt(max(tau_eff, 0.0))
    if not np.isfinite(sigma):
        sigma = 0.0
        flags.append("NO_VOL_ESTIMATE")

    return CostEstimate(
        e_is_bps=float(e), sigma_is_bps=float(sigma),
        lo_bps=float(e - pi_z * sigma), hi_bps=float(e + pi_z * sigma),
        tau_s=float(tau), w_vis=w_vis, w_res=w_res, w_unf=w_unf,
        cost_vis_bps=ladder.cost_vis_bps, coverage=ladder.coverage,
        flags=flags,
        detail={"mu_bps_per_s": mu, "hs_bps": hs, "tau_eff": tau_eff,
                "v_rate": v_rate_shares_per_s, "sigma_bps_per_s": sig},
    )


def trading_costs_bps(notional_vnd: float, side: int, fee_rate: float,
                      sell_tax_rate: float) -> dict[str, float]:
    """Phí môi giới hai chiều + thuế bán (VN: 0.1% giá trị chuyển nhượng)."""
    fee_bps = fee_rate * BPS
    tax_bps = sell_tax_rate * BPS if side == -1 else 0.0
    return {"fee_bps": fee_bps, "tax_bps": tax_bps,
            "fee_vnd": notional_vnd * fee_rate,
            "tax_vnd": notional_vnd * sell_tax_rate if side == -1 else 0.0}
