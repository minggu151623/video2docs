# Báo cáo kiểm chứng

Ngày: 20/10/2026, Asia/Ho_Chi_Minh. Trạng thái bàn giao: triển khai luồng local, đã kiểm thử mock; **chưa nghiệm thu MVP bằng Gemini/video thật**.

## Môi trường và kết quả thật

| Hạng mục | Kết quả |
| --- | --- |
| Python | 3.12.13, uv.lock |
| Node | 25.8.1; frontend yêu cầu >=22.12, đề xuất LTS 24 |
| SDK | google-genai 2.31.0 |
| Backend | FastAPI 0.150.0, SQLAlchemy 2.1.5, Alembic 1.20.0, Pydantic 2.14.1 |
| Browser/PDF | Playwright 1.64.0 + Chromium ARM64 đã cài |
| Media | FFmpeg/ffprobe 8.1, có libx264 và libvpx-vp9 |
| `uv run pytest -q` | **66 passed**, 22,89 giây ở lượt cuối |
| Ruff | `uv run ruff check --select F backend scripts tests/e2e`: pass |
| Frontend | `npm --prefix frontend run build`: TypeScript + Vite 8.3.4 pass |
| E2E | 16 nhóm kiểm tra pass trên API + worker riêng + frontend build thật; dữ liệu mock |
| Browser error | `pageerror=[]` trong luồng được kiểm tra |
| Responsive | 1440×1000 và 375×900, không tràn ngang trong trạng thái workspace |
| Contrast | 10 cặp chữ/nền đã đo, thấp nhất 4,79:1; xem contrast.txt |
| PDF | File thật đọc bằng pypdf; render trực quan PDF 2 trang từ app và fixture layout 4 trang |
| M0 live | **Pending: không có GEMINI_API_KEY**, chưa có request Google thật |
| Rubric chất lượng | **Chưa chạy**, thiếu 5 tutorial thật/annotation và key/quota |

Một warning không làm fail test: Starlette TestClient hiện khuyến cáo httpx2 thay httpx. Không có warning này trong runtime HTTP thông thường. Chưa nâng chỉ để che warning của test dependency.

Spec gốc được giữ nguyên; SHA-256 hiện tại: `103db58450b04e6884bb78dcced3b3061372288812046e789321c3ebc4e343f8`.

## Phạm vi backend đã kiểm tra

- Chunk planner 0/1/299/300/301/1200 giây; schema NaN/Infinity/field lạ/out-of-range/EOF/review reason; code partial được review.
- FFmpeg thật: upload, probe, playback, thumbnail, frame, source hash bất biến; MP4/MOV/WebM; range 206 và 416.
- Clip tổng hợp 305 giây: chunk 0–300 và 295–305, timestamp toàn cục xuất hiện 295 giây. Clip 1201 giây bị từ chối trước AI. Các clip này chỉ xác nhận pipeline kỹ thuật.
- Assembly bỏ trùng chính xác khi khoảng thời gian có overlap thật; giữ trường hợp gần giống và đánh dấu review; không cắt bỏ step khi vượt limit.
- Gemini adapter dùng SDK model thật để validate request static/schema/output cap/store=false/no tools. Mock tests cho ACTIVE/FAILED/expired/deadline, 403/429/5xx/timeout, truncation. Không được hiểu như live integration.
- Usage unknown giữ null; thinking/output chuẩn hóa đúng một lần theo contract; giá hết hạn không dùng; attempts/soft budget có cap.
- Consent hash/notice, idempotency cùng key/cùng body và 409 khác body, ngăn analysis trùng.
- Claim hai worker, expired lease, outcome unknown không tự gửi lại, retry chủ động tái dùng validated checkpoint. Process recovery chỉ kill FFmpeg thuộc project và đúng hash danh tính process.
- Hủy queued và trong encode; tombstone chặn thao tác mới; xóa local không bị worker tạo lại.
- Revision conflict 409, restore giữ lịch sử, regeneration giữ bản sửa; chọn lại frame tạo revision.
- MD/ZIP/PDF theo revision cũ dù editor đã lưu bản mới; ZIP integrity, manifest, ảnh đủ; thiếu ảnh/remote image lỗi rõ; thiếu Chromium không mất Markdown.
- CSRF/cookie/Origin/Host, traversal/symlink, filename có ký tự shell, Markdown HTML/script/remote image; upload quá lớn cả Content-Length lẫn stream chunked; low disk dọn partial.
- Remote cleanup fail rồi retry thành công qua fake provider; pending flag độc lập nội dung. Không có bằng chứng xóa file Google thật vì chưa upload thật.

## E2E chạy trên ứng dụng thật với fake provider

Lệnh: `E2E_WORKER_PID=<PID worker mock do bộ kiểm thử khởi động> uv run python tests/e2e/browser_flow.py`.

