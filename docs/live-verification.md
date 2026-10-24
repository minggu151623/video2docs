# Kiểm tra Gemini thật với video người dùng

Khởi tạo: 20/10/2026; cập nhật: 21/10/2026, Asia/Ho_Chi_Minh. Đây là báo cáo live, tách khỏi các test mock trước đó.

## Schema v2 và kiểm chứng ASR/OCR ngày 24/10/2026

Người dùng đồng ý phí. Nhánh `feat/general-tutorials` tại `72006e2`, model `gemini-3.1-flash-lite`, đoạn 120 giây.

**Probe schema v2 (chỉ văn bản, 3 request).** Google chấp nhận schema provider v2 (~16 KB): 3/3 `completed`, 5–7 giây, không có HTTP 400. 2/3 qua validation Pydantic; 1 lần model ghi thông số "Mức lửa" là `observed` mà không chép `on_screen_text`, trái quy tắc prompt, trong app sẽ tốn lượt repair duy nhất của job. [Kết quả](verification/schema-v2-probe.json).

**Toàn video Python Windows 11.** Project `3152f50e-cfe0-4fa6-8136-6d03b926107c`. Pipeline pass ngay lần đầu: 2 request analyze, không repair (13.057 + 11.582 token đầu vào), 11 bước, 11 ảnh, MD/ZIP/PDF 12 trang, cleanup pending 0, hash nguồn giữ nguyên. Gemini xếp đúng lĩnh vực `software`, `is_tutorial=true`. [Báo cáo](verification/live-v9-general.json).

| Giai đoạn | Thời gian |
| --- | --- |
| Chép lời nói (ASR, gồm lần đầu tải whisper `small` 927 MB) | 48 s |
| Phân tích 2 đoạn (chuẩn bị + upload + Gemini) | 80 s |
| Trích ảnh | 16 s |
| Kiểm chứng (OCR 4 mục + khớp) | 92 s |
| Tổng job, video 3 phút 37 | 237 s |

ASR nhận ngôn ngữ `en`, 431 từ, chép đúng lời người nói (kể cả "python space hyphen hyphen version").

**Đối chiếu frame gốc.** Thứ tự 11 bước khớp video; Optional Features 59–78 s, Advanced Options 79–99 s, progress 99–120 s, hoàn tất 115–135 s. Ảnh đúng nội dung ở 10/11 bước: Advanced Options 93 s, progress 110 s, "Setup was successful" 134 s (lượt v8 chỉ có progress), `python --version` + `Python 3.13.0` 150 s, IDLE `print("Amit Diwan")` 179 s, Save As "Demo" 192 s. Ảnh bước "Tùy chỉnh tính năng" (63 s) là màn hình đầu đang bấm Customize, chưa phải Optional Features.

**Kiểm chứng: 6 mục, 2 ✓, 4 ?.**

| Mục | Trạng thái | Đối chiếu |
| --- | --- | --- |
| Lệnh `python` (tìm trên Google) | ✓ OCR 13,5 s | Đúng |
| Ngữ cảnh đoạn "Đã hoàn tất cài đặt Python" | ✓ OCR 115 s | **Sai về nghĩa**: chữ trích "Setup Progress" có trên màn hình, nhưng lúc 115 s cài đặt còn đang chạy. ✓ chỉ chứng minh chữ trích tồn tại, không chứng minh câu diễn giải |
| Lệnh `python --version` | ? | Có trên màn hình 150 s; hàng OCR là `C:\Users\hp>python --version`, dấu nhắc Windows chưa được bỏ |
| Lệnh `print("Amit Diwan")` | ? | Có trên màn hình 179 s; hàng OCR có dấu nhắc IDLE `>>>` |
| Thông số "Tên tệp: Demo" | ? | Đúng; bị luật tên mục phải có trong nguyên văn |
| Chuẩn bị "Windows 11" | ? | Đúng; lý do "giá trị không có trong nguyên văn" |

