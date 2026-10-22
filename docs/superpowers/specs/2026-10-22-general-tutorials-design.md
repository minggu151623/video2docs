# Thiết kế: tutorial mọi lĩnh vực có kiểm chứng độc lập

Ngày: 22/10/2026. Trạng thái: thiết kế đã duyệt từng phần trong hội thoại, chờ duyệt bản viết.

## 1. Mục tiêu và bối cảnh

Video2docs hiện chỉ nhắm tới tutorial phần mềm (IDE, terminal, web, desktop). Người dùng muốn đưa sản phẩm ra mắt thật cho người khác dùng, với video hướng dẫn thuộc bất kỳ lĩnh vực nào.

Các quyết định đã chốt:

| Câu hỏi | Quyết định |
| --- | --- |
| Đối tượng | Sản phẩm thật, người lạ tự upload video |
| Phạm vi nội dung | Mọi video how-to có các bước làm theo, mọi lĩnh vực. Video không phải tutorial bị báo rõ, không bịa bước. Tài liệu dạng ghi chú cho bài giảng để mở rộng sau |
| Tiêu chí thành công | Người đọc làm theo được mà không cần xem video: đủ định lượng, thông số, cảnh báo, ảnh từng bước |
| Hướng kiến trúc | Một schema chung, model trả thêm nhãn lĩnh vực và `is_tutorial` trong cùng lần gọi; renderer đổi tên mục theo lĩnh vực |
| Chống bịa | Trích nguyên văn, kiểm chứng độc lập bằng ASR/OCR trên server, hiển thị trạng thái kiểm chứng. Không thêm lượt LLM kiểm tra |

Sản phẩm thật được tách thành bốn dự án con, mỗi dự án có spec và kế hoạch riêng:

1. **Hiểu tutorial mọi lĩnh vực** (spec này).
2. Nền tảng nhiều người dùng: đăng nhập, tách dữ liệu, hàng đợi job, lưu trữ cloud.
3. Kiểm soát chi phí và lạm dụng: quota, thanh toán, chặn video vi phạm.
4. Pháp lý và vận hành: điều khoản, chính sách dữ liệu, deploy, giám sát, backup.

Spec này vẫn chạy trên kiến trúc hiện tại: một người dùng, localhost, SQLite, worker một tiến trình, Gemini.

### Ngoài phạm vi

- Tài liệu dạng ghi chú/đề cương cho video giảng giải (`document_kind: explainer`). Thiết kế chừa chỗ, chưa triển khai.
- Lượt LLM thứ hai để kiểm chứng.
- Đưa bản ghi lời nói vào prompt Gemini.
- Mọi việc của dự án con 2–4, kể cả GPU và scale ASR.

## 2. Mô hình dữ liệu (schema v2)

`TutorialDraftV2` thay cho `TutorialDraftV1` với các job mới. Pydantic vẫn là schema chuẩn; schema gửi provider tiếp tục được sinh gọn từ Pydantic và dùng timestamp `MM:SS` như contract v8.

### 2.1. Cấp tài liệu

| Trường | Kiểu | Ghi chú |
| --- | --- | --- |
| `schema_version` | `"2.0"` | |
| `is_tutorial` | bool | `false` thì `steps` rỗng |
| `not_tutorial_reason` | chuỗi hoặc null | Bắt buộc khi `is_tutorial = false` |
| `domain` | enum | `software`, `cooking`, `repair`, `craft`, `fitness`, `beauty`, `gardening`, `music`, `other` |
| `yield` | chuỗi hoặc null | Khẩu phần hoặc sản lượng nếu video nêu ("4 người ăn") |
| `title`, `summary`, `language`, `objectives` | như v1 | |
| `prerequisites`, `troubleshooting` | claim | Như v1, thêm trường nguyên văn (mục 2.3) |
| `safety` | claim | Mới: cảnh báo áp dụng cho cả tutorial |
| `materials` | danh sách | Mới: `name`, `quantity` (chuỗi), `unit`, `note`, bằng chứng, `basis`, nguyên văn |
| `equipment` | danh sách | Thay `tools`: `name`, `spec` (phiên bản, model, kích cỡ), bằng chứng |
| `steps` | danh sách | Mục 2.2 |
| `uncertainties` | như v1 | |

`quantity` là chuỗi để giữ được "1/2", "một nhúm". Lĩnh vực ngoài danh sách dùng `other`, pipeline vẫn chạy bình thường.

### 2.2. Mỗi bước

