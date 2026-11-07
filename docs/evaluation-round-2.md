# Đánh giá nhiều lĩnh vực (lượt 2, 07/11/2026)

Lượt chạy thật thứ hai, không phải nghiệm thu. Mục đích là có đủ mục ✓ để đo tỉ lệ ✓ đúng: lượt 1 (`docs/evaluation-template.md`) chỉ có 1 mục ✓ khi chạy thật và 6 mục ✓ sau khi sửa bộ khớp.

Video lấy từ Wikimedia Commons (9 video CC BY 3.0, 1 video CC BY-SA 4.0), tải trực tiếp, không đưa vào Git. Nguồn, tác giả, hash, độ dài và số đo từng video nằm ở [`verification/eval-2026-11-07.json`](verification/eval-2026-11-07.json). Đáp án được ghi trước khi xem output và khóa hash trước khi chạy app, dựa trên:

- bản ghi lời nói local;
- ảnh ghép frame 3 giây;
- khung hình đầy đủ ở các mốc gõ lệnh, đọc bằng mắt, không dùng OCR của app.

Người ghi đáp án cũng là người chạy và chấm (Claude), nên đây không phải đánh giá độc lập.

Cấu hình chạy: model `gemini-3.1-flash-lite`, contract v9, tài liệu tiếng Việt, clip 120 giây, code ở commit `b06662a` (5 khung OCR mỗi mục).

## Kết quả chính

| # | Video | Lời nói (app nhận) | Job | ✓ đúng / ✓ (tay) | Sai mang ✓ | Ghi chú |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Phần mềm: giao diện XFCE trên Ubuntu Server | Tiếng Anh | `needs_review`, lần đầu Google trả 503 nên `UNKNOWN_OUTCOME`; thử lại qua endpoint retry thì xong | 4/4 | 0 | ✓ `sudo apt install tasksel`, `sudo reboot`, `sudo systemctl status sshd` (2 mục cùng lệnh). Script chỉ ghép được 2/4 vì đáp án không có lệnh `systemctl`; đã xem khung 322,5 s và 345,5 s: đúng |
| 2 | Phần mềm: X2Go | Tiếng Anh | `needs_review` | 3/3 | 0 | ✓ `sudo add-apt-repository ppa:x2go/stable`, `sudo apt update`, `sudo apt-get install x2goserver x2goserver-xsession`. Hai lệnh sau không có trong đáp án vì lúc ghi đáp án không đọc rõ; đã xem khung 127 s và 146 s: đúng |
| 3 | Phần mềm: USB cài Ubuntu (Rufus) | Tiếng Anh | `needs_review` | 0/0 | 0 | Chỉ có thao tác giao diện; "8 GB", "3.11" là ≈ hoặc ? |
| 4 | Nấu ăn: shio koji | Tiếng Anh | `needs_review` | 1/1 | 0 | ✓ "Koji". Muối 3-10%, lên men 5-14 ngày, ướp 30 phút đều là ≈ vì tên thông số đã dịch |
| 5 | Nấu ăn: cá hấp tương đậu | **Tiếng Mã Lai** (thật ra là tiếng Anh) | `needs_review` | 0/0 | 0 | Whisper nhận nhầm ngôn ngữ nên 9 mục có số bị chặn ("ngôn ngữ chưa hỗ trợ kiểm chứng số"), kể cả các chú thích "10g Ginger", "45g Fermented Soy Bean Paste" mà Gemini chép đúng |
| 6 | Nấu ăn: bò hầm | Không có lời | `needs_review` | **12/12** | 0 | ✓ cà rốt 280 g, gừng 7 g, red wine 75 ml, tomato puree 1 tbsp, dark soy sauce 3 tsp, water 100 ml (mỗi định lượng 2 mục: nguyên liệu và thông số của bước), parsley, brown rice. Script không ghép được 10 mục vì Gemini để tên tiếng Anh; giá trị đều khớp chú thích trên màn hình (đã xem khung 183 s cho "1tbsp tomato puree") |
| 7 | Nấu ăn: hồng treo (hoshigaki) | Tiếng Anh | `needs_review` | 0/0 | 0 | "30 ngày" là ≈ |
| 8 | Thể thao: T-bar row | Tiếng Anh | `needs_review` | 0/0 | 0 | Không có định lượng |
| 9 | May: khăn trùm đầu | **Tiếng Yoruba** (thật ra là tiếng Anh trên nền nhạc) | `needs_review` | 0/0 | 0 | Nhận nhầm ngôn ngữ nên 5 thông số (10, 17, 9 inch…) bị chặn |
| 10 | Phần mềm tiếng Việt: cài mobileUndo trên Wikipedia | Không có luồng âm thanh | `needs_review` | 0/0 | 0 | 7 mục `unverified`; đoạn mã `mw.loader.load(...)` dài qua nhiều dòng trên màn hình điện thoại |

**Tổng: 20 mục `verified`, cả 20 đúng khi xem lại bằng tay; 0 định lượng, thông số hay lệnh sai mang ✓.**

- Gộp với lượt 1 (6 mục sau khi chạy lại kiểm chứng): **26/26 ✓ đúng** trên 16 video tutorial.
- Phần lớn các mục ✓ đến từ vài nguồn:
  - 7/20 là lệnh terminal (video 1, 2);
  - 12/20 nằm ở video bò hầm, nơi Gemini giữ nguyên tên tiếng Anh;
  - 1 mục là tên "Koji".