Trên video này: 1/2 ✓ sai nghĩa (mục tiêu spec ≥ 95% ✓ đúng) và 4 mục đúng bị "?". Video phần mềm có ít định lượng nên phần kiểm chứng định lượng chưa được thử; cần một video nấu ăn hoặc sửa chữa. Một video không phải điểm rubric.

**Kiểm chứng lại sau khi sửa (24/10/2026, không gọi Gemini).** Sau commit `2c0f00c` (bỏ dấu nhắc `C:\...>`, `>>>`, `...`, `In [n]:` khi khớp lệnh OCR; mô tả chỉ được ✓ khi cùng ngôn ngữ và trùng từng từ với câu trích, ngược lại là `quote_matched` "≈ khớp nguyên văn … “đoạn đã khớp”"), chạy job `verify` trên cùng generation: 0 request provider, 77 giây (OCR), generation vẫn `needs_review`. [Kết quả](verification/live-v9-reverify.json).

| Mục | Trước | Sau |
| --- | --- | --- |
| Lệnh `python` 13,5 s | ✓ | ✓ |
| Lệnh `python --version` | ? | ✓ OCR 150 s |
| Lệnh `print("Amit Diwan")` | ? | ✓ OCR 177 s |
| "Đã hoàn tất cài đặt Python" (sai nghĩa) | ✓ | ≈ khớp nguyên văn “setup progress”, liệt kê ở "Điểm chưa rõ" |
| "Tên tệp: Demo", "Windows 11" | ? | ? (luật tên mục; giá trị không có trong nguyên văn) |

3/3 ✓ đúng trên video này; 2 mục đúng vẫn "?". Đây vẫn là một video phần mềm, chưa đo phần định lượng.

**Kiểm chứng lại offline sau follow-up 2 (`docs/decisions.md` mục 47–48), không gọi Gemini.** Cùng draft, transcript ASR đã cache và PaddleOCR local trên các frame `ocr_seconds` của từng mục: `python --version` ✓ OCR 150 s, `print("Amit Diwan")` ✓ OCR 177 s; câu "Đã hoàn tất cài đặt Python" thành `quote_matched` (≈, chưa kiểm chứng câu diễn giải), không còn ✓. Lệnh `python` (13,5 s) lần này ra "?" cả với code trước thay đổi: OCR offline đọc hàng thành `α python` thay vì `python`, khác lượt live; không do thay đổi này.

## Cải tiến chất lượng ngày 21/10/2026

Kết quả mới nhất: [báo cáo cải tiến](quality-improvements.md) và [audit JSON](verification/live-quality-improvement.json). Contract v7 giữ scope của các claim, chuyển phần suy luận sang review, truyền ngữ cảnh ba bước trước và chặn mốc ảnh mâu thuẫn. Repair nhận JSON gốc có giới hạn trong bộ nhớ, không lưu raw vào audit.

Lượt v7 đầu lỗi timestamp ở đoạn 2 sau một repair; retry có chủ đích tái dùng đoạn 1 và chỉ gọi lại đoạn 2 một lần. Pipeline cuối pass: **10 bước, 10 ảnh, PDF 11 trang**, MD/ZIP/PDF cùng revision, browser không JS exception, cleanup pending 0 và hash nguồn/baseline giữ nguyên. 84 tests và frontend build pass. Bốn ảnh kết quả chính đã đối chiếu: hoàn tất cài đặt 134 giây, phiên bản 151 giây, print 180 giây và Save As 197 giây.

Vẫn là `needs_review`: timestamp và thứ tự Optional Features/Advanced Options chưa chính xác, vài ảnh cấu hình còn là màn hình progress. Đây không phải nghiệm thu nội dung hay benchmark video khác. Báo cáo giữ cả các lượt fail và lượt pipeline pass nhưng ảnh chưa đạt, không chỉ giữ lần thành công.

## Baseline Gemini 3.1 Flash Lite ngày 21/10/2026

Người dùng yêu cầu đổi sang `gemini-3.1-flash-lite`, cung cấp hạn mức 15 RPM, 250k TPM, 500 RPD. Key truy cập metadata model thành công. Đây là thay đổi được người dùng yêu cầu, không phải fallback tự động. Quota còn lại của tài khoản chưa được đo.

