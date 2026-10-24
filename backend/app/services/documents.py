from difflib import SequenceMatcher
from app.schemas.tutorial_v2 import TutorialDraftV2
from app.core.errors import AppError
from app.services.rendering import escape, render_markdown, stamp, supported_claim  # noqa: F401
from app.core.storage import sha256, uid
from app.db.models import Document, Revision, now
from sqlalchemy import update


def has_review_claims(draft):
    claims = [*draft.prerequisites, *draft.safety, *draft.troubleshooting, *draft.materials]
    for step in draft.steps:
        claims += [*step.warnings, *step.tips, *step.parameters]
    return any(not supported_claim(c) for c in claims)


def material_key(item):
    return (
        item["name"].casefold().strip(),
        (item["quantity"] or "").strip(),
        (item["unit"] or "").casefold().strip(),
    )


def merge_evidence(target, extra):
    spans = [s for s in extra["evidence_spans"] if s not in target["evidence_spans"]]
    target["evidence_spans"] = (target["evidence_spans"] + spans)[:5]


def assemble(parts, duration, max_steps=80):
    first = parts[0][1].model_dump(by_alias=True)
    first.update(
        steps=[],
        prerequisites=[],
        safety=[],
        materials=[],
        equipment=[],
        troubleshooting=[],
        uncertainties=[],
        objectives=[],
        summary="",
    )
    summaries = []
    has_steps = False
    for chunk_index, (offset, draft) in enumerate(parts):
        data = draft.model_dump(by_alias=True)

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
            for claim in (*data["prerequisites"], *data["safety"]):
                claim["scope"] = "clip"
        if first["yield"] is None:
            first["yield"] = data["yield"]
        if data["steps"]:
            has_steps = True
        if data["summary"] and data["summary"] not in summaries:
            summaries.append(data["summary"])
        for field in (
            "objectives",
            "prerequisites",
            "safety",
            "troubleshooting",
            "uncertainties",
        ):
            for value in data[field]:
                if value not in first[field]:
                    first[field].append(value)
        for item in data["materials"]:
            same = next((m for m in first["materials"] if material_key(m) == material_key(item)), None)
            if same is None:
                first["materials"].append(item)
            else:
                merge_evidence(same, item)
        for tool in data["equipment"]:
            key = (tool["name"].casefold().strip(), (tool["spec"] or "").casefold().strip())
            same = next(
                (
                    t
                    for t in first["equipment"]
                    if (t["name"].casefold().strip(), (t["spec"] or "").casefold().strip()) == key
                ),
                None,
            )
            if same is None:
                first["equipment"].append(tool)
            else:
                merge_evidence(same, tool)
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
    if has_steps:
        first["is_tutorial"], first["not_tutorial_reason"] = True, None
    if len(first["steps"]) > max_steps:
        raise AppError("DOCUMENT_LIMIT_EXCEEDED", "Tài liệu vượt giới hạn số bước; hãy tách video.", 422)
    try:
        return TutorialDraftV2.model_validate(first, context={"duration": duration})
    except ValueError:
        raise AppError("DOCUMENT_LIMIT_EXCEEDED", "Kết quả ghép vượt schema; hãy tách video.", 422)


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
