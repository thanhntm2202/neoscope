# Ý TƯỞNG ĐỒ ÁN NEO API — CHINH PHỤC ĐỈNH THANG BLOOM & 100/100

> **Khuyến nghị chính: `NeoScope` — Kính hiển vi sổ lệnh & Buồng thử khớp lệnh.**
> Trả lời câu hỏi mà mọi bảng giá đều bỏ ngỏ: *"Nếu tôi bán 500 triệu đồng cổ phiếu X ngay lúc này, tôi sẽ khớp ở giá nào, mất bao nhiêu điểm cơ bản, và cuốn sổ lệnh có đủ 'hấp thụ' lệnh của tôi không?"*

Tài liệu này gồm: (1) giải mã yêu cầu "Bloom xuất sắc", (2) chiến lược ăn điểm theo rubric 100 điểm, (3) 4 ý tưởng ứng viên có so sánh, (4) thiết kế sâu ý tưởng được khuyến nghị — đủ chi tiết để bắt tay code ngay, (5) lịch trình và checklist khác biệt.

Cơ sở: đề thi cuối kỳ học phần *Gói phần mềm ứng dụng cho tài chính 1* (UEL, 261BFF401101/102) + tài liệu chính thức NEO API (overview, market-stream, stock-detail) đã đối chiếu tại thời điểm 17/11/2026.

---

## 1. Giải mã đề bài: "Bloom xuất sắc 10/10" thực sự nghĩa là gì?

Thang Bloom (bản sửa đổi của Anderson & Krathwohl) có **6 bậc**, không có bậc 10. "Xuất sắc 10/10" được hiểu đúng là: **sản phẩm chạm bậc cao nhất — Sáng tạo (Create) — và được nâng đỡ bởi bậc 5 — Đánh giá (Evaluate)**. Đây chính là điều đề bài viết ngay trong thông điệp cốt lõi: *"Không bắt đầu từ công nghệ. Hãy bắt đầu từ một vấn đề tài chính có thật… xây dựng sản phẩm có thể chạy, có logic tài chính và có bằng chứng kiểm chứng."*

Đối chiếu từng bậc Bloom với bằng chứng phải có trong đồ án:

| Bậc Bloom | Động từ đặc trưng | Bằng chứng trong đồ án | Nằm ở đâu trong rubric |
|---|---|---|---|
| 1. Nhớ | Liệt kê, gọi tên | Từ điển dữ liệu NEO API, glossary chỉ báo, README | TC2, TC7 |
| 2. Hiểu | Giải thích, diễn giải | Giải thích ý nghĩa kinh tế của từng trường/chỉ báo bằng lời của mình | TC3, TC7 |
| 3. Vận dụng | Tính toán, triển khai | Pipeline chạy thật: WS → chuẩn hóa → lưu → tính chỉ báo trên dữ liệu tự thu | TC2, TC4 |
| 4. Phân tích | So sánh, phân rã, truy nguyên | Phân rã thanh khoản thành các cấu phần; so sánh chéo mã/theo giờ trong phiên; truy nguyên vì sao cảnh báo kích hoạt | TC3 |
| 5. **Đánh giá** | Kiểm định, phản biện, bảo vệ | Kiểm chứng ngoài mẫu (walk-forward), đối chiếu benchmark, đối chiếu nguồn chéo, thử lỗi, nêu giới hạn trung thực | TC3, TC6 |
| 6. **Sáng tạo** | Thiết kế, kiến tạo | Thiết kế chỉ số tổng hợp mới + cơ chế ước tính chi phí thực thi + sản phẩm hoàn chỉnh giải quyết vấn đề thật | TC1, TC3, TC5 |

**Ba "bẫy trần điểm" của đề phải tránh bằng thiết kế, không phải bằng cố gắng:**

1. Không có sản phẩm chạy được → tối đa **60/100**. ⇒ Ưu tiên pipeline chạy được từ tuần 1, giao diện từ tuần 2.
2. NEO API không phải cốt lõi → tối đa **50/100**. ⇒ Mọi giá trị chính phải sinh ra từ dữ liệu NEO; nguồn ngoài chỉ để đối chiếu/bổ trợ.
3. Chỉ hiển thị dữ liệu → không đạt tối đa TC3 & TC5. ⇒ Mỗi màn hình phải trả lời một *câu hỏi quyết định*, không phải trưng bày số.