Giữ các trường v1: `local_id`, `title`, `start`/`end`, `actions`, `expected_result`, `evidence_spans`, `screenshot_times`, `needs_review`, `review_reason`. Thêm hoặc đổi:

| Trường | Ghi chú |
| --- | --- |
| `parameters` | `name`, `value`, `unit`, bằng chứng, `basis`, nguyên văn. Ví dụ nhiệt độ 180 °C, 15 phút, 25 Nm, 3 hiệp × 12 lần |
| `exact_inputs` | Thay `commands`: `kind` (`code`, `command`, `text`), `language`, `text`, `completeness`, bằng chứng, nguyên văn |
| `warnings` | Claim gắn với bước |
| `tips` | Claim gắn với bước |

Giới hạn đề xuất: `materials` ≤ 60, `equipment` ≤ 30, `parameters` ≤ 10/bước, `warnings` ≤ 5/bước, `tips` ≤ 5/bước. Các giới hạn v1 khác giữ nguyên.

### 2.3. Nguyên văn và chống bịa

Áp dụng cho `materials`, `parameters`, `exact_inputs`, `warnings`, `tips`, `safety`, `prerequisites`, `troubleshooting`:

- `basis = stated`: bắt buộc `quote`, câu người nói đúng như nghe, giữ ngôn ngữ gốc của video. Phần diễn giải theo ngôn ngữ đầu ra.
- `basis = observed` với chữ hoặc số trên màn hình: bắt buộc `on_screen_text`, chép nguyên văn.
- `basis = observed` chỉ là hành động: `quote` và `on_screen_text` là null.
- `basis = inferred` hoặc `unclear`: giữ trong JSON, chỉ hiển thị ở "Điểm chưa rõ".
- Thiếu nguyên văn theo quy tắc trên là lỗi validation và đi vào luồng repair hiện có (tối đa một repair/job).
- `exact_inputs` có `basis` như các mục khác. Với `observed`, `on_screen_text` là bản chép lệnh/code trên màn hình.

### 2.4. Kết quả kiểm chứng

App ghi, model không điền. Lưu tách khỏi draft của model, gắn theo đường dẫn tới mục (ví dụ `steps/3/parameters/0`):

| Trường | Giá trị |
| --- | --- |
| `status` | `verified`: ASR/OCR khớp quanh mốc bằng chứng. `unverified`: đã kiểm tra nhưng không khớp. `not_checkable`: hành động không có lời nói hay chữ để đối chiếu. `not_checked`: bộ kiểm chứng lỗi hoặc không chạy |
| `method` | `asr`, `ocr`, `none` |
| `matched_text` | Đoạn khớp được, hoặc null |
| `checked_range` | Khoảng thời gian đã đối chiếu |
| `reason` | Lý do khi không phải `verified` |

Có `unverified` hoặc `not_checked` thì generation mang `needs_review`. Bước kiểm chứng chạy lại được mà không gọi Gemini.

### 2.5. Tương thích

- Generation v1 đã lưu được nâng cấp khi đọc: `commands` → `exact_inputs` (`kind = command`), `tools` → `equipment` (`version` → `spec`), `domain = software`, `is_tutorial = true`, các trường mới rỗng. Không có `verification`, renderer hiển thị như trước.
- Contract hash đổi nên checkpoint v1 không được tái dùng.
- Revision Markdown đã lưu không bị render lại.

## 3. Pipeline kiểm chứng

### 3.1. Luồng xử lý

1. Kiểm tra media (như hiện tại).
2. **ASR** trên toàn bộ âm thanh, chạy local. Bản ghi lời nói có timestamp từng từ, cache theo hash video và cấu hình ASR; các generation sau dùng lại. Video không có track âm thanh thì bỏ qua và ghi nhận.
3. Phân tích Gemini theo đoạn (mục 4.2 về chặn sớm).
4. Ghép đoạn, chọn frame ảnh như hiện tại.
5. **OCR có chọn lọc:** chỉ cho mục có `on_screen_text`. Trích tối đa 3 frame trong khoảng bằng chứng (đầu, giữa, cuối), không OCR toàn video.
6. **Khớp** (mục 3.3), ghi `verification`.
7. Render Markdown.

Phase mới của job: `transcribing` (bước 2) và `verifying` (bước 5–6), hiển thị như các phase hiện có.

### 3.2. Công cụ

