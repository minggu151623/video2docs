"""Domain-aware Markdown renderer for v2 drafts, with verification badges (spec 4.3)."""

import re
from app.services.verification.matcher import iter_grounded_items

SECTION_LABELS = {
    "cooking": {"vi": ("Nguyên liệu", "Dụng cụ"), "en": ("Ingredients", "Utensils")},
    "repair": {"vi": ("Vật liệu", "Dụng cụ"), "en": ("Materials", "Tools")},
    "craft": {"vi": ("Vật liệu", "Dụng cụ"), "en": ("Materials", "Tools")},
    "gardening": {"vi": ("Vật liệu", "Dụng cụ"), "en": ("Materials", "Tools")},
    "beauty": {"vi": ("Sản phẩm", "Dụng cụ"), "en": ("Products", "Tools")},
    "fitness": {"vi": ("Vật liệu", "Thiết bị"), "en": ("Materials", "Equipment")},
    "software": {"vi": ("Tài nguyên", "Phần mềm cần có"), "en": ("Resources", "Required software")},
    "music": {"vi": ("Vật liệu", "Dụng cụ"), "en": ("Materials", "Tools")},
    "other": {"vi": ("Vật liệu", "Dụng cụ"), "en": ("Materials", "Tools")},
}
ITEM_LABELS = {
    "prerequisites": ("Chuẩn bị", "Prerequisite"),
    "safety": ("An toàn", "Safety"),
    "troubleshooting": ("Xử lý lỗi", "Troubleshooting"),
    "parameters": ("Thông số", "Parameter"),
    "exact_inputs": ("Nội dung chính xác", "Exact input"),
    "warnings": ("Cảnh báo", "Warning"),
    "tips": ("Mẹo", "Tip"),
}
NOT_CHECKED = ("unverified", "not_checked")


def stamp(seconds):
    s = int(seconds)
    return f"{s // 3600:02}:{s // 60 % 60:02}:{s % 60:02}"


def escape(value):
    return re.sub(r"([\\`*_{}\[\]<>#+.!|~-])", r"\\\1", str(value)).replace("\n", " ")


def supported_claim(claim):
    return claim.basis in ("observed", "stated")


def link(seconds):
    return f"[{stamp(seconds)}](#t={seconds:.3f})"


def material_text(m):
    text = escape(m.name)
    amount = " ".join(v for v in (m.quantity, m.unit) if v)
    if amount:
        text += ": " + escape(amount)
    return text + (f" ({escape(m.note)})" if m.note else "")


def parameter_text(p):
    return f"{escape(p.name)}: {escape(' '.join(v for v in (p.value, p.unit) if v))}"