**Chiến lược phân bổ effort theo rubric:** TC2 (dữ liệu) + TC3 (phương pháp) + TC4 (kỹ thuật) = **60/100 điểm**. Ý tưởng tốt là ý tưởng tạo đất diễn cho 3 tiêu chí này — không phải ý tưởng có UI đẹp hay mô hình "nghe oai". Đề cũng nói thẳng: *"Việc sử dụng công nghệ phức tạp không tự động làm tăng điểm."*

---

## 2. "Mỏ vàng" NEO API — những gì tài liệu chính thức xác nhận

Đã đọc trực tiếp docs (17/11/2026). Các khả năng quan trọng cho việc chọn đề:

### 2.1. WebSocket `stock-stream/broker` — 4 channel

| Channel | listId | Trường đắt giá |
|---|---|---|
| `stockInfo` | Mã CK (VPB, HPG…) | **Sổ lệnh 3 mức** (bidPrice1–3/bidVol1–3, askPrice1–3/askVol1–3), trần/sàn/tham chiếu, OHLC, giá khớp gần nhất + KL khớp, tổng KL & GTGD lũy kế, **dòng tiền ngoại** (foreignBuy/SellVolume, Buy/SellValue, NetValue), **room ngoại** (foreignRemain/foreignRoom), totalBidQTTY/totalAskQTTY |
| `marketInfo` | VNINDEX, VN30, HNXINDEX… | Giá trị chỉ số, %đổi, tổng KL/GT, **số mã tăng/giảm/đứng, số mã trần/sàn** (độ rộng thị trường), trạng thái phiên |
| `marketVolume` | VNINDEX, VN30… | KL lũy kế + **KL khớp mới (delta)** — nhịp thanh khoản từng khoảnh khắc |
| `marketSession` | HOSE, HNX, UPCOM, FU | Trạng thái phiên PRE/ATO/LO/ATC/PLO/PT/C — bộ lọc ngữ cảnh bắt buộc |

### 2.2. REST `/stock/stockDetail` + các nhóm khác

Snapshot đầy đủ tương tự stockInfo, cộng thêm: `tradingStatus`, `events` (sự kiện quyền/cổ tức), `ptTotalTradedValue` (thỏa thuận — tách khỏi khớp lệnh!), trường chứng quyền (CW). Đủ để làm **đối chiếu chéo REST ↔ WS** — một điểm kiểm chứng ăn tiền.

### 2.3. Những "bẫy dữ liệu" có thật trong docs → cơ hội ghi điểm TC2

Đây là các tình huống **đã xác nhận trong payload mẫu chính thức**, không phải giả định:

- `bidPrice1` / `askPrice1` trả về **chuỗi** (`"29750.0"`), có thể chứa `"ATO"`/`"ATC"` → phải parse & gắn cờ, không ép số bừa.
- `totalBidQTTY: null` trong payload mẫu HPG → xử lý thiếu thật sự, không phải lý thuyết.
- `indexValue` là chuỗi; các trường KL/GT là **lũy kế trong phiên** → muốn có "nhịp" phải tự tính delta, xử lý reset qua phiên.
- Timestamp không kèm múi giờ → phải chuẩn hóa `Asia/Ho_Chi_Minh` nhất quán (yêu cầu cứng của đề).
- Giới hạn **5 request/giây/client**, JWT qua `/auth/token`, **gán quyền theo IP đăng ký**, không có UAT mặc định, lệnh qua API là **lệnh thật** → mọi mô phỏng phải tự xây, tuyệt đối không gọi endpoint đặt lệnh.

> Ai xử lý và **ghi nhật ký** được các bẫy này bằng cờ chất lượng (quality flags) sẽ nổi bật hẳn ở TC2 + TC6, vì phần lớn bài nộp sẽ bỏ qua.

**Điều kiện tiên quyết (làm ngay hôm nay):** tài khoản VPBankS đã đăng ký NEO API + IP máy chạy recorder đúng IP đã g quyền. Đây là rủi ro số 1 của mọi ý tưởng — không có quyền truy cập thì không có đồ án.

---

## 3. Bốn ý tưởng ứng viên

### Bảng so sánh nhanh