- ASR và OCR mỗi cái nằm sau một adapter, giống provider AI hiện tại, có bản giả cho test.
- ASR mặc định: faster-whisper. CPU được, GPU nhanh hơn. Tự nhận diện ngôn ngữ. Cỡ model chỉnh bằng cấu hình.
- OCR: chọn qua spike trước khi triển khai, so Tesseract với PaddleOCR trên khoảng 20 frame mẫu: chữ terminal/IDE, chữ chèn trên video nấu ăn, nhãn bao bì, tiếng Việt có dấu, ít nhất một ngôn ngữ châu Á. Tiêu chí: độ chính xác ký tự trên mẫu, thời gian/frame trên CPU, kích thước cài đặt. Kết quả ghi vào `docs/decisions.md`.
- Toàn bộ ASR/OCR chạy trên server, không gửi dữ liệu ra ngoài. `PROJECT_SPEC.md` được sửa vì hiện ghi "không có OCR/Whisper riêng".

### 3.3. Thuật toán khớp

Hai tầng, đều là thuật toán, không gọi LLM.

1. **Nhất quán nội bộ:** giá trị của mục phải nằm trong nguyên văn model trích. Ví dụ `quantity = "200"` thì `quote` hoặc `on_screen_text` phải chứa 200. Không thỏa thì `unverified` với lý do "giá trị không có trong nguyên văn".
2. **Đối chiếu nguồn:**
   - `quote` so với bản ghi lời nói trong khoảng bằng chứng ± 5 giây.
   - `on_screen_text` so với kết quả OCR của các frame đã trích.
   - Chuẩn hóa: Unicode NFKC, bỏ khác biệt hoa/thường và khoảng trắng; giữ dấu tiếng Việt.
   - Con số phải khớp chính xác. Phần chữ khớp gần đúng theo ngưỡng cấu hình (khởi điểm 85/100, chỉnh theo bộ đánh giá).
   - `exact_inputs` dùng ngưỡng cao (khởi điểm 95/100), chỉ bỏ qua khác biệt khoảng trắng.
   - Số đọc bằng chữ: chuẩn hóa sang chữ số cho tiếng Việt và tiếng Anh. Ngôn ngữ khác không khớp thì rơi về `unverified` (báo nhầm theo hướng an toàn).
3. Mục `observed` chỉ có hành động: `not_checkable`, `method = none`.

### 3.4. Lỗi

- ASR/OCR lỗi, timeout hoặc thiếu dependency: tài liệu vẫn được tạo, mục liên quan `not_checked` kèm lý do, generation `needs_review`, job có warning. Không chặn việc tạo tài liệu.
- Video chỉ có nhạc: mục `stated` không qua được kiểm chứng (quy tắc hiện có vốn đòi bằng chứng audio cho `stated`).
- Timeout riêng cho ASR và OCR, nằm trong `JOB_TIMEOUT_SECONDS`.

## 4. Prompt, render và giao diện

### 4.1. Prompt

- Đổi "video hướng dẫn phần mềm" thành "video hướng dẫn thực hành (how-to)". Giữ quy tắc chống bịa, `MM:SS`, scope theo đoạn, ngữ cảnh đoạn trước không đáng tin.
- Khối gợi ý theo lĩnh vực, chỉ nói cần để ý gì, không cho phép suy đoán: nấu ăn (khẩu phần, mức lửa, thời gian, dấu hiệu chín), sửa chữa (tên và kích cỡ linh kiện, lực siết, ngắt điện), thể thao (hiệp, lần, nghỉ, tư thế), làm đẹp (lượng sản phẩm), phần mềm (lệnh chính xác, phiên bản).
- Quy tắc nguyên văn của mục 2.3.
- Che dữ liệu nhạy cảm mở rộng: secret, mật khẩu, địa chỉ, số điện thoại, giấy tờ tùy thân.
- Từ đoạn 2, `domain` của đoạn 1 được truyền trong metadata làm ngữ cảnh.

### 4.2. Chặn video không phải tutorial

- Đoạn 1 trả `is_tutorial = false`: job dừng với trạng thái mới `not_tutorial`, lưu lý do, không phân tích đoạn sau, không tạo tài liệu.
- Màn hình hiển thị lý do và nút **"Vẫn phân tích toàn bộ"**. Nút tạo job mới với cờ bỏ qua chặn, yêu cầu xác nhận chi phí như retry.
- Đoạn sau trả `is_tutorial = false` trong job đã qua chặn: chỉ ghi nhận, không dừng.

### 4.3. Render Markdown/PDF

Tên mục theo lĩnh vực:

| Lĩnh vực | `materials` | `equipment` |
| --- | --- | --- |
| cooking | Nguyên liệu | Dụng cụ |
| repair, craft, gardening | Vật liệu | Dụng cụ |
| beauty | Sản phẩm | Dụng cụ |
| fitness | Vật liệu | Thiết bị |
| software | Tài nguyên | Phần mềm cần có |
| music, other | Vật liệu | Dụng cụ |

