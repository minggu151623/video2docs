# Kiểm tra Gemini thật với video người dùng

Khởi tạo: 20/10/2026; cập nhật: 21/10/2026, Asia/Ho_Chi_Minh. Đây là báo cáo live, tách khỏi các test mock trước đó.

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
