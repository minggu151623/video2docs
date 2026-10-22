"""Run against built app + separate worker configured AI_PROVIDER=mock on port 8001.

API and worker must run with ASR_ENGINE=none OCR_ENGINE=none so verification is deterministic: the mock
draft then reports "0/2 mục đã kiểm chứng". The mock reads the uploaded file name: `mock-two-steps*` adds
a step with nothing to verify, `mock-not-tutorial*` makes the first clip a non-tutorial.
"""

import json
import os
import signal
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tmp/e2e-artifacts"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8001"
errors = []
checks = []


def copy_fixture(directory, name):
    target = Path(directory) / name
    shutil.copyfile(ROOT / "fixtures/synthetic_tutorial.mp4", target)
    return target


def checked(name):
    checks.append(name)
    print("PASS", name, flush=True)


uploads = tempfile.mkdtemp(prefix="e2e-upload-")
with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(BASE)
    expect(page.get_by_role("heading", name="Thư viện video")).to_be_visible()
    page.screenshot(path=str(OUT / "empty-desktop.png"), full_page=True)
    page.get_by_role("button", name="Tạo dự án mới", exact=True).click()
    page.get_by_label("Tên dự án", exact=True).fill("E2E: Tài liệu tiếng Việt")
    expect(page.get_by_text("Video hướng dẫn: nấu ăn, sửa chữa, phần mềm…", exact=False)).to_be_visible()
    expect(page.get_by_text("Luôn kiểm tra ảnh, định lượng và lệnh trước khi sử dụng", exact=False)).to_be_visible()
    page.get_by_label("Video nguồn").set_input_files(copy_fixture(uploads, "mock-two-steps-tutorial.mp4"))
    page.get_by_role("button", name="Lưu video vào dự án").click()
    expect(page.locator("video")).to_be_visible(timeout=30000)
    checked("create project, upload, FFmpeg validation, playback")
    expect(page.get_by_role("button", name="Tạo tài liệu", exact=True)).to_be_disabled()
    notice = page.get_by_text("Video và nội dung cần phân tích sẽ được gửi tới Google", exact=False)
    expect(notice).to_be_visible()
    page.get_by_label("Tôi đồng ý gửi video này").check()
    page.get_by_label("Tiếp tục với chi phí").check()
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/jobs") and r.status == 202
    ):
        page.get_by_role("button", name="Tạo tài liệu", exact=True).click()
    project_url = page.url
    page.reload()
    expect(page.get_by_label("Nội dung Markdown")).to_be_visible(timeout=30000)
    expect(page.get_by_label("Nội dung Markdown")).to_contain_text("MOCK")
    checked("consent gating, analysis, reload persists job and document")
    steps = page.locator(".steps .step")
    expect(page.get_by_text("Lĩnh vực: Khác", exact=True)).to_be_visible()
    expect(page.get_by_text("Trạng thái tài liệu: Cần kiểm tra", exact=True)).to_be_visible()
    expect(page.get_by_text("0/2 mục đã kiểm chứng", exact=True)).to_be_visible()
    expect(page.get_by_text("ASR không chạy · OCR không chạy", exact=True)).to_be_visible()
    expect(steps).to_have_count(2)
    expect(page.locator(".verify-badge")).to_have_count(1)
    expect(steps.first.locator(".verify-badge")).to_have_text("1 mục chưa kiểm chứng")
    checked("domain label, N/M verification summary, per-step badge")
    page.screenshot(path=str(OUT / "verification-desktop.png"), full_page=True)
    page.get_by_label("Chỉ hiện mục chưa kiểm chứng").check()
    expect(steps).to_have_count(1)
    expect(steps.first).to_contain_text("MOCK: kiểm tra frame nguồn")
    page.get_by_label("Chỉ hiện mục chưa kiểm chứng").uncheck()
    expect(steps).to_have_count(2)
    checked("unverified-only filter hides steps without unverified items")
    page.route(
        "**/api/v1/generations/*/verify",
        lambda route: route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps(
                {"error": {"code": "JOB_IN_PROGRESS", "message": "Dự án đang có một job tạo hoặc kiểm chứng tài liệu."}}
            ),
        ),
    )
    page.get_by_role("button", name="Kiểm chứng lại", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Dự án đang có một job tạo hoặc kiểm chứng tài liệu.")).to_be_visible()
    page.unroute("**/api/v1/generations/*/verify")
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/verify") and r.status == 202
    ):
        page.get_by_role("button", name="Kiểm chứng lại", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Đã kiểm chứng lại.")).to_be_visible(timeout=30000)
    expect(page.get_by_text("0/2 mục đã kiểm chứng", exact=True)).to_be_visible()
    expect(page.get_by_text("Trạng thái tài liệu: Cần kiểm tra", exact=True)).to_be_visible()
    checked("re-verify shows 409 message, then runs a verify job and reloads the generation")
    page.get_by_role("button", name="00:00:00", exact=True).first.click()
    assert page.locator("video").evaluate("(el)=>el.currentTime") == 0
    page.locator(".evidence-button").first.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).not_to_be_visible()
    checked("timestamp seek, evidence image, Escape dialog")
    editor = page.get_by_label("Nội dung Markdown")
    original = editor.input_value()
    editor.fill(original + "\n\n## Ghi chú kiểm thử\nNội dung đã chỉnh sửa tiếng Việt.\n")
    expect(page.get_by_role("status").filter(has_text="Đã lưu")).to_be_visible(timeout=10000)
    page.reload()
    expect(page.get_by_label("Nội dung Markdown")).to_have_value(
        original + "\n\n## Ghi chú kiểm thử\nNội dung đã chỉnh sửa tiếng Việt.\n", timeout=15000
    )
    checked("live preview, autosave and reload")
    other = context.new_page()
    other.on("pageerror", lambda err: errors.append(str(err)))
    other.goto(project_url)
    expect(other.get_by_label("Nội dung Markdown")).to_be_visible()
    page.get_by_label("Nội dung Markdown").fill(original + "\n\nBản tab thứ nhất.\n")
    expect(page.get_by_role("status").filter(has_text="Đã lưu")).to_be_visible(timeout=10000)
    other.get_by_label("Nội dung Markdown").fill(original + "\n\nBản local tab thứ hai.\n")
    expect(other.get_by_text("Xung đột với bản đã lưu ở tab khác.", exact=True)).to_be_visible(timeout=10000)
    assert "Bản local tab thứ hai" in other.get_by_label("Nội dung Markdown").input_value()
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    other.get_by_role("button", name="Sao chép bản local", exact=True).click()
    expect(other.get_by_role("status").filter(has_text="Đã sao chép bản local.")).to_be_visible()
    other.get_by_role("button", name="Tải bản đã lưu", exact=True).click()
    expect(other.get_by_label("Nội dung Markdown")).to_have_value(original + "\n\nBản tab thứ nhất.\n")
    other.close()
    checked("two-tab revision conflict preserves local draft")
    page.get_by_role("button", name="Lịch sử revision", exact=True).click()
    page.get_by_role("button", name="Khôi phục", exact=True).last.click()
    expect(page.get_by_role("dialog")).not_to_be_visible(timeout=10000)
    expect(page.get_by_label("Nội dung Markdown")).to_have_value(original)
    checked("restore creates a new revision")
    page.get_by_role("button", name="Markdown", exact=True).click()
    expect(page.get_by_label("Nội dung Markdown")).not_to_be_visible()
    page.get_by_role("button", name="Markdown", exact=True).click()
    page.get_by_role("button", name="Xem trước", exact=True).click()
    expect(page.locator(".prose")).not_to_be_visible()
    page.get_by_role("button", name="Xem trước", exact=True).click()
    for fmt in ("md", "zip", "pdf"):
        page.get_by_role("button", name=f"Xuất .{fmt}", exact=True).click()
        link = page.get_by_role("link", name=f"Tải .{fmt}", exact=True)
        expect(link).to_be_visible(timeout=30000)
        with page.expect_download() as event:
            link.click()
        target = OUT / ("document." + fmt)
        event.value.save_as(target)
        assert target.stat().st_size > 0
        if fmt == "zip":
            with zipfile.ZipFile(target) as z:
                assert z.testzip() is None and "document.md" in z.namelist()
        if fmt == "pdf":
            pdf = PdfReader(target)
            assert len(pdf.pages) and "Thông tin nguồn" in "".join(p.extract_text() for p in pdf.pages)
    checked("editor toggles and real MD/ZIP/PDF downloads")
    page.get_by_role("button", name="Chọn lại ảnh", exact=True).first.click()
    page.get_by_label("Timestamp (giây)", exact=True).fill("1.5")
    page.get_by_role("button", name="Xem mốc trên video", exact=True).click()
    page.get_by_role("button", name="Áp dụng ảnh vào revision mới", exact=True).click()
    expect(page.get_by_role("dialog")).not_to_be_visible()
    expect(page.get_by_label("Nội dung Markdown")).to_contain_text("Ảnh chọn lại", timeout=20000)
    checked("manual timestamp frame creates revision without LLM")
    page.get_by_role("button", name="Đổi tên", exact=True).click()
    page.get_by_label("Tên dự án", exact=True).fill("E2E đã đổi tên")
    page.get_by_role("button", name="Lưu thông tin", exact=True).click()
    expect(page.get_by_role("heading", name="E2E đã đổi tên", exact=True)).to_be_visible()
    checked("project rename")
    page.screenshot(path=str(OUT / "workspace-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 375, "height": 900})
    page.screenshot(path=str(OUT / "workspace-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement !== document.body")
    checked("375px no horizontal overflow and keyboard focus")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="Kiểm tra kết nối", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Metadata model đã phản hồi")).to_be_visible(
        timeout=15000
    )
    page.get_by_role("button", name="Đóng trạng thái", exact=True).click()
    checked("explicit provider metadata check")
    edited = page.get_by_label("Nội dung Markdown").input_value()
    page.locator(".generation-settings summary").click()
    page.get_by_label("Tôi đồng ý gửi video này").check()
    page.get_by_label("Tiếp tục với chi phí").check()
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/jobs") and r.status == 202
    ):
        page.get_by_role("button", name="Tạo generation mới", exact=True).click()
    expect(page.locator(".generations summary")).to_have_text("Các bản generation (2)", timeout=30000)
    expect(page.get_by_label("Nội dung Markdown")).to_have_value(edited)
    page.locator(".generations summary").click()
    page.get_by_role("button", name="Xem bước nguồn", exact=True).first.click()
    page.get_by_role("button", name="Áp dụng bản này", exact=True).first.click()
    expect(page.get_by_label("Nội dung Markdown")).not_to_have_value(edited, timeout=10000)
    checked("regeneration preserves edits until explicit apply")
    worker_pid = os.environ.get("E2E_WORKER_PID")
    if worker_pid:
        os.kill(int(worker_pid), signal.SIGSTOP)
        try:
            if not page.locator(".generation-settings").evaluate("(el)=>el.open"):
                page.locator(".generation-settings summary").click()
            page.get_by_label("Tôi đồng ý gửi video này").check()
            page.get_by_label("Tiếp tục với chi phí").check()
            page.get_by_role("button", name="Tạo generation mới", exact=True).click()
            page.get_by_role("button", name="Hủy job", exact=True).click(timeout=10000)
            expect(page.get_by_role("status").filter(has_text="Đã yêu cầu hủy local")).to_be_visible()
        finally:
            os.kill(int(worker_pid), signal.SIGCONT)
        if not page.locator(".job-history").evaluate("(el)=>el.open"):
            page.locator(".job-history summary").click()
        page.get_by_role("button", name="Thử lại job", exact=True).first.click()
        expect(page.locator(".generations summary")).to_have_text("Các bản generation (3)", timeout=30000)
        checked("cancel queued job and explicit retry from UI")
    saved = page.get_by_label("Nội dung Markdown").input_value()
    page.get_by_label("Nội dung Markdown").fill(
        saved + "\n\n<script>window.pwned=true</script>\n![external](https://evil.invalid/track.png)\n"
    )
    expect(page.get_by_role("status").filter(has_text="Đã lưu")).to_be_visible(timeout=10000)
    assert page.evaluate("window.pwned === undefined")
    expect(page.get_by_text("Ảnh ngoài evidence manifest bị chặn", exact=True)).to_be_visible()
    page.get_by_role("button", name="Xuất .zip", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="ảnh ngoài evidence manifest")).to_be_visible(
        timeout=15000
    )
    page.get_by_label("Nội dung Markdown").fill(saved)
    expect(page.get_by_role("status").filter(has_text="Đã lưu")).to_be_visible(timeout=10000)
    checked("Markdown XSS and external-image error state")
    page.get_by_role("button", name="Xóa dự án", exact=True).click()
    page.get_by_role("button", name="Giữ dự án", exact=True).click()
    page.get_by_role("button", name="Xóa dự án", exact=True).click()
    page.get_by_role("button", name="Xóa dữ liệu dự án", exact=True).click()
    expect(page.get_by_role("heading", name="Thư viện video", exact=True)).to_be_visible(timeout=10000)
    checked("delete confirmation and return to library")
    page.get_by_role("button", name="Tạo dự án mới", exact=True).click()
    page.get_by_label("Tên dự án", exact=True).fill("E2E: không phải tutorial")
    page.get_by_label("Video nguồn").set_input_files(copy_fixture(uploads, "mock-not-tutorial-vlog.mp4"))
    page.get_by_role("button", name="Lưu video vào dự án").click()
    expect(page.locator("video")).to_be_visible(timeout=30000)
    page.get_by_label("Tôi đồng ý gửi video này").check()
    page.get_by_label("Tiếp tục với chi phí").check()
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/jobs")) as first_request:
        page.get_by_role("button", name="Tạo tài liệu", exact=True).click()
    assert "skip_tutorial_gate" not in (first_request.value.post_data or "")
    expect(page.get_by_role("heading", name="Video này không được nhận là video hướng dẫn")).to_be_visible(
        timeout=30000
    )
    expect(page.get_by_text("Lý do: MOCK: không phải tutorial", exact=True)).to_be_visible()
    expect(page.get_by_label("Nội dung Markdown")).to_have_count(0)
    expect(page.get_by_text("Đã dừng sau đoạn đầu", exact=False).first).to_be_visible()
    expect(page.get_by_text("đoạn hoàn tất", exact=False)).to_have_count(0)
    page.screenshot(path=str(OUT / "not-tutorial-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 375, "height": 900})
    page.screenshot(path=str(OUT / "not-tutorial-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.set_viewport_size({"width": 1440, "height": 1000})
    checked("non-tutorial stop screen shows the reason and no partial progress")
    analyze_anyway = page.get_by_role("button", name="Vẫn phân tích toàn bộ", exact=True)
    analyze_anyway.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    confirm = dialog.get_by_role("button", name="Xác nhận phân tích toàn bộ", exact=True)
    expect(confirm).to_be_disabled()
    page.screenshot(path=str(OUT / "not-tutorial-dialog-desktop.png"))
    dialog.get_by_label("Gửi lại video này tới provider để phân tích toàn bộ.").check()
    expect(confirm).to_be_disabled()
    dialog.get_by_label("Chấp nhận có thể tính phí thêm, chưa xác định trước.").check()
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/jobs")) as skip_request:
        confirm.click()
    assert json.loads(skip_request.value.post_data)["skip_tutorial_gate"] is True
    assert skip_request.value.headers.get("idempotency-key")
    expect(dialog).not_to_be_visible()
    expect(page.get_by_label("Nội dung Markdown")).to_be_visible(timeout=30000)
    expect(page.get_by_role("heading", name="Video này không được nhận là video hướng dẫn")).to_have_count(0)
    if not page.locator(".job-history").evaluate("(el)=>el.open"):
        page.locator(".job-history summary").click()
    history = page.locator(".job-history")
    expect(history).to_contain_text("Tạo tài liệu · Không phải tutorial")
    expect(history).to_contain_text("Đã dừng sau đoạn đầu; không phân tích các đoạn sau.")
    expect(history).to_contain_text("Video không giống video hướng dẫn: MOCK: không phải tutorial")
    checked("analyze anyway: cost confirmation, then a new job with skip_tutorial_gate")
    page.get_by_role("button", name="Xóa dự án", exact=True).click()
    page.get_by_role("button", name="Xóa dữ liệu dự án", exact=True).click()
    expect(page.get_by_role("heading", name="Thư viện video", exact=True)).to_be_visible(timeout=10000)
    assert not errors, errors
    checked("no browser JavaScript errors")
    browser.close()
shutil.rmtree(uploads, ignore_errors=True)
(OUT / "browser-results.json").write_text(
    json.dumps({"passed": checks, "page_errors": errors}, ensure_ascii=False, indent=2)
)