def render_markdown(draft, asset, model, generation, evidence, verification=None):
    en = draft.language == "en"

    def t(vi, english):
        return english if en else vi

    paths = {id(item): path for path, _, item in iter_grounded_items(draft)}
    found = verification.items if verification else {}

    def status(item):
        """Verification status of a tracked item; None when there is no report or the item is not tracked."""
        if verification is None or id(item) not in paths:
            return None
        return found[paths[id(item)]].status if paths[id(item)] in found else "not_checked"

    def badge(item):
        state = status(item)
        if state is None:
            return ""
        if state == "verified":
            result = found[paths[id(item)]]
            where = t("khớp lời nói", "matches speech")
            if result.method == "ocr":
                where = t("khớp chữ trên màn hình", "matches on-screen text")
            at = f" {link(result.matched_sec)}" if result.matched_sec is not None else ""
            return f" · ✓ {where}{at}"
        if state == "not_checkable":
            return " · " + t("không có văn bản để đối chiếu", "no text to check against")
        return " · ? " + t("chưa kiểm chứng", "not verified")

    def line(text, item, links=True, badges=True):
        spans = "".join(" " + link(s.start_sec) for s in item.evidence_spans) if links else ""
        return text + spans + (badge(item) if badges else "")

    materials_label, equipment_label = SECTION_LABELS[draft.domain][draft.language]
    lines = [
        f"# {escape(draft.title)}",
        "",
        t("> Bản nháp: cần kiểm tra lại với video nguồn.", "> Draft: verify against the video."),
        "",
        escape(draft.summary),
        "",
    ]
    if draft.yield_:
        lines += [f"{t('Khẩu phần', 'Yield')}: {escape(draft.yield_)}", ""]

    def section(title, values, placeholder=None):
        if values or placeholder:
            lines.extend([f"## {title}", ""] + (["- " + v for v in values] or [placeholder]) + [""])

    missing = t("Không được nêu trong video.", "Not mentioned in the video.")

    def claims(collection, scope="tutorial", prefix=""):
        return [
            prefix + line(escape(c.text), c) for c in collection if c.scope == scope and supported_claim(c)
        ]

    section(t("Mục tiêu", "Objectives"), [escape(v) for v in draft.objectives], missing)
    section(t("Chuẩn bị", "Prerequisites"), claims(draft.prerequisites), missing)
    section(t("An toàn", "Safety"), claims(draft.safety))
    section(materials_label, [line(material_text(m), m) for m in draft.materials if supported_claim(m)])
    section(
        equipment_label,
        [line(escape(e.name + (" " + e.spec if e.spec else "")), e) for e in draft.equipment],
        missing,
    )
    context = claims(draft.prerequisites, "clip") + claims(draft.safety, "clip", t("An toàn: ", "Safety: "))
    section(t("Ngữ cảnh theo đoạn", "Clip context"), context)
    lines += [f"## {t('Các bước thực hiện', 'Steps')}", ""]
    for index, step in enumerate(draft.steps):
        lines += [
            f"### {index + 1}. {escape(step.title)}",
            "",
            f"{link(step.start_sec)} · {escape(step.local_id)}",
            "",
        ]
        if step.needs_review:
            lines += ["> " + t("Cần kiểm tra: ", "Needs review: ") + escape(step.review_reason), ""]
        lines += ["- " + escape(a) for a in step.actions] + [""]
        lines += ["- " + line(parameter_text(p), p, False) for p in step.parameters if supported_claim(p)]
        lines += [""] if any(supported_claim(p) for p in step.parameters) else []
        for command in step.exact_inputs:
            fence = "`" * max(3, max([len(m) for m in re.findall(r"`+", command.text)] or [0]) + 1)
            language = re.sub("[^a-zA-Z0-9_+-]", "", command.language or "")
            lines += [f"{fence}{language}", command.text, fence, ""]
            lines += [f"*{escape(command.completeness)}*{badge(command)}", ""]
        extras = [(t("Cảnh báo: ", "Warning: "), step.warnings), (t("Mẹo: ", "Tip: "), step.tips)]
        for prefix, collection in extras:
            lines += ["- " + prefix + line(escape(c.text), c) for c in collection if supported_claim(c)]
            lines += [""] if any(supported_claim(c) for c in collection) else []
        if step.expected_result:
            lines += [t("Kết quả: ", "Expected result: ") + escape(step.expected_result), ""]
        for span in step.evidence_spans:
            lines += [f"- {escape(span.source)} {link(span.start_sec)}: {escape(span.description)}"]
        lines += [""]
        image = evidence.get(step.local_id)
        if image:
            note = t("Chưa kiểm tra bằng mắt", "Not visually verified")
            lines += [
                f"![{escape(step.title)}](assets/{image.id}.png)",
                "",
                f"*{stamp(image.actual_sec)} · {escape(step.local_id)} · {note}*",
                "",
            ]
        elif not any(s.source in ("visual", "both") for s in step.evidence_spans):
            lines += [t("Chỉ có bằng chứng âm thanh.", "Audio evidence only."), ""]
    section(
        t("Lỗi và cách xử lý", "Troubleshooting"),
        [line(escape(c.text), c) for c in draft.troubleshooting if supported_claim(c)],
        missing,
    )

    def item_text(name, item):
        if name == "materials":
            return line(material_text(item), item, badges=False)
        if name == "parameters":
            return parameter_text(item)
        if name == "exact_inputs":
            return escape(item.text[:80])
        return line(escape(item.text), item, badges=False)

    reviews = []
    for uncertainty in draft.uncertainties:
        scope = t("Trong phạm vi đoạn nguồn", "Within this source segment")
        if uncertainty.start_sec is not None:
            scope += f" {link(uncertainty.start_sec)} {t('đến', 'to')} {stamp(uncertainty.end_sec)}"
        reviews.append(scope + ": " + escape(uncertainty.description))
    in_step = {
        id(i): n + 1
        for n, s in enumerate(draft.steps)
        for c in ("parameters", "exact_inputs", "warnings", "tips")
        for i in getattr(s, c)
    }
    for _, name, item in iter_grounded_items(draft):
        if name == "exact_inputs" or supported_claim(item):
            if status(item) not in NOT_CHECKED:
                continue
            reason = t("chưa kiểm chứng", "not verified")
        else:
            reason = t("chưa đủ bằng chứng", "insufficient evidence")
        label = materials_label if name == "materials" else t(*ITEM_LABELS[name])
        if id(item) in in_step:
            label += f" ({t('bước', 'step')} {in_step[id(item)]})"
        reviews.append(f"{label}, {reason}: " + item_text(name, item))
    none_reported = t("Không có mục được báo.", "No uncertainty reported.")
    section(t("Điểm chưa rõ", "Needs review"), reviews, none_reported)
    lines += [
        f"## {t('Thông tin nguồn', 'Source')}",
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