Biến PID chỉ dùng trong môi trường mock cô lập: test tạm SIGSTOP worker của chính nó để kiểm tra nút hủy queued một cách xác định, rồi SIGCONT trong finally. Không dùng PID của process khác. Chạy script không có biến này vẫn kiểm tra luồng chính nhưng bỏ nhóm hủy/thử lại UI; integration test vẫn kiểm tra hủy.

Kết quả chi tiết: [browser-results.json](verification/browser-results.json).

Các nhóm pass: tạo dự án/upload/playback; consent trước analysis; reload; seek/ảnh/Escape; preview/autosave; conflict hai tab + sao chép local/tải bản đã lưu; restore; bật/tắt editor/preview; download MD/ZIP/PDF thật; chọn frame; đổi tên; mobile/focus; metadata check chủ động; generation tách bản sửa và áp dụng có chọn; hủy và retry UI; XSS/remote-image error; xác nhận xóa; không JS exception.

Ảnh giao diện là **MOCK**, không phải tài liệu Gemini đã phân tích:

- [Workspace desktop](verification/workspace-desktop.png)
- [Workspace 375 px](verification/workspace-mobile.png)
- [Empty state](verification/empty-desktop.png)

## PDF QA

`scripts/pdf_layout_check.py` tạo [fixture PDF 4 trang](verification/pdf-layout.pdf): tiếng Việt, command dài không khoảng trắng, bảng 45 dòng, ảnh và caption. Đã render và xem đủ 4 trang: header bảng lặp, code wrap, không có chữ bị cắt, ảnh/caption cùng trang. PDF app 2 trang cũng đã render cả hai trang; font tiếng Việt đọc được, ảnh nguồn thật, không placeholder bằng chứng.

Mã PDF chặn network và JS; chỉ nhận ảnh allowlist đã kiểm hash và font local. Timeout subprocess 60 giây. Đây không phải chứng nhận khả năng in hoàn hảo cho mọi Markdown người dùng có thể nhập; tài liệu đặc biệt vẫn cần người dùng xem PDF trước khi chia sẻ.

## Mốc và checklist nghiệm thu

| Gate của đặc tả | Trạng thái/bằng chứng |
| --- | --- |
| M0 khung/build/health/SDK lock | Pass; live spike pending vì thiếu key |
| M1 upload/local/session/Range/consent | Pass trên fixture và tests |
| M2 worker/chunk/checkpoint/cancel/cleanup | Pass mock + media thật; live file states/usage chưa đo |
| M3 editor/revision/generation/evidence | Pass backend + browser |
| M4 MD/ZIP/PDF/local delete | Pass trên revision/fixture đã kiểm tra |
| M5 build/test/E2E/README | Pass phần local; chưa nghiệm thu nội dung AI |
| Năm video rubric >=90%, không command bịa | Chưa có dữ liệu, không gắn nhãn đạt |
| Thử làm theo hai tài liệu | Chưa chạy |

Các ranh giới còn cần kiểm chứng khi có key/video: quyền model của tài khoản, Files/Interactions thật, quota/billing tier, usage và cleanup thật, chất lượng nhận bước/code, rotation/VFR phức tạp trên video người dùng, và rubric thủ công. Script `provider_smoke.py` có opt-in upload/chi phí để chạy bước live; `evaluation-template.md` là mẫu chấm thật.

## Anti Slop Delivery Gate

Design Read và lý do thiết kế ở `design.md`. Người dùng chọn during + giao diện sáng như trình soạn tài liệu. ENERGY 1 / RHYTHM 2 / MOTION 1.

