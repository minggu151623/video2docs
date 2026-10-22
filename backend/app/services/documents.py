import re
from difflib import SequenceMatcher
from app.schemas.tutorial import TutorialDraftV1
from app.core.errors import AppError
from app.core.storage import sha256, uid
from app.db.models import Document, Revision, now
from sqlalchemy import update


def stamp(seconds):
    s = int(seconds)
    return f"{s // 3600:02}:{s // 60 % 60:02}:{s % 60:02}"


def escape(value):
    return re.sub(r"([\\`*_{}\[\]<>#+.!|~-])", r"\\\1", str(value)).replace("\n", " ")


def supported_claim(claim):
    return claim.basis in ("observed", "stated")


def has_review_claims(draft):
    return any(not supported_claim(c) for c in [*draft.prerequisites, *draft.troubleshooting])


def assemble(parts, duration, max_steps=80):
    first = parts[0][1].model_dump()
    first.update(
        steps=[], prerequisites=[], tools=[], troubleshooting=[], uncertainties=[], objectives=[], summary=""
    )
    summaries = []
    for chunk_index, (offset, draft) in enumerate(parts):
        data = draft.model_dump()

        def shift(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("start_sec", "end_sec") and value is not None:
                        node[key] = value + offset
                    elif key == "screenshot_candidates_sec":
                        node[key] = [v + offset for v in value]
                    else:
                        shift(value)
            elif isinstance(node, list):
                for value in node:
                    shift(value)

        shift(data)
        if chunk_index > 0:
            for prerequisite in data["prerequisites"]:
                prerequisite["scope"] = "clip"
        if data["summary"] and data["summary"] not in summaries:
            summaries.append(data["summary"])
        for field in ("objectives", "prerequisites", "troubleshooting", "uncertainties"):
            for value in data[field]:
                if value not in first[field]:
                    first[field].append(value)
        for tool in data["tools"]:
            key = (tool["name"].casefold().strip(), (tool["version"] or "").casefold().strip())
            same = next(
                (
                    t
                    for t in first["tools"]
                    if (t["name"].casefold().strip(), (t["version"] or "").casefold().strip()) == key
                ),
                None,
            )
            if same is None:
                first["tools"].append(tool)
            else:
                spans = [s for s in tool["evidence_spans"] if s not in same["evidence_spans"]]
                same["evidence_spans"] = (same["evidence_spans"] + spans)[:5]
        for step in data["steps"]:
            step["local_id"] = f"c{chunk_index + 1}-{step['local_id']}"
            normalized = lambda s: " ".join((s["title"] + " " + " ".join(s["actions"])).lower().split())
            duplicate = False
            for previous in first["steps"]:
                overlap = max(previous["start_sec"], step["start_sec"]) < min(
                    previous["end_sec"], step["end_sec"]
                )
                if overlap and normalized(previous) == normalized(step):
                    duplicate = True
                    break
                if overlap and SequenceMatcher(None, normalized(previous), normalized(step)).ratio() > 0.8:
                    step["needs_review"] = True
                    step["review_reason"] = (
                        "Có thể trùng hoặc tiếp tục bước trước ở ranh giới đoạn; cần kiểm tra."
                    )
            if not duplicate:
                first["steps"].append(step)
    first["steps"].sort(key=lambda s: (s["start_sec"], s["end_sec"]))
    first["summary"] = "\n".join(summaries)
    if len(first["steps"]) > max_steps:
        raise AppError("DOCUMENT_LIMIT_EXCEEDED", "Tài liệu vượt giới hạn số bước; hãy tách video.", 422)
    try:
        return TutorialDraftV1.model_validate(first, context={"duration": duration})
    except ValueError:
        raise AppError("DOCUMENT_LIMIT_EXCEEDED", "Kết quả ghép vượt schema; hãy tách video.", 422)


def render_markdown(draft, asset, model, generation, evidence):
    en = draft.language == "en"

    def claim(text, spans):
        return escape(text) + " " + " ".join(f"[{stamp(s.start_sec)}](#t={s.start_sec:.3f})" for s in spans)

    lines = [
        f"# {escape(draft.title)}",
        "",
        "> Draft: verify against the video." if en else "> Bản nháp: cần kiểm tra lại với video nguồn.",
        "",
        escape(draft.summary),
        "",
    ]
    sections = [
        ("Objectives" if en else "Mục tiêu", [escape(v) for v in draft.objectives]),
        (
            "Prerequisites" if en else "Chuẩn bị",
            [
                claim(p.text, p.evidence_spans)
                for p in draft.prerequisites
                if p.scope == "tutorial" and supported_claim(p)
            ],
        ),
        (
            "Tools" if en else "Công cụ",
            [claim(t.name + (" " + t.version if t.version else ""), t.evidence_spans) for t in draft.tools],
        ),
    ]
    for title, values in sections:
        lines += (
            [f"## {title}", ""]
            + (
                ["- " + v for v in values]
                or ["Not mentioned in the video." if en else "Không được nêu trong video."]
            )
            + [""]
        )
    context = [
        claim(p.text, p.evidence_spans)
        for p in draft.prerequisites
        if p.scope == "clip" and supported_claim(p)
    ]
    if context:
        lines += ["## Clip context" if en else "## Ngữ cảnh theo đoạn", ""]
        lines += ["- " + value for value in context] + [""]
    lines += ["## Steps" if en else "## Các bước thực hiện", ""]
    for index, step in enumerate(draft.steps):
        lines += [
            f"### {index + 1}. {escape(step.title)}",
            "",
            f"[{stamp(step.start_sec)}](#t={step.start_sec:.3f}) · {escape(step.local_id)}",
            "",
        ]
        if step.needs_review:
            lines += ["> " + ("Needs review: " if en else "Cần kiểm tra: ") + escape(step.review_reason), ""]
        lines += ["- " + escape(a) for a in step.actions] + [""]
        for command in step.commands:
            fence = "`" * max(3, max([len(m) for m in re.findall(r"`+", command.text)] or [0]) + 1)
            language = re.sub("[^a-zA-Z0-9_+-]", "", command.language)
            lines += [f"{fence}{language}", command.text, fence, "", f"*{escape(command.completeness)}*", ""]
        if step.expected_result:
            lines += [("Expected result: " if en else "Kết quả: ") + escape(step.expected_result), ""]
        for span in step.evidence_spans:
            lines += [
                f"- {escape(span.source)} [{stamp(span.start_sec)}](#t={span.start_sec:.3f}): {escape(span.description)}"
            ]
        lines += [""]
        item = evidence.get(step.local_id)
        if item:
            lines += [
                f"![{escape(step.title)}](assets/{item.id}.png)",
                "",
                f"*{stamp(item.actual_sec)} · {escape(step.local_id)} · "
                + ("Not visually verified" if en else "Chưa kiểm tra bằng mắt")
                + "*",
                "",
            ]
        elif not any(s.source in ("visual", "both") for s in step.evidence_spans):
            lines += ["Audio evidence only." if en else "Chỉ có bằng chứng âm thanh.", ""]
    lines += ["## Troubleshooting" if en else "## Lỗi và cách xử lý", ""]
    lines += [
        "- " + claim(c.text, c.evidence_spans) for c in draft.troubleshooting if supported_claim(c)
    ] or ["Not mentioned in the video." if en else "Không được nêu trong video."]
    lines += ["", "## Needs review" if en else "## Điểm chưa rõ", ""]
    reviews = []
    for uncertainty in draft.uncertainties:
        scope = "Within this source segment" if en else "Trong phạm vi đoạn nguồn"
        if uncertainty.start_sec is not None:
            scope += (
                f" [{stamp(uncertainty.start_sec)}](#t={uncertainty.start_sec:.3f})"
                f" {'to' if en else 'đến'} {stamp(uncertainty.end_sec)}"
            )
        reviews.append(scope + ": " + escape(uncertainty.description))
    for label, claims in (
        ("Prerequisite" if en else "Chuẩn bị", draft.prerequisites),
        ("Troubleshooting" if en else "Xử lý lỗi", draft.troubleshooting),
    ):
        for item in claims:
            if not supported_claim(item):
                reason = "insufficient evidence" if en else "chưa đủ bằng chứng"
                reviews.append(f"{label}, {reason}: " + claim(item.text, item.evidence_spans))
    lines += ["- " + value for value in reviews] or [
        "No uncertainty reported." if en else "Không có mục được báo."
    ]
    lines += [
        "",
        "## Source" if en else "## Thông tin nguồn",
        "",
        f"- File: {escape(asset.original_name)}",
        f"- Duration: {stamp(asset.duration_sec)}",
        f"- Model: {escape(model)}",
        f"- Generation: {generation.id}",
        f"- Created (UTC): {generation.created_at}",
        "- Pipeline: 0.1.0",
        "",
    ]
    return "\n".join(lines)


def create_revision(session, document, base_revision, markdown, source, generation_id=None):
    if document.current_revision_id != base_revision:
        raise AppError(
            "REVISION_CONFLICT", "Tài liệu đã thay đổi ở tab khác. Bản local được giữ để bạn sao chép.", 409
        )
    previous = session.get(Revision, base_revision) if base_revision else None
    revision = Revision(
        id=uid(),
        document_id=document.id,
        revision_number=previous.revision_number + 1 if previous else 1,
        base_revision_id=base_revision,
        markdown=markdown,
        generation_id=generation_id if generation_id else (previous.generation_id if previous else None),
        content_sha256=sha256(markdown.encode()),
        source=source,
    )
    session.add(revision)
    session.flush()
    changed = session.execute(
        update(Document)
        .where(Document.id == document.id, Document.current_revision_id == base_revision)
        .values(current_revision_id=revision.id, updated_at=now())
    )
    if changed.rowcount != 1:
        raise AppError("REVISION_CONFLICT", "Tài liệu đã thay đổi ở tab khác.", 409)
    return revision
