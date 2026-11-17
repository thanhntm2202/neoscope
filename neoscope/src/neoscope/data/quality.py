"""Cờ chất lượng dữ liệu (quality flags).

Mỗi bản ghi chuẩn hóa mang theo danh sách cờ; dashboard có tab đếm cờ theo
phiên. Các cờ tương ứng với những tình huống ĐÃ XÁC NHẬN trong payload mẫu
chính thức của NEO API (bidPrice1 dạng chuỗi/ATO, totalBidQTTY null, bộ đếm
lũy kế...) — xem docs/data_dictionary.md.
"""
from __future__ import annotations

from enum import StrEnum


class QF(StrEnum):
    NULL_FIELD = "NULL_FIELD"            # trường quan trọng bị thiếu/null
    PARSE_FAIL = "PARSE_FAIL"            # không ép được kiểu số
    ATO_ATC = "ATO_ATC"                  # giá mức 1 là ký tự ATO/ATC (hợp lệ theo phiên)
    DUPLICATE = "DUPLICATE"              # thông điệp lặp (bị loại khỏi curated)
    OUT_OF_ORDER = "OUT_OF_ORDER"        # arrival_ts lùi so với bản ghi trước cùng mã
    LATE_ARRIVAL = "LATE_ARRIVAL"        # (synth) bản ghi đến muộn có chủ đích
    STALE_GAP = "STALE_GAP"              # khoảng trống > ngưỡng trong phiên liên tục
    COUNTER_RESET = "COUNTER_RESET"      # bộ đếm lũy kế giảm (reset/phiên mới/lỗi)
    CROSSED_BOOK = "CROSSED_BOOK"        # bid1 >= ask1 ngoài ATO/ATC
    BEYOND_BAND = "BEYOND_BAND"          # giá ngoài biên độ trần/sàn
    MISSING_LEVEL = "MISSING_LEVEL"      # thiếu một mức giá/KL trong sổ 3 mức
    NO_BOOK = "NO_BOOK"                  # không dựng được mid (thiếu cả hai phía)


FLAG_DESCRIPTIONS: dict[str, str] = {
    QF.NULL_FIELD: "Trường quan trọng null — giữ NaN, không điền bừa",
    QF.PARSE_FAIL: "Ép kiểu thất bại — giữ NaN và ghi giá trị gốc vào log",
    QF.ATO_ATC: "Giá mức 1 là 'ATO'/'ATC' — hợp lệ trong phiên định kỳ, loại khỏi tính toán sổ lệnh",
    QF.DUPLICATE: "Payload trùng hash trong cửa sổ khử lặp — loại bản ghi",
    QF.OUT_OF_ORDER: "Thông điệp đến không đúng thứ tự — giữ, sắp xếp lại theo (ts, seq)",
    QF.LATE_ARRIVAL: "Thông điệp đến muộn (mô phỏng có chủ đích để thử pipeline)",
    QF.STALE_GAP: "Không có cập nhật quá ngưỡng trong phiên LO — đánh dấu khoảng trống",
    QF.COUNTER_RESET: "Bộ đếm lũy kế giảm — delta đặt NaN, không tính nhịp âm",
    QF.CROSSED_BOOK: "Sổ lệnh bắt chéo ngoài phiên định kỳ — loại chỉ báo sổ lệnh tại tick",
    QF.BEYOND_BAND: "Giá ngoài [sàn, trần] — giữ bản ghi, loại giá trị phạm lệ",
    QF.MISSING_LEVEL: "Thiếu mức 2/3 — tính độ sâu trên các mức còn lại, ghi cờ",
    QF.NO_BOOK: "Không có mid hợp lệ — tick không dùng cho ước tính thực thi",
}