- Một số mục là cùng một nội dung được ghi hai lần: 4 định lượng của video bò hầm (8 mục) và lệnh `systemctl` (2 mục). Tính theo nội dung khác nhau, có 14 nội dung đúng.
- Mẫu nhỏ và tập trung vào vài video, nên con số này cho thấy app chưa có ✓ sai, chứ chưa chứng minh ngưỡng 95% trên mọi loại video.

`scripts/evaluate.py` chấm 6/20 đúng và 0 sai. 14 mục còn lại nằm ở `verified_unmatched`: mục không có trong đáp án hoặc tên không ghép được. Đó là lý do mỗi mục ✓ đều được xem lại bằng tay.

Tổng 30 request phân tích Gemini (kể cả request bị 503 và lần thử lại): 322.010 token vào, 60.976 token ra tính phí. App chưa có bảng giá cho model này nên `estimated_cost_usd` để trống.

## Độ phủ bước (script, ghép theo tiêu đề rồi theo thời gian)

| # | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Ghép được / đáp án | 7/9 | 6/10 | 7/10 | 5/7 | 7/9 | 8/10 | 5/9 | 3/6 | 7/8 | 4/7 |
| Trong đó chỉ theo thời gian | 1 | 3 | 4 | 4 | 3 | 3 | 4 | 3 | 3 | 2 |

Các cặp ghép chỉ theo thời gian có thể sai (mục 65), nên đây là cận trên. Chưa đếm tay cho lượt này.

## Phát hiện

1. **Whisper nhận nhầm ngôn ngữ làm mất cả video.**
   - Hai video nói tiếng Anh bị nhận là tiếng Mã Lai (giọng Singapore) và tiếng Yoruba (lời nói trên nền nhạc). Bộ khớp coi đó là ngôn ngữ không đọc được số (R2a, R13), nên chặn mọi số, cả trên màn hình.
   - Chiều này an toàn: không có ✓ sai. Nhưng hai video có 14 mục có số không được kiểm.
   - Hướng sửa cần quyết định: khi Whisper đoán một ngôn ngữ ngoài vi/en với độ tin cậy thấp, cho Whisper chọn lại chỉ giữa vi và en, hoặc dùng ngôn ngữ mà Gemini thấy.
2. **Gemini để tên nguyên liệu bằng tiếng Anh** ("red wine", "water") trong tài liệu tiếng Việt ở video bò hầm. Các mục này được ✓ vì trùng từng từ với chú thích, nhưng người đọc tiếng Việt nhận một tài liệu lẫn hai thứ tiếng.
3. **Chú thích hiện rất ngắn vẫn được đọc**: video bò hầm hiện mỗi định lượng khoảng 2–3 giây. Với 5 khung rải 2 giây (mục 71), 4 định lượng tên tiếng Anh cùng "cà rốt 280 g" và "gừng 7 g" đều được ✓.
4. **Tên đã dịch vẫn chỉ được ≈**: các định lượng như "khoai tây mới 280 g", "cần tây 150 g", "thịt bò hầm 500 g", "Muối 3-10%" đúng giá trị nhưng tên đã dịch sang tiếng Việt. "Hành tây 2 củ" từ chú thích "2x onion" không ✓ vì ký hiệu "x" trước số.
5. **Google trả 503** một lần (video 1). App ghi `UNKNOWN_OUTCOME` và dừng thay vì gọi lại, đúng thiết kế chống tính tiền trùng; endpoint retry chạy lại được.
6. **Đáp án có chỗ thiếu**:
   - Lệnh `systemctl`, `apt update` và lệnh cài X2Go bị thiếu vì lúc ghi không đọc rõ.
   - Định lượng trên màn hình của video cá hấp bị thiếu vì đáp án dựa vào lời nói mà không xem ảnh ghép.
   - "1 tbsp tomato puree" của video bò hầm hiện giữa hai khung của ảnh ghép.
   - Đáp án đã khóa nên không sửa; các mục này được xem lại bằng tay ở trên.

## Sau khi kiểm lại ngôn ngữ (mục 72, 07/11/2026)

Chạy lại job kiểm chứng của 10 video (0 request Gemini, cùng draft, bản ghi lời nói làm lại):

- Video 5 (cá hấp) và 9 (may khăn) giờ có bản ghi lời nói tiếng Anh. Các video khác vẫn được nhận đúng như trước và không mục nào đổi trạng thái.
- Video 5: 6 mục từ `unverified` thành ≈. Ví dụ "steam on high for around six to eight minutes", "one to two minutes" khớp giá trị nhưng tên thông số đã dịch.
- Video 9: 5 mục thành ≈ ("10 Inches", "17 Inches", "9 inches"; tên đã dịch).
- Số mục ✓ không đổi: **20, cả 20 đúng**, 0 ✓ sai.
- Còn mở: chú thích song ngữ "10g Ginger 姜" của video 5. OCR (model tiếng Anh) đọc đúng "10g Ginger" nhưng chữ Hán thành ký tự rác, trong khi `on_screen_text` của Gemini chép cả chữ Hán. Vì vậy mục phải khớp nguyên văn và không khớp. Chú thích "1Tbsp Seasame Oil" sai chính tả ngay trong video, còn Gemini sửa thành "Sesame".
