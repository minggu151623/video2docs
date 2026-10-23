# Đánh giá nhiều lĩnh vực (chưa chạy)

Đây là mẫu để điền kết quả thật, không phải kết quả nghiệm thu. **Bộ 8 video chưa được chạy**: chưa có video có quyền sử dụng, chưa có đáp án, chưa gửi video nào lên Google cho mục đích này. Mọi ô dưới đây là "Chưa chạy" hoặc "Chưa có" cho đến khi có số đo thật. Gửi video lên Google cần người dùng đồng ý và chấp nhận phí (spec mục 5.2).

Cách chấm: ghi đáp án theo `fixtures/eval/README.md` trước khi xem output, chạy video qua app, rồi `uv run python scripts/evaluate.py --generation-dir <thư mục generation> --annotation <đáp án>.json` (video non-tutorial bị chặn ở đoạn 1 dùng `--blocked-by-gate`). Script chỉ in số đo; người chấm xem lại các mục lệch bằng mắt trước khi ghi ô.

## Bảng chính: các ngưỡng của spec

| # | Loại video | Quyền sử dụng/hash | Đáp án trước output | Job/model | % ✓ đúng (`verified_precision`) | Định lượng/thông số sai mang ✓ (`wrong_verified_quantities`) | Chặn non-tutorial (`not_tutorial_correct`) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Phần mềm (IDE/terminal, lệnh rõ) | Chưa có | Chưa có | Chưa chạy | Chưa đo | Chưa đo | Không áp dụng |
| 2 | Nấu ăn (định lượng, nhiệt độ, thời gian) | Chưa có | Chưa có | Chưa chạy | Chưa đo | Chưa đo | Không áp dụng |
| 3 | Sửa chữa (kích cỡ linh kiện, lực siết, an toàn) | Chưa có | Chưa có | Chưa chạy | Chưa đo | Chưa đo | Không áp dụng |
| 4 | Thủ công (vật liệu, kích thước) | Chưa có | Chưa có | Chưa chạy | Chưa đo | Chưa đo | Không áp dụng |
| 5 | Thể thao (hiệp, lần, nghỉ) | Chưa có | Chưa có | Chưa chạy | Chưa đo | Chưa đo | Không áp dụng |
| 6 | Làm đẹp (lượng sản phẩm) | Chưa có | Chưa có | Chưa chạy | Chưa đo | Chưa đo | Không áp dụng |
| 7 | Không phải tutorial: vlog | Chưa có | Chưa có | Chưa chạy | Không áp dụng | Không áp dụng | Chưa đo |
| 8 | Không phải tutorial: review | Chưa có | Chưa có | Chưa chạy | Không áp dụng | Không áp dụng | Chưa đo |

Ngưỡng khởi điểm theo spec mục 5.2 (người dùng có thể chỉnh, nhưng không chỉnh sau khi đã xem kết quả để coi là đạt):

- Tổng hợp trên 6 video tutorial: >= 95% mục mang `verified` đúng với đáp án.
- 2/2 video không phải tutorial bị chặn ở đoạn 1.
- 0 định lượng hoặc thông số sai nào mang `verified`.

Tổng hợp: chưa có, vì chưa có lượt chạy nào.

## Bảng báo cáo thêm (chưa đặt ngưỡng)

| # | Tỉ lệ mục đúng bị `unverified` (`verified_false_negative_rate`) | Độ phủ bước (`step_coverage`) | Thời gian ASR / OCR | Chi phí Gemini | Cần sửa |
| --- | --- | --- | --- | --- | --- |
| 1 | Chưa đo | Chưa đo | Chưa đo | Chưa đo | |
| 2 | Chưa đo | Chưa đo | Chưa đo | Chưa đo | |
| 3 | Chưa đo | Chưa đo | Chưa đo | Chưa đo | |
| 4 | Chưa đo | Chưa đo | Chưa đo | Chưa đo | |
| 5 | Chưa đo | Chưa đo | Chưa đo | Chưa đo | |
| 6 | Chưa đo | Chưa đo | Chưa đo | Chưa đo | |
| 7 | Không áp dụng | Không áp dụng | Chưa đo | Chưa đo | |
| 8 | Không áp dụng | Không áp dụng | Chưa đo | Chưa đo | |

## Trước khi chạy cần biết

- Luật số lân cận 8 token và các luật còn lại của bộ khớp (`docs/decisions.md`, mục 26 đến 42) làm một số định lượng đúng bị `unverified`; cột "mục đúng bị `unverified`" có mặt để đo đúng cái giá đó, chưa có ngưỡng.
- Chưa có chỗ hở đã biết nào cho "sai mang ✓" sau mục 37–42; nếu cột "sai mang ✓" không đạt, ghi nguyên số, không chỉnh ngưỡng. Các luật 37–42 thêm cái giá về recall (thứ tự "fifth", "point"/"chấm" đứng trước số, câu nhận định khác ngôn ngữ với đơn vị ngoài bảng, chữ tiếng Việt trên màn hình phải trùng từng từ, "nữa" trên OCR, "media").
- Probe schema v2 với Gemini bằng request text-only chưa chạy; lượt gửi video đầu tiên cũng là lần đầu xác nhận Google chấp nhận schema.
- Phép chấm khớp tên và số, và ghép bước bằng `token_set_ratio`, có sai số riêng (`fixtures/eval/README.md`).

Không đạt thì sửa prompt/policy/bộ khớp rồi đo lại, không chỉnh báo cáo hoặc ngưỡng để coi là đạt.