Có bản tiếng Anh tương ứng. Mục rỗng không hiển thị, trừ các mục v1 vốn hiển thị "Không được nêu trong video".

Thứ tự: tiêu đề, tóm tắt, `yield`, mục tiêu, chuẩn bị, **An toàn**, vật liệu, dụng cụ, ngữ cảnh theo đoạn, các bước, lỗi và cách xử lý, điểm chưa rõ, thông tin nguồn.

Trong mỗi bước: thao tác, thông số ("Nhiệt độ: 180 °C"), `exact_inputs` (khối code như hiện tại), cảnh báo, mẹo, kết quả, bằng chứng, ảnh.

Huy hiệu kiểm chứng bằng chữ (font DejaVu hỗ trợ ✓):

| Trạng thái | Hiển thị |
| --- | --- |
| `verified` ASR | ✓ khớp lời nói [mốc] |
| `verified` OCR | ✓ khớp chữ trên màn hình [mốc] |
| `unverified`, `not_checked` | ? chưa kiểm chứng |
| `not_checkable` | không có văn bản để đối chiếu |

Mục `unverified`/`not_checked` vẫn nằm đúng chỗ trong bước và được liệt kê thêm ở "Điểm chưa rõ". Mục `inferred`/`unclear` chỉ ở "Điểm chưa rõ".

### 4.4. Giao diện

- Câu chữ upload: "Video hướng dẫn: nấu ăn, sửa chữa, phần mềm…". Bỏ "command" trong lời nhắc kiểm tra.
- Màn hình kết quả: nhãn lĩnh vực, tóm tắt "N/M mục đã kiểm chứng", bộ lọc "chỉ hiện mục chưa kiểm chứng", huy hiệu trong danh sách bước.
- Màn hình `not_tutorial` như mục 4.2.
- Kiểu TypeScript sinh lại từ Pydantic (`scripts/generate_schema.py`, `npm --prefix frontend run types`).

## 5. Kiểm thử và đánh giá

### 5.1. Test tự động

- Unit: validation nguyên văn theo `basis`; nâng cấp v1 → v2; bộ khớp (con số chính xác, chữ gần đúng, chuẩn hóa tiếng Việt, số đọc bằng chữ vi/en, nhất quán nội bộ); tên mục theo lĩnh vực; huy hiệu.
- Integration với ASR/OCR/provider giả: luồng đủ phase; chặn `not_tutorial` ở đoạn 1 chỉ tốn một request; nút bỏ qua chặn; ASR lỗi vẫn tạo tài liệu `needs_review`; chạy lại kiểm chứng không gọi provider.
- Probe chỉ có text với Gemini thật để xác nhận Google chấp nhận schema v2, trước lượt gửi video đầu tiên. Probe có thể phát sinh phí nhỏ, cần người dùng đồng ý.

### 5.2. Bộ đánh giá

Khoảng 8 video không nhạy cảm: phần mềm, nấu ăn, sửa chữa, thủ công, thể thao, làm đẹp, và 2 video không phải tutorial (vlog, review). Mỗi video có đáp án ghi tay: các bước, định lượng, thông số, cảnh báo, kèm mốc thời gian.

Ngưỡng khởi điểm (người dùng có thể chỉnh):

- ≥ 95% mục mang `verified` đúng với đáp án.
- 2/2 video không phải tutorial bị chặn ở đoạn 1.
- Không có định lượng hoặc thông số sai nào mang `verified`.
- Báo cáo thêm, chưa đặt ngưỡng: tỉ lệ mục đúng bị `unverified`, độ phủ bước, thời gian ASR/OCR, chi phí Gemini mỗi video.

Gửi video bộ đánh giá lên Google cần người dùng đồng ý và chấp nhận phí.

## 6. Thứ tự triển khai đề xuất

1. Spike OCR (mục 3.2), ghi quyết định.
2. Schema v2, nâng cấp v1, sinh lại schema provider, probe schema với Gemini.
3. Prompt v2 và chặn `not_tutorial`.
4. Adapter ASR/OCR, bộ khớp, `verification`.
5. Renderer và giao diện.
6. Cập nhật `PROJECT_SPEC.md`, README, `docs/decisions.md`.
7. Bộ đánh giá và lượt chạy live.

Kế hoạch chi tiết viết riêng bằng writing-plans sau khi spec này được duyệt.