| Rule/check | Status và bằng chứng |
| --- | --- |
| R-02 | PASS: UI/code sản phẩm không có em dash trang trí; spec nguồn không sửa |
| R-03 | PASS: browser assert scrollWidth <= innerWidth ở 375 px; ảnh mobile đã xem |
| R-17 | PASS: số dự án, duration, byte, job/chunk lấy từ API; không số khách hàng/uptime giả |
| R-18 | PASS: không testimonial/avatar khách hàng |
| R-23 | PASS: không ảnh/logo khách hàng; chỉ typographic title, ảnh video và fixture tổng hợp có nhãn |
| R-24 | PASS: project nav, terms, download đều có đích thật |
| R-25 | PASS: 10 cặp palette đo >=4,5:1; tối thiểu 4,79:1, contrast.txt |
| R-26 | PASS: controls có handler/API/native behavior; click-through UI và error states được ghi |
| R-27 | PASS: empty/upload/queued/error/conflict/export-failure/cleanup-pending có thông báo và hành động |
| R-28 | PASS: không FAQ chèn thêm |
| R-32 | PASS: label form, focus-visible toàn cục; Tab và native dialog Escape được kiểm tra |
| R-33 | PASS: tính năng viết trong source; formatter chỉ định dạng code |
| R-34 | PASS: một theme sáng được người dùng chọn, không toggle thiếu chức năng |
| R-35 | PASS: TypeScript/Vite build, browser clicks, file downloads thật và 66 backend tests |
| R-36 | PASS: không security/compliance/performance claim giả; mock/live phân biệt |
| R-37 | PASS: có lựa chọn hướng thiết kế rõ từ người dùng trước khi dựng UI |
| R-38 | PASS: nội dung kiểm thử ghi MOCK và banner; không giả lập như kết quả AI thật |
| R-01 | PASS: không gradient/glow trang trí |
| R-04 | PASS: không bộ icon generic; chữ/timestamp phục vụ tác vụ |
| R-06 | PASS: system font cho Việt ngữ, Georgia cho trang tài liệu, monospace chỉ Markdown/code/time |
| R-07 | PASS: không background grid/dot pattern |
| R-08 | PASS: không mũi tên trang trí trên buttons |
| R-09 | PASS: không badge marketing |
| R-10 | PASS: không glassmorphism |
| R-12 | PASS: shadow nhẹ duy nhất ở document sheet, phân lớp vùng đọc |
| R-13 | PASS: không glow |
| R-14 | PASS: không feature-card grid; project list/source/document theo dữ liệu |
| R-19 | PASS: không animation nền/loop; native progress thể hiện upload thật |
| R-22 | PASS: không stock illustration |
| Liveliness dials | PASS: 1/2/1, màn nguồn/tài liệu có nhịp và độ ưu tiên tương ứng |
| Focal point | PASS: form upload ở empty state; document sheet ở workspace |
| Whitespace | PASS: tách metadata, bước, editor, export; đã xem desktop/mobile |
| Accent/motif | PASS: xanh trầm ở action chính/time; 01/02 + timestamp lặp theo công việc |
| C-1 | PASS: palette/type/layout có lý do trong design.md |
| C-2 | PASS: controls có luồng thật; provider chưa có key được disable và giải thích |
| C-3 | PASS: không marketing/stats/feed giả; chỉ thư viện, source, document, history/export |
| C-4 | PASS: desktop/375px, reload, loading/error/conflict, keyboard/dialog đã chạy |
| C-5 | PASS: ảnh FFmpeg có hash/time; mock không nhận là quality result |
| R-05 | PASS: cấu trúc phục vụ so sánh video/tài liệu, không hero/cards/pricing template |
| R-11 | PASS: input/button radius nhỏ; video/document/dialog có vai trò riêng |
| R-15 | PASS: CTA cụ thể Lưu video/Tạo tài liệu/Xuất/Khôi phục |
| R-16 | PASS: không buzzword marketing |
| R-20 | PASS: timestamp/source/evidence/revision là nội dung và tương tác của công cụ này |
| R-21 | PASS: theme sáng đúng lựa chọn người dùng |
| R-29 | PASS: nền giấy/xanh xám, một accent xanh trầm, màu cảnh báo có chức năng |
| R-30 | PASS: không clone brand khác |
| R-31 | PASS: lý do từng quyết định lớn ghi design.md |

Gate giao diện PASS trong phạm vi local/mock đã kiểm tra. Gate nghiệm thu chất lượng AI vẫn pending như bảng phía trên.

## Cập nhật live sau khi người dùng cung cấp key/video

Xem [báo cáo live cập nhật ngày 21/10/2026](live-verification.md). Key/model và smoke 25 giây Gemini 3.8 đã pass thật. Sau khi người dùng yêu cầu đổi sang Gemini 3.1 Flash Lite và bổ sung chỉ dẫn timestamp, toàn video 216,642177 giây đã qua pipeline: 7 bước, 7 ảnh, MD/ZIP/PDF 8 trang, cleanup pending 0. PDF đã xem đủ 8 trang; browser hiển thị model/tài liệu, không JS exception. **72 tests pass**, Ruff pass. Nội dung vẫn cần rà soát: ngữ cảnh giữa các đoạn và phần xử lý lỗi PATH còn suy diễn. Chưa đạt nghiệm thu chất lượng bộ 5 tutorial. Các số 66/71 tests và trạng thái thiếu key phía trên là bản ghi lịch sử.

Cập nhật sau yêu cầu cải tiến: **84 tests pass** trong 29,78 giây, Ruff và frontend production build pass. Live contract v7 hoàn tất sau retry checkpoint: 10 bước, 10 ảnh, PDF 11 trang đã xem đủ, MD/ZIP khớp revision, không JS exception và cleanup pending 0. Đã cải thiện scope, loại PATH suy diễn khỏi hướng dẫn và ảnh kết quả; timestamp/thứ tự một số bước cấu hình vẫn cần sửa thủ công. Xem [đối chiếu trước/sau và các giới hạn](quality-improvements.md).
