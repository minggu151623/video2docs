# Video2docs

Ứng dụng local chuyển video hướng dẫn (how-to) thuộc mọi lĩnh vực, từ phần mềm, nấu ăn, sửa chữa đến thể thao, thành bản nháp tài liệu có timestamp, ảnh bằng chứng và trạng thái kiểm chứng từng mục. Theo `PROJECT_SPEC.md` và `docs/superpowers/specs/2026-10-22-general-tutorials-design.md`; giao diện tiếng Việt, tài liệu có thể chọn tiếng Việt hoặc tiếng Anh.

**Trạng thái:** 24/10/2026: schema v2 được Google chấp nhận; chạy thật toàn video Python pass (11 bước, 237 s gồm ASR/OCR), nhưng kiểm chứng mới cho 2 ✓/6 mục và 1 ✓ sai nghĩa — xem `docs/live-verification.md`; sau đó bỏ dấu nhắc Windows/Python trên hàng OCR và thêm trạng thái `quote_matched` cho câu diễn giải chưa kiểm chứng (`docs/decisions.md` mục 47–48, chưa chạy lại live).  ngày 22/10/2026 mở rộng từ tutorial phần mềm sang mọi video how-to: schema v2 (vật liệu, thông số, cảnh báo, lệnh/văn bản nguyên văn), chặn video không phải tutorial ở đoạn đầu, và kiểm chứng độc lập các trích dẫn bằng ASR (faster-whisper) và OCR (PaddleOCR) chạy local; contract provider v9. 1093 tests pass (`uv run pytest -q`, 3 test `slow` chạy engine thật nằm ngoài lượt mặc định) và frontend build pass. **Chưa chạy bộ đánh giá 8 video nhiều lĩnh vực** (`docs/evaluation-template.md`): chưa có số đo độ chính xác của kiểm chứng, tỉ lệ chặn video không phải tutorial hay tỉ lệ mục đúng bị bỏ sót, và chưa kiểm tra Google chấp nhận schema v2 bằng request thật. Bộ khớp ưu tiên không để định lượng sai mang dấu ✓, nên có thể bỏ sót mục đúng (các luật và cái giá về recall ở `docs/decisions.md` mục 26–48). Lịch sử trước đó (contract `MM:SS` v8, lượt live trên một video cài Python, cải tiến ngữ cảnh giữa các đoạn) ở `docs/quality-improvements.md`, `docs/live-verification.md` và `docs/validation.md`; các lượt live này dùng schema v1 và chưa phải nghiệm thu chất lượng.

## Cài và chạy trên macOS Apple Silicon

Cần `uv`, Node.js LTS 24 (>=22.12), npm và FFmpeg/ffprobe. Môi trường đã chạy kiểm thử: Python 3.12.13, Node 25.8.1. Dependency Python/JS được khóa bằng `uv.lock` và `frontend/package-lock.json`. Font DejaVu Sans hỗ trợ tiếng Việt được đóng gói kèm license.

`./scripts/setup.sh` (`uv sync --locked`) cài cả engine kiểm chứng: `faster-whisper` (ASR) và `paddleocr` + `paddlepaddle` (OCR) cộng thêm khoảng 0,9 GB vào `.venv`. Không cần gói hệ thống nào khác. Trọng số model **không** nằm trong repo: lần chạy kiểm chứng đầu tiên cần mạng để tải (faster-whisper `small` khoảng 0,5 GB từ Hugging Face; model OCR mobile phát hiện chữ + nhận dạng tiếng Anh/Hàn khoảng 25 MB từ nguồn của PaddleX về `~/.paddlex`), các lần sau dùng bản đã tải. Chỉ tải trọng số, không gửi video, âm thanh hay khung hình đi đâu. Ước lượng kích thước theo số đo spike và tài liệu của engine, chưa kiểm lại trên máy sạch. Có thể bỏ qua hai engine bằng `ASR_ENGINE=none OCR_ENGINE=none`; khi đó mọi mục cần đối chiếu là `not_checked` và tài liệu mang `needs_review`.

