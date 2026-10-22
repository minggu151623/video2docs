# Cải tiến chất lượng bản nháp

Ngày 21/10/2026. Nguồn vấn đề: video Python Windows 11 và generation baseline `b799d6af-064c-49a6-b41a-9be01dc6aa19`.

## Thay đổi

1. Mỗi request có số thứ tự đoạn, tổng số đoạn, offset và tối đa ba tiêu đề bước trước. Ngữ cảnh bản nháp trước được đánh dấu không đáng tin, không được dùng làm bằng chứng hay chỉ dẫn. Model vẫn trả timestamp local; backend chỉ cộng offset một lần.
2. Claim trong chuẩn bị/xử lý lỗi có `basis` (`observed`, `stated`, `inferred`, `unclear`) và `scope` (`tutorial`, `clip`). Model phải khai báo các trường này; JSON cũ thiếu trường vẫn đọc được nhưng mặc định chưa đủ bằng chứng. `stated` phải có audio/both, `observed` phải có visual/both.
3. Khi ghép, điều kiện từ các đoạn sau luôn thuộc phạm vi đoạn. Renderer tách chúng khỏi chuẩn bị cho cả tutorial. Nhận xét chưa rõ có mốc nguồn và nhãn phạm vi đoạn.
4. Claim inferred/unclear giữ nguyên trong JSON và được đưa vào phần cần kiểm tra của Markdown, không trình bày như hướng dẫn xử lý lỗi đã có bằng chứng. Generation mang trạng thái `needs_review` nếu có các claim này.
5. (Đã nới ngày 22/10/2026, xem cuối tài liệu.) Chọn mốc ảnh trong phần giao giữa bước và bằng chứng visual. Với bước có kết quả, ưu tiên mốc đề xuất muộn hơn có bằng chứng. Nếu mốc được đề xuất mâu thuẫn với khoảng bằng chứng, không tự chọn mốc dự phòng: bỏ ảnh của bước đó, gắn review reason và warning `EVIDENCE_TIMESTAMP_CONFLICT`. Trung điểm chỉ dùng khi không có đề xuất, và phải nằm trong phần giao giữa bước và bằng chứng. Đây là sửa đổi sau khi xem ảnh của lượt pipeline pass đầu: có một mốc dự phòng rơi vào phần quảng cáo cuối video.
6. Prompt yêu cầu chỉ lấy xử lý lỗi được trình diễn/nói rõ và ưu tiên ảnh cấu hình/kết quả. Contract adapter v7 và prompt hash mới chặn tái dùng checkpoint cũ. Không thêm synthesis call; giới hạn vẫn một semantic repair/job.
7. Lượt kiểm tra đầu của thay đổi này gặp JSON sai sau một repair. Phát hiện luồng repair cũ chỉ gửi vị trí/thông báo lỗi, không gửi JSON cần sửa, nên model phải tạo lại. Repair nay nhận response gốc trong khối dữ liệu không đáng tin, giới hạn 128 KiB UTF-8, chỉ giữ tạm trong bộ nhớ và không ghi raw response vào audit. Payload vượt giới hạn bị từ chối, không bị cắt âm thầm. Danh sách ảnh có `maxItems=2` trong schema provider; keyword này thuộc [subset được Google hỗ trợ](https://ai.google.dev/gemini-api/docs/structured-output#json-schema-support).

## Tiêu chí đối chiếu live, chốt trước lượt chạy

- Cả hai đoạn validate, timestamp global đúng và các file xuất dùng generation của chính job mới.
- Trạng thái “đang cài đặt” ở đầu đoạn sau không trở thành yêu cầu chung trước tutorial.
- Không có lời khuyên PATH chưa đủ bằng chứng nằm trong phần hướng dẫn xử lý lỗi. Nếu có suy luận, nội dung phải hiện ở phần cần kiểm tra.
- Nhận xét thiếu thông tin được trình bày với phạm vi/mốc nguồn, tránh kết luận cho cả video.
- Xem ảnh của các bước hoàn tất cài đặt, kiểm tra phiên bản, IDLE và lưu tệp; đối chiếu với video gốc. Đánh giá ảnh có cho thấy nội dung/kết quả phù hợp hay chỉ màn hình mở ứng dụng.
- MD/ZIP/PDF hợp lệ, xem đủ các trang PDF, cleanup không pending, video gốc và các output baseline không đổi.

Đây là đánh giá trước/sau trên một video đã biết. `basis` do model khai báo và kiểm tra modality chỉ là kiểm tra cấu trúc, không phải bằng chứng xác minh ngữ nghĩa độc lập. Chưa suy ra chất lượng trên video khác hoặc điểm rubric của bộ năm tutorial.

## Kiểm thử

84 tests pass trong 29,78 giây; Ruff pass; frontend types được sinh lại từ Pydantic và production build pass. Các regression mới kiểm tra phạm vi điều kiện giữa đoạn, tương thích JSON cũ, claim suy luận được giữ để review, modality của claim, timestamp ảnh trong bước/bằng chứng, ngữ cảnh trước có giới hạn và luồng worker hai đoạn. Regression repair kiểm tra JSON gốc được chuyển chính xác, dữ liệu quá lớn bị chặn, không thể đóng khối untrusted bằng nội dung lồng bên trong, và marker raw response không xuất hiện trong audit trả từ API. Test ảnh mâu thuẫn bảo đảm không tự chuyển sang mốc cuối đoạn có thể chứa quảng cáo.

## Kết quả live

Generation cuối: `01abf369-34c2-40a8-a0f0-e464dd80dd65`, project `9a591044-8489-4534-b12a-7d10672c736e`. **Pipeline pass sau một lần retry checkpoint có chủ đích**, trạng thái nội dung vẫn `needs_review`. Hai đoạn cho 10 bước, 10 ảnh, MD/ZIP/PDF 11 trang. Đã xem đủ 11 trang PDF; ZIP integrity và revision pass; browser không có JS exception; cleanup pending 0; video và ba file xuất baseline giữ nguyên hash.

Lượt đầu v7 có đoạn 1 hợp lệ, đoạn 2 sai timestamp ảnh cả analyze và một repair nên dừng. Retry chỉ gọi lại đoạn 2 một request và tái dùng checkpoint đoạn 1. Tổng lượt v7 gồm 3 request ở job đầu và 1 request retry, không tính các thử nghiệm v5/v6 được giữ riêng. Không mô tả đây là thành công ngay lần đầu hoặc bảo đảm mọi clip sẽ pass.

| Đối chiếu trên video này | Baseline | Sau cải tiến |
| --- | --- | --- |
| Trạng thái đang cài đặt ở đầu đoạn sau | Nằm trong chuẩn bị toàn tài liệu | Tách vào Ngữ cảnh theo đoạn, mốc 115 giây |
| Lời khuyên PATH giả định | Có trong hướng dẫn xử lý lỗi | Không còn; mục xử lý lỗi nói không được nêu trong video |
| Nhận xét đoạn bị cắt | Không hiện phạm vi/mốc trong Markdown | Có nhãn phạm vi đoạn nguồn và mốc 119–120 giây |
| Hoàn tất cài đặt | Ảnh 120 giây: progress | Ảnh 134 giây: Setup was successful |
| Kiểm tra phiên bản | Ảnh 140 giây: Start menu | Ảnh 151 giây: Python 3.13.0 trong Command Prompt |
| Chạy print | Ảnh 163 giây: Start menu | Ảnh 180 giây: lệnh và kết quả Amit Diwan |
| Lưu tệp | Ảnh 185 giây: File menu | Ảnh 197 giây: Save As với tên Demo |

**Giới hạn còn thấy:** timestamp của các bước Optional Features/Advanced Options ở đoạn đầu chưa chính xác; sắp xếp theo timestamp khiến bước tùy chọn nâng cao xuất hiện sau bước hoàn tất ở vùng overlap. Các ảnh tùy chọn cài đặt đôi lúc còn là màn hình progress. Cần đối chiếu và sửa thứ tự các bước này trước khi làm theo tài liệu. Bộ lọc `basis` không tự chứng minh rằng mọi claim được model gắn observed/stated đều đúng; vẫn cần kiểm tra nội dung với video. Số bước/ảnh tăng không phải điểm chính xác.

[Báo cáo cuối](verification/live-quality-improvement.json), [Markdown](../output/live-quality-improved/document.md), [ZIP](../output/live-quality-improved/document.zip), [PDF](../output/live-quality-improved/document.pdf).

## Contract v8: timestamp MM:SS (22/10/2026)

**Nguyên nhân sai timestamp/thứ tự Optional Features/Advanced Options.** Đối chiếu frame nguồn: Optional Features khoảng 62–81 giây, Advanced Options khoảng 81–100 giây, bấm Install khoảng 100 giây. Đoạn 1 của generation `01abf369…` ghi bằng chứng Optional Features `104–118`, ảnh `105`/`117` và Advanced Options `119–120`. Đây là `01:04–01:18`, `01:05`/`01:17` và `01:19–01:20` bị viết dính thành số giây. Đoạn dài 120 giây nên các giá trị sai vẫn lọt validation. Hệ quả là bước Advanced Options bị xếp sau bước hoàn tất cài đặt, ảnh 117 giây rơi vào màn hình progress, và có nhận xét sai rằng "clip kết thúc khi cài đặt vừa bắt đầu". Lỗi sai screenshot ở đoạn 2 trong các lượt trước (đoạn ngắn hơn 102 giây) cũng khớp với cách hiểu này.

**Thay đổi.** Với static video, Gemini nhận mốc thời gian mỗi giây và tài liệu Google hướng dẫn tham chiếu mốc theo dạng `MM:SS`. Schema gửi provider dùng chuỗi `MM:SS` với tên trường `start`, `end`, `screenshot_times`, không còn hậu tố `_sec`. Metadata (`clip_start`, `previous_steps.end`) và `clip_duration` cũng được gửi dạng `MM:SS`. Adapter đổi về giây trước khi validate bằng Pydantic; schema ứng dụng, checkpoint, DB và frontend vẫn dùng giây. Chuỗi mơ hồ như `"104"` hay `"1.04"` bị từ chối với vị trí trường và đi vào luồng repair hiện có (vẫn tối đa một repair/job), thay vì được hiểu âm thầm thành 104 giây. Contract adapter lên v8 nên checkpoint v7 không được tái dùng.

**Ghép đoạn.** Tool trùng tên và phiên bản giữa các đoạn được gộp, nối evidence span (tối đa 5), thay vì lặp lại.

**Kiểm thử.** 104 tests pass, Ruff pass.

### Kết quả live v8 (22/10/2026)

Người dùng đồng ý gửi video và chấp nhận phí. Project `f697ad8f-9fc8-411c-97a0-c5631b704143`, generation `3185b006-cf33-4379-a17a-f9b4f7bcee8e`. Hai job đầu dừng `UNKNOWN_OUTCOME` vì Google trả HTTP 503 "high demand" ở đoạn 1, không có output hoặc usage. Để loại trừ khả năng schema gây lỗi, đã gửi 5 request chỉ có text: schema v8 được chấp nhận 3/3 lần, latency 12–168 giây với cả hai schema, khớp với tình trạng quá tải. Retry thứ hai **pipeline pass**: 2 request analyze, không repair, 9 bước, 6 ảnh, MD/ZIP/PDF 8 trang, cleanup pending 0, hash nguồn giữ nguyên. Đã xem đủ 8 trang PDF. Usage: 22.683 input, 3.860 output, 2.705 thinking token.

| Bước | Baseline v7 | v8 | Frame gốc |
| --- | --- | --- | --- |
| Optional Features | 60–118 s, bằng chứng 104–118 | 59–77 s, bằng chứng 60–63 và 76–77 | khoảng 62–81 s |
| Advanced Options | 119–120 s, xếp sau bước hoàn tất | 78–99 s, đứng trước progress | khoảng 81–100 s |
| Progress | không có bước riêng | 100–120 s | 101–130 s |
| Thứ tự | Advanced Options sau "Hoàn tất cài đặt" | đúng thứ tự video | |
| Nhận xét sai "clip kết thúc khi vừa cài đặt" | có | không còn | |

Không còn timestamp đoạn 1 kiểu `MM:SS` viết dính thành số giây; ảnh 85 giây là Advanced Options thay vì màn progress.

**Còn tồn tại:**
- Ba bước bị bỏ ảnh với `EVIDENCE_TIMESTAMP_CONFLICT`: mốc đề xuất nằm trong bước nhưng ngoài khoảng bằng chứng hẹp, cụ thể Optional Features đề xuất 64 s so với bằng chứng 60–63, phiên bản 148 so với 149–152, IDLE 169 so với 179–182. Trong khoảng bằng chứng có frame tốt hơn: 151 s thấy `Python 3.13.0`, 180 s thấy `Amit Diwan`. Chính sách không tự chọn mốc dự phòng (mục 5) đang loại các ảnh này. Số ảnh giảm từ 10 xuống 6.
- Ảnh "Hoàn tất cài đặt" ở 130 s vẫn là progress 100%; màn "Setup was successful" ở khoảng 134 s.
- Ngữ cảnh đoạn có "Kết nối Internet" (suy luận) và "Đã cài đặt Python" ở mốc 115 s, trong khi lúc đó cài đặt vẫn đang chạy.
- Bước 1 gộp tìm kiếm, tải và mở file; bản trước tách thành ba bước.

### Chọn ảnh khi mốc đề xuất lệch bằng chứng (22/10/2026)

Theo quyết định của người dùng, mục 5 được nới: khi mọi mốc ảnh đề xuất nằm ngoài khoảng bằng chứng visual, worker không bỏ ảnh nữa mà dùng frame cuối của khoảng bằng chứng visual kết thúc muộn nhất. Khoảng này đã được cắt theo phạm vi bước và lùi 0,5 giây nếu chạm EOF, nên ảnh không thể rơi ra ngoài bước (trường hợp quảng cáo cuối video trước đây là do mốc nằm ngoài phần giao này). Bước vẫn mang `needs_review` với lý do "đã dùng frame cuối của khoảng bằng chứng", kèm warning `EVIDENCE_TIMESTAMP_CONFLICT` có `fallback_sec`. Nếu bước không còn khoảng visual nào thì vẫn bỏ ảnh như cũ. Chuỗi `evidence_policy` trong contract hash đổi theo.

Đối chiếu offline trên draft live v8, không gọi Gemini: ba bước trước đây bị bỏ ảnh nay lấy 77 s (Optional Features, con trỏ ở Next), 152 s (`python --version` ra `Python 3.13.0`) và 182 s (`print("Amit Diwan")` cùng kết quả). Cả ba frame đã được xem và khớp nội dung. Generation live đã lưu không tự cập nhật; muốn có ảnh trong tài liệu đó cần chọn lại ảnh theo giây trong UI hoặc chạy job mới. 106 tests pass.

Đây là một lượt trên một video, chưa phải điểm rubric. [Báo cáo](verification/live-v8-mmss.json), [Markdown](../output/live-v8-mmss/document.md), [PDF](../output/live-v8-mmss/document.pdf).
