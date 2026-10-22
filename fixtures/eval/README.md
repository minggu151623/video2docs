# Bộ đánh giá nhiều lĩnh vực: định dạng đáp án

Thư mục này mô tả cách ghi đáp án và chấm bằng `scripts/evaluate.py`. Chưa có video hay đáp án thật nào trong repo, và bộ 8 video chưa được chạy (xem `docs/evaluation-template.md`). Video riêng tư, raw output của provider và đáp án gắn với video có quyền sử dụng không đưa vào Git.

Người chấm ghi đáp án **trước** khi xem output của app, theo từng video, ra một file JSON:

```json
{
  "is_tutorial": true,
  "steps": [{ "title": "Trộn bột với đường", "start_sec": 48 }],
  "materials": [{ "name": "Bột mì", "quantity": "200", "unit": "g" }],
  "parameters": [{ "step_index": 1, "name": "Nhiệt độ", "value": "180", "unit": "°C" }],
  "warnings": ["Cẩn thận, khay rất nóng"],
  "claims": [{ "text": "Để bột nghỉ 30 phút", "numbers": ["30"] }],
  "exact_inputs": ["npm run build"]
}
```

- `is_tutorial`: `false` cho video không phải how-to (vlog, review); khi đó các danh sách còn lại để rỗng.
- `steps`: các bước theo thứ tự trong video; `start_sec` là giây từ đầu video, không phải `MM:SS`. Viết `title` bằng ngôn ngữ của tài liệu cần chấm.
- `materials`: `quantity` là chuỗi đúng như video nói hoặc hiện (`"1/2"`, `"1,5"`), `null` nếu video không nêu số lượng; `unit` ghi đúng đơn vị video dùng, hoặc `null`.
- `parameters`: `step_index` là chỉ số (từ 0) của bước trong chính danh sách `steps` của đáp án, không phải trong output.
- `warnings`: câu cảnh báo, gồm cả cảnh báo chung của cả tutorial.
- `claims` (tùy chọn): các câu có con số khác (mẹo, điều kiện, khắc phục sự cố), mỗi câu kèm `numbers` là danh sách con số đúng như video nói hoặc hiện.
- `exact_inputs` (tùy chọn): lệnh, code hoặc chữ phải gõ đúng nguyên văn, mỗi mục một chuỗi.

## Chạy

```sh
uv run python scripts/evaluate.py --generation-dir data/projects/<project_id>/generations/<generation_id> --annotation <đáp án>.json
uv run python scripts/evaluate.py --blocked-by-gate --annotation <đáp án>.json
```

`--generation-dir` là thư mục generation, cần `draft.json`; `verification.json` đọc nếu có (thiếu thì mọi mục coi như chưa kiểm chứng). Video bị chặn ở đoạn 1 không có generation, nên dùng `--blocked-by-gate`: chỉ chấm `not_tutorial_correct`, các chỉ số khác là `null`. Script in JSON ra stdout, thoát mã 0, không gọi mạng và không tự kết luận đạt hay không đạt. Chấm trên `draft.json` của generation, không chấm trên Markdown đã sửa tay.

## Quy tắc khớp

- Vật liệu khớp đáp án khi `rapidfuzz.fuzz.token_set_ratio` giữa hai tên đã `normalize` (NFKC, hạ chữ thường, gộp khoảng trắng; giữ dấu tiếng Việt) đạt từ 80 trở lên, nên "Bột mì" ghép được với "Bột mì đa dụng". Thông số khớp khi tên khớp theo cùng cách và nằm trong bước của output đã được ghép với `step_index` đó (quy tắc ghép bước bên dưới); đáp án có bước không ghép được thì thông số của nó không khớp mục nào.
- Giá trị khớp khi các số nguyên vẹn bằng nhau theo `number_tokens` của bộ khớp (số đọc bằng chữ được đổi sang chữ số; `1,5` bằng `1.5`; `1/2` khác `1 2`; `2-3` là một khoảng, khác `2` và `3`). Nếu đáp án có `unit` thì đơn vị cũng phải bằng nhau sau `normalize`; `g` và `gram` là hai đơn vị khác nhau, nên ghi đáp án đúng chữ video dùng. Đáp án thiếu `unit` thì không so đơn vị.
- Cảnh báo (mục `warnings` của bước và mục `safety`) khớp đáp án khi `token_set_ratio` giữa hai chuỗi đã `normalize` đạt từ 60 trở lên; nếu cảnh báo hoặc câu đáp án có số thì tập số (`number_tokens`) của hai bên phải bằng nhau, khác thì tính là định lượng sai.
- Mục có số trong `tips`, `prerequisites`, `troubleshooting` (và cảnh báo có số) còn được so với `claims` của đáp án: cùng nội dung theo ngưỡng 60 và cùng tập số với `numbers` thì đúng; cùng nội dung mà khác số thì là định lượng sai. Mục không có số ở ba loại trên không được chấm.
- `exact_inputs` đúng khi bằng một mục `exact_inputs` của đáp án sau khi bỏ khoảng trắng (phân biệt hoa/thường); gần giống (`token_set_ratio` ≥ 80) mà không bằng thì là lệnh sai.
- Bước: một bước đáp án được tính là có mặt khi có bước của output chưa dùng cho bước đáp án khác, với `start_sec` lệch không quá 10 giây và `token_set_ratio` giữa hai tiêu đề đã `normalize` đạt từ 60 trở lên (chọn bước điểm cao nhất, duyệt theo thứ tự đáp án). Mỗi bước output chỉ phục vụ một bước đáp án.

