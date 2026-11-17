"""Hằng số vi cấu trúc thị trường HOSE và quy ước thời gian.

Nguồn quy tắc: Quy chế giao dịch chứng khoán tại Sở GDCK TP.HCM (HOSE),
mục bước giá / biên độ / lô giao dịch / phiên khớp lệnh. Kiểm tra lại tại
https://www.hsx.vn khi triển khai — thông số có thể được cập nhật.
"""
from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# --- Bước giá HOSE (tick size grid) ---
def tick_size(price: float) -> float:
    """Bước giá HOSE: <10.000đ: 10đ; 10.000–<50.000đ: 50đ; >=50.000đ: 100đ."""
    if price < 10_000:
        return 10.0
    if price < 50_000:
        return 50.0
    return 100.0


def round_to_tick(price: float, mode: str = "nearest") -> float:
    """Làm tròn giá về lưới bước giá hợp lệ."""
    t = tick_size(price)
    if mode == "down":
        return (price // t) * t
    if mode == "up":
        return -((-price) // t) * t
    return round(price / t) * t


# --- Biên độ dao động giá trong ngày (HOSE: ±7% so với tham chiếu) ---
PRICE_BAND_PCT = 0.07
LOT_SIZE = 100  # lô giao dịch khớp lệnh HOSE

# --- Phiên giao dịch HOSE (giờ Việt Nam) ---
SESSION_WINDOWS: dict[str, tuple[time, time]] = {
    "ATO": (time(9, 0), time(9, 15)),
    "LO_AM": (time(9, 15), time(11, 30)),
    "LUNCH": (time(11, 30), time(13, 0)),
    "LO_PM": (time(13, 0), time(14, 30)),
    "ATC": (time(14, 30), time(14, 45)),
    "PT": (time(14, 45), time(15, 0)),
}

# Mã trạng thái phiên NEO API (marketSession): PRE, ATO, LO, ATC, PLO, PT, C
CONTINUOUS_SESSIONS = {"LO"}

# Số nhịp 5s trong một phiên liên tục (135 phút sáng + 90 phút chiều = 225 phút)
LO_MINUTES = 135 + 90


def session_of_time(t: time) -> str:
    """Trả về mã phiên nội bộ tại một thời điểm trong ngày giao dịch."""
    for name, (start, end) in SESSION_WINDOWS.items():
        if start <= t < end:
            return name
    return "CLOSED"


def bucket_of_time(t: time, bucket_min: int = 15) -> int:
    """Bucket giờ-trong-phiên (phút từ 00:00 // bucket_min).

    Chuẩn hóa thống kê theo bucket để tôn trọng hình chữ U của thanh khoản
    nội ngày (mở cửa/đóng cửa dày, giữa phiên mỏng) — xem docs/thresholds.md.
    """
    return (t.hour * 60 + t.minute) // bucket_min
