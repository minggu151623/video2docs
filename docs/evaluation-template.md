# Đánh giá nhiều lĩnh vực (lượt 1, 05/11/2026)

Lượt chạy thật đầu tiên của bộ 8 video, không phải nghiệm thu. Video lấy từ Wikimedia Commons (CC BY 3.0), tải trực tiếp, không đưa vào Git; nguồn, tác giả, hash và số đo từng video ở [`verification/eval-2026-11-05.json`](verification/eval-2026-11-05.json). Đáp án ghi trước khi xem output, từ ảnh ghép frame 3 giây và bản ghi lời nói local; hash đáp án được khóa trước khi đọc output. Người ghi đáp án cũng là người chạy và chấm (Claude), nên đây không phải đánh giá độc lập. Model `gemini-3.1-flash-lite`, contract v9, tài liệu tiếng Việt, clip 120 giây.

Cách chấm: ghi đáp án theo `fixtures/eval/README.md` trước khi xem output, chạy video qua app, rồi `uv run python scripts/evaluate.py --generation-dir <thư mục generation> --annotation <đáp án>.json` (video non-tutorial bị chặn ở đoạn 1 dùng `--blocked-by-gate`). Script chỉ in số đo; người chấm xem lại các mục lệch bằng mắt trước khi ghi ô. Số "tay" dưới đây là kết quả xem lại đó.

## Bảng chính: các ngưỡng của spec

| # | Loại video | Lời nói | Job | % ✓ đúng (`verified_precision`) | Định lượng/thông số sai mang ✓ | Chặn non-tutorial |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Phần mềm: git commit/push | Tiếng Anh | `needs_review`, 2 lượt gọi | không có mục ✓ | 0 | Không áp dụng |
| 2 | Nấu ăn: kombucha | Không (nhạc, chú thích trên màn hình) | `needs_review`, 2 lượt gọi (thêm 1 ở lần chạy đầu lỗi upload) | không có mục ✓ | 0 | Không áp dụng |
| 3 | Sửa chữa: thay GPU/SSD máy MSI | Không (nhạc, chú thích) | `needs_review`, 5 lượt gọi, 1 lần thử lại upload | không có mục ✓ | 0 | Không áp dụng |
| 4 | Thủ công: punch needle | Không (nhạc, chú thích) | `needs_review`, 2 lượt gọi | không có mục ✓ | 0 | Không áp dụng |
| 5 | Thể thao: dumbbell shoulder press | Tiếng Anh | `needs_review`, 2 lượt gọi | không có mục ✓ | 0 | Không áp dụng |
| 6 | Làm đẹp: serum mọc tóc | Tiếng Anh | `needs_review`, 2 lượt gọi, 1 lần thử lại upload | script 0/1; tay 1/1 | script 1; tay 0 | Không áp dụng |
| 7 | Vlog du lịch | Không có luồng âm thanh | `not_tutorial` sau đoạn 1, 1 lượt gọi | Không áp dụng | Không áp dụng | Đúng |
| 8 | Review camera hành trình | Tiếng Anh | `not_tutorial` sau đoạn 1, 1 lượt gọi | Không áp dụng | Không áp dụng | Đúng |

Ngưỡng khởi điểm theo spec mục 5.2 (người dùng có thể chỉnh, nhưng không chỉnh sau khi đã xem kết quả để coi là đạt):

- Tổng hợp trên 6 video tutorial: >= 95% mục mang `verified` đúng với đáp án.
- 2/2 video không phải tutorial bị chặn ở đoạn 1.
- 0 định lượng hoặc thông số sai nào mang `verified`.

Tổng hợp: cả 6 video tutorial chỉ có **1 mục `verified`** ("Nước 1 cốc", đúng; script tính sai đơn vị vì đáp án ghi "cup"). Theo con số, 1/1 ✓ đúng và 0 định lượng sai mang ✓; **2/2** video không phải tutorial bị chặn ở đoạn 1. Một mục không đủ để nói ngưỡng 95% đạt: lượt này đo được rằng bộ khớp không cho ✓ sai, chưa đo được độ chính xác của ✓ trên số lượng có ý nghĩa.

## Bảng báo cáo thêm (chưa đặt ngưỡng)

