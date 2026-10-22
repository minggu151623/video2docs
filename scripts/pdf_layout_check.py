"""Generate a standalone synthetic multi-page PDF for visual QA."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.services.exports import pdf_bytes
from app.core.storage import atomic_write

markdown = "# Kiểm tra bố cục PDF tiếng Việt\n\nBản tổng hợp để kiểm tra chữ, bảng, code và ảnh.\n\n"
markdown += "## Command dài\n\n```sh\n" + "echo " + "du_lieu_kiem_tra_" * 30 + "\n```\n\n"
markdown += "## Bảng nhiều dòng\n\n| Bước | Mô tả | Kết quả |\n| --- | --- | --- |\n"
for i in range(45):
    markdown += f"| {i + 1} | Kiểm tra tiếng Việt: nguồn, điều kiện, kết quả | Đọc được và không tràn |\n"
markdown += "\n## Ảnh nguồn tổng hợp\n\n![Fixture](assets/fixture.png)\n\n*Chú thích ảnh nguồn tổng hợp, không phải kết quả phân tích Gemini.*\n"
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 800, "height": 450})
    page.set_content(
        '<html lang="vi"><body style="font:32px sans-serif;background:#e8eee8;color:#244632;padding:40px"><h1>Ảnh kiểm tra PDF</h1><p>Tiếng Việt: hướng dẫn, bằng chứng, kết quả.</p></body></html>'
    )
    image = page.screenshot()
    browser.close()
atomic_write(
    root / "tmp/e2e-artifacts/pdf-layout.pdf", pdf_bytes(markdown, {"assets/fixture.png": (image, None)})
)
print("Created tmp/e2e-artifacts/pdf-layout.pdf")
