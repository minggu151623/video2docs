# Ghép bước ở ranh giới đoạn

Ngày kiểm tra: 28/10/2026. Thay đổi này chạy local, không thêm request Gemini.

## Vấn đề và cách sửa

Trước đây, hai bước chồng thời gian có cùng tiêu đề và thao tác sẽ làm bước sau bị bỏ, kể cả khi bước sau có cảnh báo, thông số, lệnh, mẹo hoặc kết quả khác. Khoảng thời gian và bằng chứng của bước sau cũng bị mất. Hai bước cùng tiêu đề nhưng diễn đạt thao tác khác nhau có thể không được cảnh báo vì điểm tương đồng của cả đoạn văn thấp.

Giờ chỉ gộp bước từ hai đoạn liền nhau có thời gian chồng lấn và toàn bộ nội dung tương ứng giống nhau. So sánh nội dung giữ nguyên chữ hoa/thường của lệnh và giá trị; không dùng độ tương đồng để tự xóa. Khi gộp, giữ thời gian bao phủ cả hai, bằng chứng cấp bước và cấp mục, ảnh đề xuất cùng lý do rà soát. Nếu vượt giới hạn schema, giữ cả hai bước thay vì cắt bằng chứng.

Bước cùng tiêu đề hoặc có nội dung rất giống nhau nhưng chưa đủ điều kiện gộp được giữ và đánh dấu ở cả hai phía, có ID để đối chiếu. Lặp lại ở thời điểm khác hoặc các bước trong cùng đoạn không bị tự gộp. Cảnh báo cũ được giữ nguyên. Bộ lọc trên giao diện giữ cả bước có `needs_review`, kể cả khi bước đó không có mục văn bản chưa kiểm chứng.

## Kiểm tra thực hiện

- 1.380 tests pass, 3 test engine thật `slow` nằm ngoài lượt mặc định; 53,42 giây. Thêm 17 ca cho việc giữ cảnh báo/thông số/lệnh/mẹo/kết quả, bằng chứng lồng nhau, giới hạn schema, lặp theo thời gian, bất biến đầu vào và cảnh báo tiếng Anh.
- Ruff `--select F`, `git diff --check` và TypeScript/Vite build pass.
- 22 nhóm kiểm tra trình duyệt pass với API/worker mock và dữ liệu riêng, gồm regression cho bộ lọc, sửa/lưu/khôi phục, xuất MD/ZIP/PDF, màn hình chặn non-tutorial, kích thước 375px và bàn phím. Không có lỗi JavaScript. Lượt này không chạy ca dừng worker/hủy job vì không truyền PID worker cho harness.
- Anti Slop trong phạm vi sửa hành vi bộ lọc: R-26/R-35 PASS bằng click-through thực tế; R-03/R-32 PASS bằng kiểm tra 375px và focus bàn phím. Giữ giao diện sáng và bố cục hiện tại để người dùng vẫn tìm thấy cảnh báo ở đúng vị trí.

## Ghép lại từ các đoạn thật đã lưu

Đọc DB ở chế độ chỉ đọc, kiểm tra hash của từng checkpoint trước khi ghép. Không gọi provider, không chạy lại ASR/OCR, không thay đổi generation hoặc revision gốc. Bản xem trước dùng ảnh đã lưu và không kế thừa dấu kiểm chứng cũ vì chỉ số bước có thể thay đổi sau ghép.

| Video | Trước | Sau | Kết quả |
| --- | --- | --- | --- |
| Nấu ăn | 12 bước | 12 bước | Hai bước đánh bông trứng được đánh dấu để rà soát; giữ mẹo làm lạnh ở bước trước và cảnh báo đánh quá tay ở bước sau |
| Python | 11 bước | 11 bước | Không có thay đổi trong các bước |

[Audit JSON](verification/assembly-replay-2026-10-28.json). Bản xem trước chỉ nằm trên máy chạy kiểm tra (`output/assembly-review-2026-10-28/`, không đưa lên repo vì chứa nội dung video).

Đây là kiểm tra phần ghép trên dữ liệu cũ, không phải đánh giá độ chính xác trên video mới. Cặp bước nấu ăn chưa được tự gộp vì nội dung khác nhau; vẫn cần người đọc quyết định cách diễn đạt thao tác liên tục. Chưa hoàn thành bộ đánh giá 8 video.

Thay đổi áp dụng cho lần phân tích/ghép mới sau khi khởi động lại worker. Nút Kiểm chứng lại chỉ chạy ASR/OCR, không ghép lại các đoạn và không sửa tài liệu đã biên tập.
