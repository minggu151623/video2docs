import base64
import io
import json
import re
import zipfile
import subprocess
import sys
import os
import signal
from pathlib import Path
import bleach
from markdown_it import MarkdownIt
from pypdf import PdfReader
from app.core.errors import AppError
from app.core.storage import safe_path, sha256
from app.db.models import Evidence

parser = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
IMAGE_REF = re.compile(r"assets/([a-f0-9-]{36})\.png")


def markdown_images(markdown):
    found = []

    def walk(tokens):
        for token in tokens:
            if token.type == "image":
                found.append(token.attrGet("src"))
            if token.children:
                walk(token.children)

    walk(parser.parse(markdown))
    return found


def resolve_images(session, root, project_id, markdown):
    result = {}
    for reference in markdown_images(markdown):
        match = IMAGE_REF.fullmatch(reference)
        if not match:
            raise AppError(
                "UNSAFE_IMAGE", "Tài liệu có ảnh ngoài evidence manifest. Xóa hoặc chọn ảnh nội bộ.", 422
            )
        evidence = session.get(Evidence, match[1])
        if not evidence or evidence.project_id != project_id:
            raise AppError("EVIDENCE_MISSING", "Ảnh tham chiếu không thuộc dự án hoặc đã bị xóa.", 422)
        path = safe_path(root, evidence.relative_path)
        if not path.is_file() or sha256(path.read_bytes()) != evidence.sha256:
            raise AppError("EVIDENCE_MISSING", "Ảnh bị thiếu hoặc khác hash lưu trong manifest.", 422)
        result[reference] = (path.read_bytes(), evidence)
    return result


def safe_html(markdown, images):
    tokens = parser.parse(markdown)

    def walk(items):
        for token in items:
            if token.type == "image":
                reference = token.attrGet("src")
                token.attrSet(
                    "src", "data:image/png;base64," + base64.b64encode(images[reference][0]).decode()
                )
            if token.type == "link_open":
                token.attrs = (
                    {"href": token.attrGet("href")} if (token.attrGet("href") or "").startswith("#t=") else {}
                )
            if token.children:
                walk(token.children)

    walk(tokens)
    html = parser.renderer.render(tokens, parser.options, {})
    return bleach.clean(
        html,
        tags=[
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "ul",
            "ol",
            "li",
            "pre",
            "code",
            "blockquote",
            "strong",
            "em",
            "a",
            "img",
            "hr",
            "br",
            "table",
            "thead",
            "tbody",
            "tr",
            "td",
            "th",
        ],
        attributes={"img": ["src", "alt"], "a": ["href"]},
        protocols=["data"],
        strip=True,
    )


def pdf_bytes(markdown, images):
    font = Path(__file__).resolve().parents[1] / "static/fonts/DejaVuSans.ttf"
    if not font.is_file():
        raise AppError("PDF_FONT_MISSING", "Thiếu font PDF local; chạy scripts/setup.sh.", 503)
    encoded = base64.b64encode(font.read_bytes()).decode()
    html = (
        '<!doctype html><meta charset="utf-8"><style>'
        + f"""
    @font-face {{ font-family: Doc; src: url(data:font/ttf;base64,{encoded}); }}
    @page {{ size: A4; margin: 18mm 16mm; }}
    body {{ font-family: Doc, sans-serif; font-size: 10pt; line-height: 1.55; color: #202826; }}
    h1 {{ font-size: 23pt; line-height: 1.3; }} h2 {{ margin-top: 22pt; }}
    h1,h2,h3 {{ break-after: avoid; }} img {{ max-width: 100%; max-height: 180mm; object-fit: contain; }}
    p:has(img) {{ break-inside: avoid; break-after: avoid; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #f2f4f2; padding: 10pt; }}
    code {{ font-family: Doc, monospace; font-size: 9pt; overflow-wrap: anywhere; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
    td,th {{ border: 1px solid #a9b3ae; padding: 5pt; overflow-wrap: anywhere; }}
    tr {{ break-inside: avoid; }} a {{ color: #1f5d4b; }} blockquote {{ border-left: 2pt solid #61756b; margin-left: 0; padding-left: 10pt; }}
    </style>"""
        + safe_html(markdown, images)
    )
    try:
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        backend = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = backend
        process = subprocess.Popen(
            [sys.executable, "-m", "app.services.pdf_renderer"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        try:
            result, _ = process.communicate(html.encode(), timeout=60)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
        if process.returncode:
            raise AppError("PDF_DEPENDENCY", "Chromium không tạo được PDF. Kiểm tra cài đặt browser.", 503)
        reader = PdfReader(io.BytesIO(result))
        if len(reader.pages) == 0 or not any(page.extract_text().strip() for page in reader.pages):
            raise AppError("PDF_EMPTY", "PDF không có nội dung đọc được.", 503)
        return result
    except AppError:
        raise
    except Exception:
        raise AppError(
            "PDF_DEPENDENCY",
            "Không tạo được PDF. Kiểm tra Chromium với uv run playwright install chromium.",
            503,
        )


def build_export(session, settings, revision, project_id, fmt):
    if fmt == "md":
        return revision.markdown.encode("utf-8")
    images = resolve_images(session, settings.data_dir, project_id, revision.markdown)
    if fmt == "pdf":
        return pdf_bytes(revision.markdown, images)
    archive = io.BytesIO()
    manifest = {
        "revision": revision.id,
        "content_sha256": revision.content_sha256,
        "created_at": revision.created_at,
        "evidence": [],
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("document.md", revision.markdown)
        for reference, (content, item) in images.items():
            z.writestr(reference, content)
            manifest["evidence"].append(
                {
                    "id": item.id,
                    "sha256": item.sha256,
                    "requested_sec": item.requested_sec,
                    "actual_sec": item.actual_sec,
                    "asset_id": item.asset_id,
                }
            )
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return archive.getvalue()