| Tiêu chí | **A. NeoScope** (khuyến nghị) | B. ForeignRadar | C. BasisWatch | D. PulseVN |
|---|---|---|---|---|
| Vấn đề | Chi phí thực thi & rủi ro thanh khoản ẩn sau bảng giá | Dòng tiền ngoại đổi hướng bất thường | Lệch giá phái sinh vs cơ sở | Trạng thái thị trường + giải thích có kiểm chứng |
| Đất diễn TC3 (20đ) | ★★★★★ vi cấu trúc + mô hình impact | ★★★★ thống kê lead-lag | ★★★★★ cost-of-carry | ★★★ độ rộng + regime |
| Đất diễn TC2 (20đ) | ★★★★★ tick dày, bẫy dữ liệu thật | ★★★★ | ★★★ | ★★★★ |
| Tự chủ dữ liệu 5–10 phiên | ★★★★★ tick WS dày đặc mỗi phiên | ★★★★ lũy kế theo phiên | ★★★ cần chuỗi đáo hạn | ★★★★ |
| Khác biệt so với số đông | ★★★★★ hiếm ai làm execution | ★★★ dễ trùng gợi ý #5 | ★★★★ | ★★ dễ trùng #1/#14 |
| Rủi ro kỹ thuật/dữ liệu | Trung bình (chỉ 3 mức giá — xử lý bằng giới hạn trung thực) | Thấp | **Cao** (quyền dữ liệu phái sinh, ít sự kiện đáo hạn trong kỳ) | Trung bình (LLM dễ nói sai) |
| Trần Bloom | **Create + Evaluate đầy đủ** | Create + Evaluate | Create + Evaluate | Create, Evaluate yếu nếu LLM chủ đạo |

### A. NeoScope — Kính hiển vi sổ lệnh & Buồng thử khớp lệnh ⭐ KHUYẾN NGHỊ