| Mục | Kết quả |
| --- | --- |
| Video | Giữ nguyên video 216,642177 giây và hash nguồn |
| Chia đoạn | 0–120 và 115–216,642177 giây, overlap 5 giây |
| Lượt đầu Flash Lite | Đoạn 1 hợp lệ sau một repair; đoạn 2 sai screenshot timestamp, job dừng đúng giới hạn một repair/job |
| Sửa chỉ dẫn | Nêu rõ giây thay vì phút:giây; start <= end; screenshot nằm trong bước, trước EOF; có thể để mảng ảnh rỗng. Giữ nguyên validation |
| Lượt sau sửa | **Pipeline pass**, 2/2 đoạn, 2 request analyze, không repair; requested/returned model đều là `gemini-3.1-flash-lite` |
| Usage lượt pass | 21.231 input, 3.442 output và 1.466 thinking token; billable output chuẩn hóa 4.908 token |
| Tài liệu | 7 bước, 7 ảnh FFmpeg; `needs_review`, không gắn nhãn nội dung đã được nghiệm thu |
| Export | MD + ZIP + PDF thật 8 trang; ZIP khớp revision và integrity pass; đã render và xem đủ 8 trang PDF |
| Browser | Model và tài liệu hiện đúng; không JavaScript exception trong lượt kiểm tra |
| Cleanup | `cleanup_pending=0` |
| Regression | 72 tests pass, 28,41 giây; Ruff pass |

Job pass: `e21d7161-e0a7-4315-a8c2-706cd9c5aaab`, generation `b799d6af-064c-49a6-b41a-9be01dc6aa19`. Báo cáo đầy đủ: [live-flash-lite.json](verification/live-flash-lite.json). Lượt đầu: [live-flash-lite-initial-failure.json](verification/live-flash-lite-initial-failure.json). Các file [Markdown](../output/live-test-gemini31-flash-lite/document.md), [ZIP](../output/live-test-gemini31-flash-lite/document.zip), [PDF](../output/live-test-gemini31-flash-lite/document.pdf) được xuất từ cùng revision.

**Pipeline pass không đồng nghĩa nội dung hoàn toàn đúng.** Đối chiếu cho thấy điều kiện “đã bắt đầu cài đặt” là ngữ cảnh đầu đoạn 2, không phải điều kiện của cả tutorial. Nhận xét “không thấy tùy chọn cài đặt” chỉ đúng với đoạn 2, trong khi đoạn 1 có hiển thị chúng. Phần xử lý lỗi PATH có suy diễn chưa được bằng chứng visual đi kèm xác nhận. Một số ảnh cho thấy thao tác mở ứng dụng thay vì kết quả cuối; có thể chọn lại ảnh không gọi AI. Command `python --version`, chuỗi `print("Amit Diwan")` và tệp `Demo.py` đã đối chiếu với frame nguồn. Đây là spot check trên một video, chưa phải điểm rubric.