```sh
brew install uv node@24 ffmpeg
cp .env.example .env
./scripts/setup.sh
```

Bỏ qua lệnh `cp` nếu `.env` đã có. Điền `GEMINI_API_KEY` trong `.env` bằng editor local; không đưa key vào chat, mã frontend hoặc Git.

```sh
uv run python scripts/dev.py
```

Mở [http://127.0.0.1:5173](http://127.0.0.1:5173). Lệnh trên khởi động API, worker và Vite; Ctrl-C dừng cả ba. Worker là tiến trình riêng, không phải FastAPI BackgroundTasks. Khởi động lại API và worker khi đổi `.env`.

Có thể chạy ba terminal riêng từ thư mục gốc:

```sh
PYTHONPATH=backend uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
PYTHONPATH=backend uv run python -m app.workers.runner
npm --prefix frontend run dev
```

Để dùng frontend đã build, chạy `npm --prefix frontend run build`, sau đó chỉ cần API + worker và mở [http://127.0.0.1:8000](http://127.0.0.1:8000). Health: `/api/v1/health`; OpenAPI: `/openapi.json`; tài liệu API: `/api/docs`. Health/readiness không gọi Google.

## Sử dụng

1. Nhập tên dự án, chọn ngôn ngữ, chọn MP4/MOV/WebM rồi **Lưu video vào dự án**. Upload chỉ vào máy này. Worker kiểm tra container, thời lượng, độ phân giải, tạo playback/thumbnail; giữ nguyên nguồn và hash.
2. Đọc thông báo gửi dữ liệu và điều khoản, xác nhận video/provider. Chi phí và quota chưa đo được phải được chủ động chấp nhận; không hiển thị số lượt miễn phí giả.
3. **Tạo tài liệu**. Theo dõi giai đoạn/số đoạn/thời gian thật; có thể reload hoặc hủy. Request đã gửi tới Google có thể vẫn phát sinh phí khi hủy local.
4. Đối chiếu từng bước, click timestamp/ảnh để xem nguồn. Markdown có preview ngay, autosave khoảng 1 giây. Hai tab sửa cùng bản sẽ báo 409 và giữ bản local để sao chép.
5. Lịch sử revision cho phép khôi phục thành revision mới. Generation mới luôn lưu riêng; chọn áp dụng sau khi kiểm tra. Chọn lại ảnh theo số giây không gọi AI. Bỏ một ảnh bằng cách xóa dòng `![...](assets/...)` trong Markdown.
6. Xuất MD, ZIP hoặc PDF từ revision đã lưu. MD riêng cần ảnh đi kèm; ZIP gồm `document.md`, `assets/`, manifest revision/hash/timestamp. PDF là file A4 thật với font local. Các file đã xuất còn có thể tải từ Lịch sử xử lý sau reload.
7. Kết quả hiện nhãn lĩnh vực, dòng "N/M mục đã kiểm chứng", huy hiệu "n mục chưa kiểm chứng" trên từng bước, bộ lọc **Chỉ hiện mục chưa kiểm chứng** và nút **Kiểm chứng lại** (chạy lại ASR/OCR local, không gọi Google). Trạng thái tài liệu lấy từ generation, không phải từ job kiểm chứng. Nếu đoạn đầu không phải video hướng dẫn, job dừng ở trạng thái "Không phải tutorial" kèm lý do; **Vẫn phân tích toàn bộ** mở hộp xác nhận chi phí rồi tạo job mới bỏ qua chặn này.
8. Xóa dự án cần xác nhận; tombstone chặn thao tác mới, worker hủy job và dọn file. Cleanup Google có thể còn pending, không được diễn giải thành đã xóa remote.

## Phạm vi và cấu hình

| Mục | Mặc định |
| --- | --- |
| Phạm vi | Video how-to mọi lĩnh vực (nhãn: phần mềm, nấu ăn, sửa chữa, thủ công, thể thao, làm đẹp, làm vườn, âm nhạc, khác); video không phải tutorial bị báo rõ, không bịa bước; một người dùng localhost. Chưa có chế độ ghi chú cho bài giảng |
| Đầu vào | File local MP4/MOV/WebM, một video/dự án; chưa có connector URL |
| Provider/model | Gemini Developer API, `gemini-3.1-flash-lite` theo yêu cầu đổi model ngày 21/10/2026; đổi bằng `GEMINI_MODEL` |
| Mode | Static, `store=false`, không tools, không background của provider |
| Stack | React + TypeScript + Vite; FastAPI + SQLAlchemy/Alembic; SQLite và file local |
| Biên tập/xuất | Markdown + preview; MD/ZIP/PDF; ảnh FFmpeg; tên mục theo lĩnh vực (Nguyên liệu, Vật liệu, Sản phẩm, Tài nguyên…) |
| Kiểm chứng | ASR + OCR local đối chiếu trích dẫn của model (lời nói, chữ trên màn hình); trạng thái `verified`, `unverified`, `not_checkable`, `not_checked` ở `verification.json`; chạy lại không gọi Google. Bản ghi lời nói không gửi cho Gemini |
| Ngôn ngữ | UI tiếng Việt; output vi/en |
| Tài nguyên | 500 MiB, 1200 giây, 8.294.400 pixel/video; 5000 MiB/project |
| Worker/chunk | Một job media/AI tại một thời điểm; clip 300 giây, overlap 5 giây |
| Output | 80 bước, 40 ảnh, 60 vật liệu, 10 thông số/bước, cạnh ảnh tối đa 1920 px, không upscale |
| Budget | 12 attempts/job, tối đa 1 JSON repair/job; ngân sách mềm 1 USD |
| Timeout | Job 2700 giây; generate 300 giây; media encode 600 giây; PDF 60 giây; ASR 1200 giây; OCR 300 giây |

Đây là giới hạn thiết kế của app, không phải quota Google. Không tự suy ra subscription Google AI Pro bao gồm quota API. Không có YouTube, LLM local, lượt LLM thứ hai để kiểm chứng, agent điều khiển máy, multi-user hoặc public deployment. App không thực thi code/command trong tài liệu.

Cấu hình local hiện dùng `CHUNK_SECONDS=120`, overlap 5 giây cho video thử. Hạn mức Flash Lite do người dùng cung cấp là 15 RPM, 250.000 input TPM và 500 RPD; app chưa truy vấn quota tài khoản hay lượng đã dùng bởi các ứng dụng khác. Worker gửi các request tuần tự, không coi các số này là quota còn lại được bảo đảm.

Trong phiên kiểm tra hiện tại, `.env` dùng `APP_PORT=8002` vì cổng 8000 đang có ứng dụng khác. Frontend đã build mở tại [http://127.0.0.1:8002](http://127.0.0.1:8002); `scripts/dev.py` đọc cổng từ `.env`.

## Cấu hình

`.env.example` liệt kê toàn bộ cấu hình. Biến môi trường ghi đè file `.env`.

- `DATA_DIR` chứa cả DB và file; `DATABASE_URL` bắt buộc trỏ SQLite ngay trong root đó. Khi đổi thư mục, đổi cả hai. Không đặt root vào symlink không tin cậy.
- `APP_HOST` chỉ nhận localhost/127.0.0.1. Nếu đổi `APP_PORT`, thêm origin tương ứng vào `ALLOWED_ORIGINS`; Vite đọc `APP_PORT` cho proxy. Không hỗ trợ LAN/public bằng cấu hình hiện tại.
- `GEMINI_API_KEY` chỉ được backend/worker đọc. `GEMINI_MODEL` không fallback âm thầm; sai key/model sẽ báo lỗi.
- `CHUNK_SECONDS`, `CHUNK_OVERLAP_SECONDS`, `VIDEO_FPS`, `MAX_OUTPUT_TOKENS` và các `MAX_*` trong example điều khiển tài nguyên. Overlap phải nhỏ hơn chunk; schema v2 giới hạn tối đa 80 bước/40 ảnh.
- `ENABLE_AGENTIC_VIDEO=true`, `GEMINI_STORE_INTERACTIONS=true`, provider background, concurrency >1 và raw debug retention đều bị từ chối vì chưa triển khai.
- `AI_PROVIDER=mock` bật dữ liệu tổng hợp được ghi nhãn trong UI/tài liệu. Mặc định là `gemini`; thiếu key không tự chuyển mock.
- `ASR_ENGINE` (`faster-whisper` hoặc `none`), `ASR_MODEL` (mặc định `small`), `OCR_ENGINE` (`paddleocr` hoặc `none`), `ASR_TIMEOUT_SECONDS` (1200) và `OCR_TIMEOUT_SECONDS` (300) chọn engine đối chiếu lời thoại/chữ trên màn hình chạy local; `none` tắt engine tương ứng. Kích thước model và tải lần đầu: xem mục cài đặt. Test mặc định không tải model; test `slow` (`uv run pytest -m slow`) chạy engine thật và có thể tải model.
- `VERIFY_WINDOW_SECONDS` (5, cửa sổ đối chiếu quanh khoảng bằng chứng), `VERIFY_TEXT_THRESHOLD` (85, ngưỡng khớp gần đúng cho chữ thường, 0-100) và `VERIFY_MAX_OCR_FRAMES` (3, số khung hình OCR tối đa mỗi mục). Con số và đơn vị luôn phải khớp nguyên vẹn bất kể ngưỡng. Lệnh/code (`exact_inputs`) khớp chính xác ngoài khác biệt khoảng trắng, nên **không có** `VERIFY_INPUT_THRESHOLD`.

Giá/điều khoản được kiểm tra lại ngày **20/10/2026**. Có snapshot Standard có hiệu lực đến 31/12/2026 để đối chiếu usage sau request; không tự xác nhận tier của key hay đưa ước tính video chưa đo như hóa đơn. Usage thiếu là `null`, không phải 0. Interactions trả output/thinking riêng; adapter tính billable output đúng một lần. Ngân sách app là soft cap, không bảo đảm chặn toàn bộ hóa đơn. Xem quyết định và nguồn trong `docs/decisions.md`.

## Kiểm thử

```sh
uv sync --locked
uv run pytest -q
uv run ruff check --select F backend scripts tests/e2e
npm --prefix frontend ci
npm --prefix frontend run build
uv run python scripts/generate_fixtures.py
```

Test mặc định không cần key, không gửi Google. Integration dùng SQLite tạm, provider fake và FFmpeg/Chromium thật. Fixture tổng hợp không thay thế bộ đánh giá chất lượng. Bộ đánh giá nhiều lĩnh vực (8 video, đáp án ghi tay) chấm bằng `uv run python scripts/evaluate.py --generation-dir <thư mục generation> --annotation <đáp án>.json`; định dạng đáp án, quy tắc khớp và định nghĩa chỉ số ở `fixtures/eval/README.md`, bảng kết quả (hiện chưa có số liệu) ở `docs/evaluation-template.md`. Script chạy local, không gọi mạng.

E2E chạy riêng API và worker với cùng cấu hình mock và storage riêng:

```sh
AI_PROVIDER=mock ASR_ENGINE=none OCR_ENGINE=none DATA_DIR=./tmp/e2e-data DATABASE_URL=sqlite:///./tmp/e2e-data/app.sqlite3 ALLOWED_ORIGINS=http://127.0.0.1:8001 PYTHONPATH=backend uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
AI_PROVIDER=mock ASR_ENGINE=none OCR_ENGINE=none DATA_DIR=./tmp/e2e-data DATABASE_URL=sqlite:///./tmp/e2e-data/app.sqlite3 ALLOWED_ORIGINS=http://127.0.0.1:8001 PYTHONPATH=backend uv run python -m app.workers.runner
uv run python tests/e2e/browser_flow.py
```

`ASR_ENGINE=none OCR_ENGINE=none` giữ kiểm chứng tất định: bản nháp mock luôn hiện "0/2 mục đã kiểm chứng". Mock đọc tên file upload: `mock-two-steps*` thêm một bước không có mục cần kiểm chứng (kiểm tra bộ lọc), `mock-not-tutorial*` giả lập video không phải tutorial ở đoạn đầu. E2E tự tạo các bản copy fixture với tên đó.

Ảnh chụp, kết quả E2E và PDF QA ở `tmp/e2e-artifacts/`. Có thể tái tạo PDF bảng/code dài với `uv run python scripts/pdf_layout_check.py`.

Pydantic là schema chuẩn. Khi đổi schema, chạy `uv run python scripts/generate_schema.py` rồi `npm --prefix frontend run types`; không tự sửa TypeScript generated types.

Live smoke chủ động, có thể phát sinh phí: chạy app với Gemini/key thật, chuẩn bị clip không nhạy cảm 10–30 giây, rồi:

```sh
uv run python scripts/provider_smoke.py --video /path/to/clip.mp4 --confirm-google-upload --accept-unknown-cost
```

Báo cáo ghi `docs/live-smoke.json`, model/SDK/usage/cleanup; không ghi key. Nút **Kiểm tra kết nối** chỉ kiểm tra metadata model, không xác nhận khả năng hiểu video. Báo cáo hiện tại là lượt smoke thật đã pass (schema v1, trước khi mở rộng); bộ đánh giá 8 video nhiều lĩnh vực chưa chạy, và probe Gemini với schema v2 cần người dùng đồng ý phí.

## Backup, xóa và xử lý lỗi

Dừng API/worker trước khi backup. Sao chép toàn bộ `DATA_DIR` (gồm SQLite/WAL nếu có và các project), không chỉ file DB; giữ manifest/hash cùng artifacts. `.env` là secret riêng, không nằm trong ZIP xuất tài liệu. Khôi phục backup vào root mới rồi cập nhật hai biến data/DB và chạy setup migration. Không downgrade phá dữ liệu; giữ backup trước khi nâng schema.

Xóa dự án trong UI dọn nguồn, ảnh, generation, export và nội dung revision; giữ metadata tối thiểu cho audit/cleanup. Video và tài liệu local không được mã hóa at rest bởi ứng dụng. Kiểm tra screenshot để tránh xuất secret; prompt redact không làm sạch video gốc.

- Thiếu FFmpeg/ffprobe: `brew install ffmpeg`. Video giả hoặc vượt duration/resolution sẽ bị chặn trước AI.
- PDF dependency: `uv run playwright install chromium`. Markdown vẫn còn khi PDF lỗi. Font/license nằm ở `backend/app/static/fonts/`.
- Job queued mãi: kiểm tra worker chạy cùng `.env`, DB/storage; app báo giai đoạn queued, không giả phần trăm AI.
- Worker restart: đợi lease tối đa 60 giây. Job bị gián đoạn cần retry chủ động; checkpoint validated được tái dùng chỉ với cấu hình/hash/prompt trùng. Không tự gửi lại request ambiguous.
- 429/5xx/network: app dừng có mã lỗi; không tự retry request có nguy cơ bị tính phí trùng. Retry chủ động có xác nhận cho outcome unknown. Google Files upload gián đoạn trước khi có file name có thể cần kiểm tra AI Studio.
- Cleanup remote: thử lại tối đa 5 lần với backoff; pending vẫn hiển thị. Kiểm tra Files trong AI Studio nếu hết retries. Không khẳng định đã xóa remote khi chưa xác nhận.
- 409 revision: sao chép bản local rồi tải revision mới; không tự ghi đè.
- Full disk/storage cap: dọn dữ liệu hoặc chỉnh limit có kiểm soát, thử lại; `.partial` được dọn, nguồn không bị sửa.

Xem `docs/validation.md` để biết bằng chứng chạy, coverage và các gate chưa đủ dữ liệu nghiệm thu.
