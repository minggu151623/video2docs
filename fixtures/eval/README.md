# Bộ đánh giá nhiều lĩnh vực: định dạng đáp án

Thư mục này mô tả cách ghi đáp án và chấm bằng `scripts/evaluate.py`. Chưa có video hay đáp án thật nào trong repo, và bộ 8 video chưa được chạy (xem `docs/evaluation-template.md`). Video riêng tư, raw output của provider và đáp án gắn với video có quyền sử dụng không đưa vào Git.

Người chấm ghi đáp án **trước** khi xem output của app, theo từng video, ra một file JSON:

```json
{
  "is_tutorial": true,
  "steps": [{ "title": "Trộn bột với đường", "start_sec": 48 }],
  "materials": [{ "name": "Bột mì", "quantity": "200", "unit": "g" }],
  "parameters": [{ "step_index": 1, "name": "Nhiệt độ", "value": "180", "unit": "°C" }],
  "warnings": ["Cẩn thận, khay rất nóng"]
}
```

- `is_tutorial`: `false` cho video không phải how-to (vlog, review); khi đó các danh sách còn lại để rỗng.
- `steps`: các bước theo thứ tự trong video; `start_sec` là giây từ đầu video, không phải `MM:SS`. Viết `title` bằng ngôn ngữ của tài liệu cần chấm.
- `materials`: `quantity` là chuỗi đúng như video nói hoặc hiện (`"1/2"`, `"1,5"`), `null` nếu video không nêu số lượng; `unit` ghi đúng đơn vị video dùng, hoặc `null`.
- `parameters`: `step_index` là chỉ số (từ 0) của bước trong chính danh sách `steps` của đáp án, không phải trong output.
- `warnings`: câu cảnh báo, gồm cả cảnh báo chung của cả tutorial.

## Chạy

```sh
uv run python scripts/evaluate.py --generation-dir data/projects/<project_id>/generations/<generation_id> --annotation <đáp án>.json
uv run python scripts/evaluate.py --blocked-by-gate --annotation <đáp án>.json
```

`--generation-dir` là thư mục generation, cần `draft.json`; `verification.json` đọc nếu có (thiếu thì mọi mục coi như chưa kiểm chứng). Video bị chặn ở đoạn 1 không có generation, nên dùng `--blocked-by-gate`: chỉ chấm `not_tutorial_correct`, các chỉ số khác là `null`. Script in JSON ra stdout, thoát mã 0, không gọi mạng và không tự kết luận đạt hay không đạt. Chấm trên `draft.json` của generation, không chấm trên Markdown đã sửa tay.

## Quy tắc khớp

- Vật liệu khớp đáp án khi `normalize(name)` bằng nhau (NFKC, hạ chữ thường, gộp khoảng trắng; giữ dấu tiếng Việt). Thông số khớp khi cùng tên và nằm trong bước của output đã được ghép với `step_index` đó (quy tắc ghép bước bên dưới); đáp án có bước không ghép được thì thông số của nó không khớp mục nào.
- Giá trị khớp khi các số nguyên vẹn bằng nhau theo `number_tokens` của bộ khớp (số đọc bằng chữ được đổi sang chữ số; `1,5` bằng `1.5`; `1/2` khác `1 2`; `2-3` là một khoảng, khác `2` và `3`). Nếu đáp án có `unit` thì đơn vị cũng phải bằng nhau sau `normalize`; `g` và `gram` là hai đơn vị khác nhau, nên ghi đáp án đúng chữ video dùng. Đáp án thiếu `unit` thì không so đơn vị.
- Cảnh báo (mục `warnings` của bước và mục `safety`) khớp đáp án khi `rapidfuzz.fuzz.token_set_ratio` giữa hai chuỗi đã `normalize` đạt từ 60 trở lên.
- Bước: một bước đáp án được tính là có mặt khi có bước của output chưa dùng cho bước đáp án khác, với `start_sec` lệch không quá 10 giây và `token_set_ratio` giữa hai tiêu đề đã `normalize` đạt từ 60 trở lên (chọn bước điểm cao nhất, duyệt theo thứ tự đáp án). Mỗi bước output chỉ phục vụ một bước đáp án.

## Chỉ số

Chỉ tính bốn loại mục có đáp án: `materials`, `parameters`, `warnings` (bước) và `safety`. `exact_inputs`, `tips`, `prerequisites`, `troubleshooting` không có đáp án nên không nằm trong các chỉ số dưới đây; mục `verified` thuộc bốn loại trên mà không khớp đáp án nào vẫn kéo `verified_precision` xuống, nhưng không tính là định lượng sai.

| Chỉ số | Định nghĩa | Ngưỡng của spec |
| --- | --- | --- |
| `verified_precision` | mục `verified` khớp một mục đáp án (cùng tên và giá trị; cảnh báo cùng nội dung) / mọi mục `verified`; `null` khi không mục nào `verified` | >= 95% |
| `wrong_verified_quantities` | số mục `verified` thuộc `materials` hoặc `parameters` có tên trùng đáp án nhưng giá trị hoặc đơn vị khác | 0 |
| `verified_false_negative_rate` | định lượng đáp án có mặt đúng trong output mà mục đó không `verified` / số định lượng đáp án có mặt đúng; `null` khi không có | báo cáo, chưa đặt ngưỡng |
| `step_coverage` | số bước đáp án ghép được / số bước đáp án; `null` khi đáp án không có bước | báo cáo, chưa đặt ngưỡng |
| `not_tutorial_correct` | `is_tutorial` của output bằng của đáp án (với `--blocked-by-gate`: đáp án phải là `false`) | 2/2 video không phải tutorial bị chặn |

"Định lượng đáp án" là mỗi `materials` có `quantity` khác rỗng và mỗi `parameters`. JSON còn có `counts` (tử số và mẫu số của các tỉ lệ trên) để đối chiếu bằng tay.

## Giới hạn của cách chấm

- Chỉ chấm theo tên và số. Thông số chỉ được xét trong bước đã ghép được, nên một bước bị bỏ sót hoặc lệch giờ quá 10 giây làm các thông số của nó không khớp mục nào (kéo `verified_precision` xuống nếu chúng `verified`, và không tính vào tỉ lệ âm tính giả).
- Khớp tiêu đề bước và cảnh báo bằng `token_set_ratio` có thể ghép nhầm hai câu dùng chung nhiều từ, hoặc bỏ sót câu diễn đạt khác hẳn. Với số mục nhỏ của một video, nên đọc `counts` và xem lại bằng mắt các mục `unverified`.
- Script không biết lỗi nằm ở đáp án hay output; mọi chênh lệch cần được người chấm xem lại trước khi ghi vào báo cáo.