| # | Định lượng đúng trong draft nhưng không ✓ | Độ phủ bước: script / tay | Thời gian job | Token (vào / ra) | Cần sửa |
| --- | --- | --- | --- | --- | --- |
| 1 | Không có định lượng; 3 lệnh đúng chưa ✓ | 4/8 / 4/8 | 531 s | 22.575 / 2.767 | OCR đọc dấu nhắc `$` thành `S` nên không bỏ được dấu nhắc; chữ cửa sổ bên cạnh dính vào hàng lệnh. Gemini chép sai hoa/thường `"Removed test.txt"` (đúng là không ✓). Hai bước commit cùng 115 s ở ranh giới đoạn, tiêu đề khác nên không bị đánh dấu trùng |
| 2 | 5/5 (15 gms trà, 45 gms đường, 2 lít nước, 2 tuần, 3–4 ngày, đều đúng) | 10/13 / 13/13 | 249 s | 30.714 / 8.414 | Video không lời: luật R13 chặn mọi số trên màn hình. "Không vặn chặt nắp" được ghi thành thao tác, không thành mục cảnh báo. Bước ủ chai lặp ở ranh giới đã được đánh dấu rà soát |
| 3 | Không ghi số vít (2, 3, 3, 4) thành thông số | 8/23 / khoảng 18/23 | 664 s sau thử lại | 60.802 / 9.855 | OCR hết ngân sách 300 s (3 mục `not_checked`); nhãn lĩnh vực sai (`software` cho sửa phần cứng); R13 |
| 4 | Không có định lượng | 4/10 / 8/10 | 424 s | 22.898 / 3.941 | Thiếu bước thử chỉ và gắn ruy băng |
| 5 | "45 độ" gán nhầm cho độ nghiêng ghế (video nói độ hạ khuỷu tay); đúng là `unverified` | 0/6 / 4/6 | 446 s | 24.437 / 5.155 | Tiêu đề diễn đạt khác nên script không ghép được bước |
| 6 | 9 mục đúng không ✓ (2 thìa canh lá tầm ma/cỏ đuôi ngựa, 1/1/2 tablespoon dầu/gel, 10 và 8 giọt tinh dầu, 15–20 phút) | 2/8 / 4/8 | 792 s sau thử lại | 24.864 / 4.651 | Gemini ghi "gỗ tuyết tùng" thay cho cypress (cây bách) trong mục không có số nên không bị bắt; bước đun nước ghi ở 0 s; thiếu hai bước cách dùng |
| 7 | Không áp dụng | Không áp dụng | 318 s | 10.123 / 207 | |
| 8 | Không áp dụng | Không áp dụng | 166 s | 13.122 / 263 | |

Tổng cộng 18 request phân tích Gemini (kể cả các request ở lần chạy đầu bị lỗi upload), 209.535 token vào và 35.253 token ra; app chưa có bảng giá cho model này nên `estimated_cost_usd` để trống. Lần chạy đầu, 6/8 video lỗi `UPLOAD_OUTCOME_UNKNOWN` trước khi gọi phân tích: clip gửi Google mã hóa CRF 18 ở 1080p (~77 MB cho 2 phút) bị đứt kết nối sau 470 s trên đường upload ~1 Mbps; cùng clip ở 1280 px CRF 26 (~15 MB) upload được trong 129 s. Đã sửa (`docs/decisions.md` mục 61) rồi chạy lại; hai video vẫn cần một lần thử lại upload.

Độ phủ "tay" ghép bước theo nghĩa trong cửa sổ 10 giây (riêng video 3 nới tới khoảng 20 giây), vì `token_set_ratio` không ghép được tiêu đề tiếng Việt diễn đạt khác. Định lượng đúng nhưng không ✓ chủ yếu do: video không có lời nói (R13), đơn vị/tên dịch sang tiếng Việt, và OCR đọc sai dấu nhắc.

## Trước khi chạy cần biết

- Luật số lân cận 8 token và các luật còn lại của bộ khớp (`docs/decisions.md`, mục 26 đến 46) làm một số định lượng đúng bị `unverified`; cột "mục đúng bị `unverified`" có mặt để đo đúng cái giá đó, chưa có ngưỡng.
- Chỗ hở đã biết cho "sai mang ✓": ba ca ở `docs/decisions.md` mục 60 ("..." sau đoạn khớp, tên cạnh tranh ngoài từ điển, "Đường và muối 200g"); nếu cột "sai mang ✓" không đạt, ghi nguyên số, không chỉnh ngưỡng. Từ mục 45 (R13) và 46(b), video không có lời nói vi/en (kể cả transcript có ngôn ngữ nhưng không có từ) không có mục OCR nào chứa số được ✓: ghi riêng số mục như vậy để thấy cái giá. Các luật 37–46 thêm cái giá về recall (OCR so từng từ theo thứ tự, thứ tự "fifth", "point"/"chấm" đứng trước số, câu nhận định khác ngôn ngữ với đơn vị ngoài bảng, chữ tiếng Việt trên màn hình phải trùng từng từ, "nữa" trên OCR, "media").
- Probe schema v2 đã chạy ngày 24/10/2026: Google nhận cả 3 request, 2 kết quả qua Pydantic. Đã có lượt live Python và nấu ăn riêng lẻ; chúng không thay thế bộ 8 video trong bảng. Xem `docs/live-verification.md`.
- Phép chấm khớp tên và số, và ghép bước bằng `token_set_ratio`, có sai số riêng (`fixtures/eval/README.md`).

Không đạt thì sửa prompt/policy/bộ khớp rồi đo lại, không chỉnh báo cáo hoặc ngưỡng để coi là đạt.