## Chỉ số

Các mục được chấm: `materials`, `parameters`, `warnings` (bước), `safety`, mọi `exact_inputs`, và các mục có số trong `tips`, `prerequisites`, `troubleshooting`. Mục `verified` được chấm mà không ghép được với đáp án nào vẫn kéo `verified_precision` xuống và được liệt kê trong `verified_unmatched` để người chấm xem bằng mắt (có thể là ✓ sai mà đáp án không nhắc tới).

| Chỉ số | Định nghĩa | Ngưỡng của spec |
| --- | --- | --- |
| `verified_precision` | mục `verified` khớp một mục đáp án (cùng tên và giá trị; cảnh báo cùng nội dung) / mọi mục `verified`; `null` khi không mục nào `verified` | >= 95% |
| `wrong_verified_quantities` | số mục `verified` thuộc `materials` hoặc `parameters` có tên khớp đáp án nhưng giá trị hoặc đơn vị khác, cộng các câu có số khớp nội dung đáp án nhưng khác số | 0 |
| `wrong_verified_exact_inputs` | số `exact_inputs` `verified` gần giống một lệnh đáp án nhưng không bằng | 0 |
| `verified_unmatched` | `{"count", "paths"}`: các mục `verified` được chấm mà không ghép được với đáp án nào | xem bằng mắt |
| `verified_false_negative_rate` | định lượng đáp án có mặt đúng trong output mà mục đó không `verified` / số định lượng đáp án có mặt đúng; `null` khi không có | báo cáo, chưa đặt ngưỡng |
| `step_coverage` | số bước đáp án ghép được / số bước đáp án; `null` khi đáp án không có bước | báo cáo, chưa đặt ngưỡng |
| `not_tutorial_correct` | `is_tutorial` của output bằng của đáp án (với `--blocked-by-gate`: đáp án phải là `false`) | 2/2 video không phải tutorial bị chặn |

"Định lượng đáp án" là mỗi `materials` có `quantity` khác rỗng và mỗi `parameters`. JSON còn có `counts` (tử số và mẫu số của các tỉ lệ trên) để đối chiếu bằng tay.

## Giới hạn của cách chấm

- Chỉ chấm theo tên và số. Thông số chỉ được xét trong bước đã ghép được, nên một bước bị bỏ sót hoặc lệch giờ quá 10 giây làm các thông số của nó không khớp mục nào (kéo `verified_precision` xuống và nằm trong `verified_unmatched` nếu chúng `verified`, và không tính vào tỉ lệ âm tính giả).
- Ghép tên bằng `token_set_ratio` ≥ 80 nên tên này chứa trọn tên kia là ghép được ("Bột" với "Bột mì"); hai vật liệu khác nhau có chung từ có thể bị ghép nhầm, nên `wrong_verified_quantities` cần được xem lại bằng mắt.
- Khớp tiêu đề bước và cảnh báo bằng `token_set_ratio` có thể ghép nhầm hai câu dùng chung nhiều từ, hoặc bỏ sót câu diễn đạt khác hẳn. Với số mục nhỏ của một video, nên đọc `counts` và xem lại bằng mắt các mục `unverified`.
- Script không biết lỗi nằm ở đáp án hay output; mọi chênh lệch cần được người chấm xem lại trước khi ghi vào báo cáo.