Chi phí trong app giữ unknown do chưa có snapshot giá phù hợp Flash Lite; không lấy giá Gemini 3.8 để tính cho model mới. Không suy ra key miễn phí hay tổng hóa đơn từ quota người dùng cung cấp. [Tài liệu model](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [giá tham chiếu](https://ai.google.dev/gemini-api/docs/pricing).

## Lịch sử Gemini 3.8 Flash ngày 20/10/2026

| Mục | Kết quả đo được |
| --- | --- |
| Key | Backend đọc được; không đưa giá trị key vào báo cáo/frontend |
| Model metadata | `models/gemini-3.8-flash` phản hồi thành công |
| Text thật | Gemini trả đúng token kiểm tra; usage 12 input, 8 output, 110 thinking |
| Video nguồn | `video_test/HowtoinstallPythonWindows11.mp4`, 5.585.933 byte, 216,642177 giây, 1280×720, H.264 + AAC |
| Smoke 25 giây | **Pass thật**: 3 bước, 3 ảnh FFmpeg, một semantic repair trong giới hạn |
| Tài liệu smoke | Tạo đúng phần mở Chrome, tìm Python, truy cập python.org; báo rõ clip chưa có phần cài đặt |
| Export smoke | MD + ZIP + PDF thật; ZIP integrity pass; PDF 4 trang đã render và xem đủ 4 trang |
| Toàn video, lượt đầu | Hai response đều không qua validation; job `SCHEMA_INVALID`, không lưu như tài liệu hoàn chỉnh |
| Toàn video, lượt sau | `UNKNOWN_OUTCOME`; chưa xác nhận kết quả/usage phía Google; không tự gửi lại |
| Cleanup | Các job video trên đều báo `cleanup_pending=0` sau gọi xóa file Google |
| Nguồn | Hash trước/sau không đổi |
| Regression | **71 tests pass**, 26,21 giây; Ruff `--select F` pass |

Tại mốc 20/10, pipeline chưa hoàn tất trên toàn video. Người dùng sau đó đã xác nhận khả năng phát sinh phí lại để thử đoạn tối đa 120 giây. Lượt 3.8 này vẫn lỗi schema: đoạn đầu hợp lệ, đoạn cuối sai evidence span; báo cáo được giữ tại `output/live-test-python-windows11/report-attempt-3.json`. Ngân sách 1 USD/job là soft cap của app, không phải bảo đảm hóa đơn Google. Kết quả hiện tại bằng Flash Lite nằm ở phần đầu báo cáo.

## Bằng chứng

- [Smoke report thật](live-smoke.json), gồm model, SDK, usage từng attempt và cleanup.
- [Kết quả toàn video ban đầu](verification/live-full-initial-failure.json).
- [Kết quả toàn video gián đoạn](verification/live-full-interrupted.json).
- [Quan sát frame nguồn trước khi chạy toàn video](verification/live-reference.json): mốc 25/60/100/150/200 giây. Đây là spot check, không phải điểm chất lượng trên bộ 5 tutorial.
- [Thư mục output smoke](../output/live-smoke-25s/) chứa MD, ZIP, PDF và ảnh.

Chi phí tham chiếu Standard của riêng smoke pass là 0,0128565 USD cho hai response có usage. Con số này không bao gồm các response bị từ chối/gián đoạn không trả usage, không phải tổng hóa đơn thực tế của toàn phiên kiểm tra.

## Những sửa đổi sau kiểm tra thật

1. Schema Pydantic gốc gửi trực tiếp bị HTTP 400 `invalid_request`; chuyển sang subset gọn tự sinh theo tài liệu structured output. Giới hạn đầy đủ và validation ngữ nghĩa vẫn nằm ở Pydantic; không đổi model/provider và không nới tiêu chuẩn nhận kết quả.
2. Thêm trần timestamp theo duration đo được vào schema gửi provider, không tự clamp kết quả sai. Screenshot phải trước EOF.
3. Repair nhận location/type/message cụ thể và duration; không lưu raw model input/output vào log. Lỗi validation được lưu ở warnings chỉ gồm field/mã/thông báo.
4. Snapshot hash của contract adapter/schema chặn dùng lại checkpoint từ contract khác.
5. Lỗi provider từ nay lưu mã HTTP và loại exception đã lọc trong audit để phân biệt transport với lỗi request mà không lộ key/payload. Lượt gián đoạn trước sửa này chỉ có trạng thái unknown; không suy đoán nguyên nhân cụ thể.

71 kiểm thử gồm các regression cho schema projection, duration bounds, repair có lý do cụ thể, đổi contract và phân loại lỗi provider. Chưa tính bài test mock là bằng chứng live.

## Giới hạn đánh giá

Chỉ một video người dùng được cung cấp. Chưa hoàn thành bộ 5 tutorial, chưa đo coverage/timestamp theo rubric đầy đủ, chưa thử thao tác cài đặt trong Windows. Không có command từ video được thực thi trên máy này.