Ghép có chủ đích 3 gợi ý của đề (#3 bộ đo thanh khoản, #4 mất cân bằng sổ lệnh, #12 mô phỏng giao dịch) nhưng **xoay quanh một câu hỏi quyết định duy nhất** thay vì làm 3 tính năng rời: *"Lệnh của tôi sẽ 'ăn' bao nhiêu giá?"*. Chi tiết thiết kế ở Mục 4.

### B. ForeignRadar — Ra-đa dòng tiền ngoại & room

- **Vấn đề:** NĐT cá nhân thấy "khối ngoại bán ròng 500 tỷ" trên báo sau phiên, nhưng không biết mã nào bị bán **bất thường so với chính nó**, room sắp cạn ở đâu, và liệu áp lực ngoại có đang dẫn dắt giá trong phiên.
- **Logic tài chính:** delta foreignNetValue theo cửa sổ trượt → z-score theo mã × khung giờ; tỷ lệ sử dụng room `1 − foreignRemain/foreignRoom` và tốc độ thay đổi; kiểm định lead-lag (tương quan chéo có trễ, Granger nếu đủ dữ liệu) giữa áp lực ngoại và lợi nhuận — **báo cáo cả khi không có quan hệ**, tách train/test theo thời gian.
- **Dữ liệu NEO:** stockInfo (6 trường ngoại + room) + marketInfo. Đủ ≥10 phiên.
- **Kiểm chứng:** đối chiếu net lũy kế cuối phiên với bảng giá VPBankS/báo cáo thị trường; unit test delta & z-score; kiểm định placebo (đảo ngẫu nhiên chuỗi) để chứng minh pipeline không "nhìn thấy" quan hệ giả.
- **Điểm mạnh:** dễ thu dữ liệu, câu chuyện hấp dẫn. **Điểm yếu:** dễ trùng với nhiều bài khác; lead-lag trên 10 phiên dễ yếu ý nghĩa thống kê → phải trung thực.

### C. BasisWatch — Theo dõi hội tụ/phân kỳ phái sinh VN30

- **Vấn đề:** basis VN30F vs VN30 có lúc lệch xa giá trị lý thuyết; NĐT phái sinh cần biết khi nào lệch là "cơ hội" hay "bẫy thanh khoản".
- **Logic tài chính:** fair basis theo cost-of-carry `F* = S·e^{(r−q)T}` (r: lãi suất phi rủi ro tham chiếu, q: cổ tức kỳ vọng — nguồn ngoài phải trích rõ); chuẩn hóa basis theo năm; cảnh báo khi basis lệch > k·σ lịch sử; theo dõi hội tụ về đáo hạn.
- **Điểm mạnh:** công thức tài chính "sách giáo khoa" rất ăn điểm TC3. **Rủi ro:** phải xác nhận quyền truy cập dữ liệu phái sinh của NEO API cho tài khoản sinh viên; trong kỳ thu thập có thể không có ngày đáo hạn nào → khó chứng minh hội tụ; dữ liệu mỏng hơn hẳn cổ phiếu cơ sở. **Chỉ chọn nếu đã xác nhận quyền dữ liệu trước.**

### D. PulseVN — Nhịp thị trường + trợ lý giải thích "nói có sách"

- **Vấn đề:** NĐT cá nhân ngợp thông tin, cần một bản tóm tắt trạng thái thị trường *đáng tin*.
- **Logic tài chính:** engine độ rộng (advances/declines, trần/sàn, % mã trên MA nội ngày), nhịp thanh khoản (delta marketVolume so với profile giờ-trong-phiên), điểm "Market Pulse" tổng hợp; lớp giải thích **sinh từ quy tắc + số liệu đã lưu**, mỗi câu khẳng định đều gắn trích dẫn bản ghi dữ liệu (cơ chế fact-check tự động: câu nào không truy được về số liệu thì bị chặn). LLM chỉ là tùy chọn diễn đạt lại, không tạo số.
- **Điểm mạnh:** khác biệt ở cơ chế chống "ảo giác". **Điểm yếu:** chiều sâu TC3 mỏng hơn A/C; đề cảnh báo rõ về LLM → phải đầu tư cơ chế kiểm chứng câu chữ, effort cao mà điểm không chắc.

**Vì sao không chọn các hướng "an toàn" khác:** bảng điều khiển cá nhân (#9) và bộ lọc REST thuần (#2) rất dễ làm nhưng trần điểm thấp — đề ghi rõ sản phẩm chỉ hiển thị sẽ bị chặn điểm tối đa TC3/TC5; bộ công cụ wrapper (#13) mạnh TC4 nhưng yếu TC1/TC3 (thiếu lớp logic tài chính).

---

## 4. Thiết kế sâu NeoScope (ý tưởng khuyến nghị)

### 4.1. Vấn đề thật & người dùng

**Vấn đề:** Bảng giá Việt Nam hiển thị 3 mức giá mua/bán, nhưng không ai dịch nó thành **chi phí thực thi**. NĐT cá nhân đặt lệnh lớn so với thanh khoản hiển thị (đặc biệt midcap) bị trượt giá nặng; lệnh MP/ATO quét sổ lệnh mỏng gây thiệt hại vô hình. Không có công cụ bán lẻ nào trả lời: *"lệnh này có 'vừa' cuốn sổ không?"*.

**Người dùng mục tiêu:** (1) NĐT cá nhân giao dịch quy mô 100 triệu – 5 tỷ/lệnh; (2) môi giới cần cảnh báo khách về mã mỏng thanh khoản; (3) người học tài chính muốn *nhìn thấy* vi cấu trúc thị trường.

**Tuyên bố giá trị:** NeoScope biến sổ lệnh 3 mức + luồng khớp lệnh realtime thành (a) điểm sức khỏe thanh khoản, (b) ước tính chi phí thực thi trước khi đặt lệnh, (c) cảnh báo bất thường có cơ sở thống kê — và **tự kiểm chứng ước tính của mình** bằng buồng thử khớp lệnh mô phỏng. Không khuyến nghị mua/bán, không đặt lệnh thật.

### 4.2. Bốn câu hỏi sản phẩm (mỗi màn hình = một câu hỏi)

1. **"Mã này thanh khoản khỏe đến đâu, so với ai?"** → Liquidity Health Score (LHS) 0–100 + xếp hạng watchlist.
2. **"Tôi mua/bán X đồng ngay bây giờ thì giá khớp bình quân bao nhiêu?"** → Execution Estimator: đi dọc sổ lệnh + hiệu chỉnh impact + phí.
3. **"Thanh khoản vừa bất thường lúc nào, vì sao?"** → Alert engine với giải thích truy nguyên được về dữ liệu.
4. **"Ước tính của máy đáng tin đến đâu?"** → Buồng thử (paper simulator) + kết quả walk-forward công khai ngay trong UI.

Câu hỏi 4 chính là bậc **Evaluate** của Bloom được *sản phẩm hóa* — hiếm bài nộp nào dám đưa điểm yếu của mình lên giao diện. Đó là chữ ký của bài 10/10.

### 4.3. Kiến trúc

```
NEO API (VPBankS)
 ├─ WS stock-stream: stockInfo (30–60 mã), marketInfo (VNINDEX/VN30),
 │                   marketSession (HOSE), marketVolume
 └─ REST /stock/stockDetail: snapshot khởi tạo + đối chiếu chéo + tradingStatus/events
        │
        ▼
[1] collector/  ── client JWT, token-bucket 5 RPS, auto-reconnect + resubscribe,
        │          heartbeat, ghi RAW JSONL (bất biến, đánh số sequence)
        ▼
[2] data/       ── chuẩn hóa kiểu (parse "ATO"/chuỗi số), múi giờ UTC+7,
        │          khử lặp, tính delta từ bộ đếm lũy kế, quality flags → SQLite/Parquet
        ▼
[3] finance/    ── spread, depth, OBI, ILLIQ nội ngày, volatility, resilience…
        ▼
[4] analytics/  ── LHS (percentile tổng hợp), alert z-score theo giờ-trong-phiên,
        │          execution estimator (ladder + impact), hiệu chỉnh walk-forward
        ▼
[5] simulator/  ── khớp lệnh mô phỏng trên dữ liệu replay: hàng đợi giả định,
        │          phí + thuế, không bao giờ gọi API đặt lệnh
        ▼
[6] app/        ── Streamlit: Overview · Heatmap LHS · Drill-down mã ·
        │          "Thử lệnh" · Phòng kiểm chứng · nhật ký cảnh báo
        ▼
Người dùng (kèm disclaimer: công cụ phân tích học thuật, không phải khuyến nghị đầu tư)
```

Mỗi lớp là một package Python riêng, giao tiếp qua schema Pydantic → đúng yêu cầu tách lớp của đề (Mục 9), dễ unit test từng lớp.

### 4.4. Dữ liệu & lưu trữ (đất diễn TC2 — 20 điểm)

- **Phạm vi thu:** watchlist ~40 mã (VN30 + 10 midcap thanh khoản thấp để có tương phản) qua `stockInfo`; `marketInfo` VNINDEX/VN30; `marketSession` HOSE; `marketVolume`. ≥15 trường có ý nghĩa kinh tế — vượt xa mức tối thiểu 3.
- **Hai tầng lưu trữ:** `raw/` JSONL bất biến theo phiên (nguồn sự thật để replay) + `curated/` Parquet/SQLite theo schema chuẩn. Người chấm truy vết được mọi con số về thông điệp gốc → "tính tái lập" tuyệt đối.
- **Từ điển dữ liệu** (trích mẫu — làm đủ trong phụ lục báo cáo):

| Trường | Kiểu gốc NEO | Kiểu chuẩn | Đơn vị | Ý nghĩa kinh tế | Bẫy đã xử lý |
|---|---|---|---|---|---|
| bidPrice1 | string | float \| enum{ATO,ATC} | VND | Giá chào mua tốt nhất | Chuỗi "29750.0", ký tự ATO/ATC |
| bidVol1–3 | number | int | cổ phiếu | Độ sâu phía mua | Kiểm chứng đơn vị với bảng giá |
| totalTradingValue | number | int lũy kế → delta | VND | Dòng tiền khớp từng nhịp | Reset qua phiên, đến muộn |
| foreignNetValue | number | int lũy kế | VND | Áp lực ròng khối ngoại | Đối chiếu Buy−Sell |
| totalBidQTTY | number \| null | float + flag | cổ phiếu | Tổng cung/cầu hiển thị | null trong payload thật |
| indexTime / time | string | datetime UTC+7 | — | Nhịp thời gian | Không kèm tz, lệch đồng hồ |

- **Quality flags bắt buộc:** `PARSE_FAIL`, `NULL_FIELD`, `CROSSED_BOOK` (bid ≥ ask ngoài ATO/ATC), `STALE_TICK`, `DUPLICATE`, `OUT_OF_ORDER`, `COUNTER_RESET`, `OUTSIDE_SESSION`, `BEYOND_BAND` (ngoài trần/sàn). Mỗi bản ghi mang cờ; dashboard có tab "sức khỏe dữ liệu" đếm cờ theo phiên.
- **Kỷ luật API:** WS là chính (đúng khuyến nghị của đề); REST chỉ snapshot đầu phiên + đối chiếu định kỳ, qua token-bucket 5 RPS có log chứng minh tuân thủ.

### 4.5. Cụm công thức tài chính (đất diễn TC3 — 20 điểm)

Tất cả tính trên sổ lệnh 3 mức tại thời điểm t, mid `m = (ask1 + bid1)/2`:

| # | Chỉ báo | Công thức | Ý nghĩa & cơ sở |
|---|---|---|---|
| 1 | Spread tương đối | `s_bps = (ask1 − bid1)/m × 10⁴` | Chi phí tức thời của một lệnh nhỏ; chuẩn hóa để so sánh chéo mã (quoted spread — chỉ báo kinh điển của vi cấu trúc, Roll 1984; Chordia et al. 2000) |
| 2 | Độ sâu tiền phía mua/bán | `D_bid = Σᵢ bidPriceᵢ·bidVolᵢ` (i=1..3) | "Sức hấp thụ" hiển thị, đo bằng VND để so được chéo mã |
| 3 | Mất cân bằng sổ lệnh | `OBI = (ΣV_bid − ΣV_ask)/(ΣV_bid + ΣV_ask) ∈ [−1,1]` | Áp lực cung– cầu ngắn hạn; có sức dự báo hướng giá ngắn hạn trong tài liệu học thuật (Cont et al. 2014) |
| 4 | Độ dốc sổ lệnh | hồi quy giá theo KL tích lũy 3 mức | Sổ "dốc" = càng quét càng đắt; hình dạng quyết định slippage |
| 5 | Tập trung độ sâu | `HHI = Σ wᵢ²`, wᵢ = tỷ trọng KL mức i | Độ sâu dồn 1 mức dễ "bốc hơi" hơn trải đều |
| 6 | ILLIQ nội ngày (Amihud 2002, biến thể) | `mean(\|r_phút\| / (GTGD_phút/10⁹)) × 10⁴` → bps/tỷ đồng | Giá phải "trả" bao nhiêu bps cho mỗi tỷ đồng giao dịch — thước đo tác động giá |
| 7 | Biến động nội ngày | σ của lợi nhuận mid theo phút, cửa sổ trượt | Chuẩn hóa impact; phân biệt "mỏng vì yên" vs "mỏng vì loạn" |
| 8 | Khả năng phục hồi (resilience) | sau nhịp khớp lớn (delta KL > p95), thời gian để D_bid hồi về ≥80% mức trước nhịp | Thanh khoản động, không chỉ tĩnh — rất ít bài làm được |
| 9 | **Liquidity Health Score** | `LHS = 100 × Σ wₖ·percentile_rank(cₖ)`, cₖ ∈ {−spread, depth, −ILLIQ, −|OBI| dai dẳng, resilience}, w mặc định đều | Tổng hợp **mới do mình thiết kế** (bậc Create); dùng percentile nên không có "ngưỡng ma thuật"; báo cáo độ nhạy khi đổi w |
| 10 | **Ước tính thực thi** | Bán Q cổ: quét bid1→bid3 được VWAP_ladder; phần vượt sổ hiển thị ước lượng bằng impact `Y·σ·√(Q/ADV)` (luật căn bậc hai, Y hiệu chỉnh từ dữ liệu tự thu); `slippage_bps = (m − VWAP_est)/m × 10⁴`; kèm `coverage = D_visible/Q` và phí/thuế cấu hình được | Trái tim sản phẩm: dịch sổ lệnh thành chi phí; phần vượt sổ **luôn gắn cờ "ước lượng ngoài vùng quan sát"** |

**Cơ sở ngưỡng cảnh báo (đề cấm ngưỡng tùy ý):** mọi ngưỡng suy từ **phân vị thực nghiệm theo mã × khung giờ 15 phút** (thanh khoản nội ngày có hình chữ U — mở cửa/đóng cửa dày, giữa phiên mỏng; so sánh phải cùng khung giờ). Kích hoạt khi `|z| ≥ 3` **và** vượt p99 của bucket **và** duy trì ≥ N tick (chống nhiễu), có cooldown chống spam. Ngưỡng N, p99 được biện giải bằng thống kê trên chính dữ liệu thu + trích dẫn tài liệu, không bốc số.

### 4.6. Buồng thử & kế hoạch kiểm chứng (đất diễn TC6 — 10 điểm, và linh hồn của bậc Evaluate)

1. **Unit test tính tay:** sổ lệnh giả lập (công bố rõ là synthetic) với spread/OBI/slippage tính bằng tay → pytest so khớp từng công thức. Test cả ca biên: sổ trống một phía (trần/sàn), ATO/ATC, Q = 0, Q > toàn bộ sổ.
2. **Đối chiếu chéo:** trường chuẩn hóa từ WS ↔ snapshot REST `/stock/stockDetail` ↔ bảng giá VPBankS (ảnh chụp); tùy chọn đối chiếu nguồn thứ hai qua SSI FastConnect (đề cho phép, ghi rõ nguồn).
3. **Replay tái lập:** chạy lại toàn bộ phiên đã ghi từ raw JSONL → kết quả trùng khớp bit-for-bit. Người chấm tự chạy được bằng một lệnh `make replay SESSION=...`.
4. **Walk-forward chống nhìn trước:** hiệu chỉnh tham số impact Y trên các phiên 1..k → ước tính slippage cho các lệnh mô phỏng phiên k+1 → so với slippage "thực hiện" trong buồng thử khớp lệnh. **So với 2 benchmark ngây thơ:** (a) khớp tại mid không impact, (b) chỉ quét ladder không hiệu chỉnh. Báo cáo MAE (bps) ngoài mẫu theo mã + các ca thất bại. Nếu mô hình không thắng benchmark ở nhóm mã nào — **nói thẳng**, đó là điểm cộng chứ không phải điểm trừ.
5. **Thử lỗi có kịch bản:** ngắt mạng giữa phiên (kill WS), bơm thông điệp lặp/sai kiểu/đến muộn vào replay, mô phỏng token hết hạn, thị trường đóng cửa. Mỗi kịch bản có log + hành vi mong đợi + kết quả thật.
6. **Giới hạn trung thực (viết sẵn vào báo cáo §8):** chỉ thấy 3 mức giá (không full book, không hàng đợi, không thanh khoản ẩn); buồng thử giả định lệnh chủ động quét sổ, không mô phỏng ưu tiên hàng đợi thật; impact hiệu chỉnh trên ít phiên nên sai số lớn với lệnh rất lớn; ADV ước từ số phiên tự thu; không phải khuyến nghị đầu tư.

### 4.7. Giao diện Streamlit (TC5 — 10 điểm)

- **Header cố định:** tên sản phẩm + đối tượng + **trạng thái kết nối WS (xanh/vàng/đỏ) + thời điểm dữ liệu mới nhất (UTC+7) + trạng thái phiên** — đúng yêu cầu tối thiểu Mục 6 của đề.
- **Tab 1 Overview:** nhịp VNINDEX/VN30, độ rộng, "sức khỏe dữ liệu" (đếm quality flags).
- **Tab 2 Heatmap:** LHS theo watchlist, tô màu theo percentile; bộ lọc sàn/nhóm.
- **Tab 3 Drill-down mã:** sổ lệnh 3 mức dựng lại, time-series spread/depth/OBI, nhật ký cảnh báo — mỗi cảnh báo bấm vào thấy **vì sao** (giá trị, bucket, phân vị, z).
- **Tab 4 "Thử lệnh":** nhập mã + chiều + số tiền → VWAP ước tính, slippage bps, coverage %, phí, cảnh báo nếu vượt sổ hiển thị. So sánh 2 mã cạnh nhau: "500 triệu vào HPG vs vào mã midcap X".
- **Tab 5 Phòng kiểm chứng:** kết quả walk-forward, bảng benchmark, coverage dữ liệu các phiên, nút replay.
- Footer mọi trang: disclaimer học thuật.

### 4.8. Cấu trúc repo (bám đúng gợi ý Mục 9 của đề)

```
neoscope/
├── README.md            # cài đặt, cấu hình, chạy, giới hạn đã biết
├── pyproject.toml       # Python 3.11+, websockets, httpx, pydantic, pandas,
│                        # numpy, scipy, streamlit, plotly, pytest, loguru
├── .env.example         # NEO_USERNAME/…, NEO_TOKEN_URL, WS_URL, WATCHLIST — không chứa bí mật thật
├── src/
│   ├── neo_api/         # auth JWT, REST client + token bucket, WS client + reconnect
│   ├── data/            # schema Pydantic, chuẩn hóa, quality flags, raw JSONL + Parquet/SQLite
│   ├── finance/         # 10 công thức mục 4.5 — thuần hàm, không I/O → dễ test
│   ├── analytics/       # LHS, alert engine, impact calibration, walk-forward
│   ├── simulator/       # paper matching engine + phí/thuế (không import neo_api trading!)
│   └── app/             # Streamlit 5 tab
├── tests/               # pytest: công thức tính tay, parse bẫy, replay, chaos
├── data_sample/         # 1 phiên mẫu đã ẩn danh để người chấm replay ngay
├── docs/                # sơ đồ kiến trúc, từ điển dữ liệu, sổ tay ngưỡng
└── report/              # báo cáo 8–12 trang + phụ lục
```

Chi tiết bảo mật: bí mật qua `.env` (không commit), log không in token, `simulator/` bị cấm import module đặt lệnh ở mức code review — chứng minh bằng grep trong báo cáo rằng không tồn tại lời gọi place/amend/cancel.

### 4.9. Lịch trình 4 tuần (đường găng = dữ liệu!)

| Tuần | Việc | Sản phẩm kiểm tra được |
|---|---|---|
| **1** | Xác nhận quyền NEO API + IP; viết client WS/REST; **bắt đầu ghi raw mỗi phiên giao dịch ngay từ ngày 1–2** | Recorder chạy, raw JSONL đầu tiên |
| 2 | Chuẩn hóa + quality flags + finance/ + unit test; khung Streamlit | ≥5 phiên dữ liệu; dashboard xem được chỉ báo |
| 3 | LHS + alerts + estimator + simulator; thu tiếp phiên 6–10 | "Thử lệnh" chạy live; ≥8–10 phiên |
| 4 | Walk-forward + chaos test + hoàn thiện UI; báo cáo + video 5 phút | Bộ kiểm chứng đầy đủ, gói nộp hoàn chỉnh |

Lưu ý: hôm nay 17/11/2026 (thứ Ba) — mỗi ngày chần chừ là mất một phiên dữ liệu không lấy lại được. Khuyến nghị của đề là ≥5 phiên, ưu tiên ≥10; tick WS dày nên 10 phiên là đủ kiểm chứng thống kê trong phiên.

### 4.10. Kịch bản demo 5 phút (video/bảo vệ)

1. (30s) Vấn đề: "Bảng giá cho bạn 3 mức giá — nhưng không nói lệnh 500 triệu của bạn sẽ đắt hơn bao nhiêu."
2. (60s) Live: heatmap LHS, chọn 1 mã VN30 vs 1 midcap mỏng.
3. (90s) "Thử lệnh" 500 triệu trên cả hai mã → slippage & coverage khác nhau rõ rệt; bấm một cảnh báo để xem truy nguyên.
4. (60s) Phòng kiểm chứng: MAE walk-forward vs benchmark, một ca mô hình thua và lời giải thích.
5. (60s) Chaos: rút mạng → trạng thái đỏ, reconnect, dữ liệu không mất; kết thúc bằng slide giới hạn trung thực + disclaimer.

### 4.11. Khung báo cáo 8–12 trang

Bám đúng 10 mục của đề (Mục 12): Tóm tắt điều hành → Vấn đề & người dùng → Thiết kế (sơ đồ 4.3) → Dữ liệu NEO (từ điển 4.4) → Phương pháp (bảng 4.5 + biện giải ngưỡng) → Triển khai (5 tab) → Kiểm thử & kết quả (4.6) → Hạn chế & trách nhiệm → Hướng phát triển (full book nếu được cấp, thêm mã, hiệu chỉnh impact dài hạn, kiểm định OBI dự báo hướng giá) → Kết luận. Phụ lục: từ điển đầy đủ, công thức, bảng kết quả test, hướng dẫn chạy.

---

## 5. Checklist "khác biệt 10 điểm" — những thứ gần như không ai làm

- [ ] Raw JSONL bất biến + **replay tái lập được bằng 1 lệnh** (người chấm tự kiểm chứng, không cần tin lời bạn).
- [ ] Quality flags trên từng bản ghi + tab sức khỏe dữ liệu (biến bẫy ATO/null/lũy kế thành điểm).
- [ ] Ngưỡng cảnh báo theo **phân vị × giờ-trong-phiên**, có sổ tay biện giải từng ngưỡng.
- [ ] Walk-forward **so với benchmark ngây thơ** và công khai cả ca thua — chữ ký của bậc Evaluate.
- [ ] Tab "Phòng kiểm chứng" ngay trong UI sản phẩm.
- [ ] Đối chiếu chéo WS ↔ REST ↔ bảng giá (ảnh chụp) ↔ SSI (tùy chọn, ghi nguồn).
- [ ] Unit test các ca biên trần/sàn/ATO — nơi 90% code sinh viên vỡ.
- [ ] Token-bucket 5 RPS có log tuân thủ; `.env.example`; grep chứng minh không gọi API đặt lệnh.
- [ ] Disclaimer học thuật trên mọi màn hình + mục "những gì sản phẩm KHÔNG nên dùng để làm".
- [ ] Video demo có cả kịch bản lỗi, không chỉ đường thuận.

---

## 6. Bước tiếp theo đề xuất

1. **Hôm nay:** xác nhận tài khoản NEO API + IP được gán quyền (rủi ro lớn nhất, không phụ thuộc code).
2. Chọn ý tưởng (khuyến nghị A — NeoScope; phương án dự phòng B — ForeignRadar nếu muốn nhẹ hơn).
3. Dựng khung repo + recorder để **thu phiên đầu tiên ngay ngày mai**.
4. Viết đề cương báo cáo song song — báo cáo viết dần theo bằng chứng, không viết cuối.

*Tài liệu này là định hướng thiết kế học thuật. Mọi số liệu payload trích từ docs NEO API tại 17/11/2026; thông số có thể được VPBankS cập nhật — kiểm tra lại khi triển khai.*
