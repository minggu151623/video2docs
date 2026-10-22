from types import SimpleNamespace as NS
import pytest
from app.core.config import Settings
from app.providers.mock import MockProvider
from app.schemas.tutorial_v2 import TutorialDraftV2
from app.schemas.verification import ItemVerification, VerificationReport
from app.services.documents import render_markdown as reexported
from app.services.rendering import SECTION_LABELS, render_markdown, stamp

ASSET = NS(original_name="source.mp4", duration_sec=10)
GENERATION = NS(id="generation", created_at="2026-10-22")


def span(source="both"):
    return {"start_sec": 1, "end_sec": 3, "source": source, "description": "Source"}


def material(name="Bột mì", quantity="200", unit="gram", basis="stated"):
    return {
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "note": None,
        "evidence_spans": [span()],
        "basis": basis,
        "quote": f"{quantity} {unit} {name}" if basis == "stated" else None,
        "on_screen_text": None,
    }


def parameter(name="Nhiệt độ", value="180", unit="°C", basis="stated"):
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "evidence_spans": [span()],
        "basis": basis,
        "quote": f"{value} {unit}" if basis == "stated" else None,
        "on_screen_text": None,
    }


def claim(text, basis="stated", scope="tutorial"):
    return {
        "text": text,
        "evidence_spans": [span()],
        "basis": basis,
        "scope": scope,
        "quote": text if basis == "stated" else None,
        "on_screen_text": None,
    }


def build(domain="cooking", language="vi", **changes):
    data = MockProvider(Settings(ai_provider="mock")).analyze(None, 10, language, {})["text"]
    draft = TutorialDraftV2.model_validate_json(data, context={"duration": 10})
    data = draft.model_dump(by_alias=True)
    data.update(domain=domain, language=language, **changes)
    return TutorialDraftV2.model_validate(data, context={"duration": 10})


def with_step(draft, **fields):
    data = draft.model_dump(by_alias=True)
    data["steps"][0].update(fields)
    return TutorialDraftV2.model_validate(data, context={"duration": 10})


def render(draft, verification=None, evidence=None):
    return render_markdown(draft, ASSET, "model", GENERATION, evidence or {}, verification)


def report(**items):
    return VerificationReport(items=items, asr_status="ok", ocr_status="ok")


def verified(method="asr", sec=135.0):
    return ItemVerification(status="verified", method=method, matched_text="x", matched_sec=sec)


def unverified():
    return ItemVerification(status="unverified", method="asr", reason="no match")


def headings(text):
    return [line[3:] for line in text.splitlines() if line.startswith("## ")]


def test_documents_reexports_renderer():
    assert reexported is render_markdown


def test_cooking_labels_and_section_order():
    draft = build(
        objectives=["Làm bánh"],
        prerequisites=[claim("Lò đã làm nóng")],
        safety=[claim("Cẩn thận dầu nóng")],
        materials=[material()],
        equipment=[{"name": "Chảo", "spec": None, "evidence_spans": [span()]}],
    )
    data = draft.model_dump(by_alias=True)
    data["prerequisites"].append(claim("Tủ lạnh trống", scope="clip"))
    data["prerequisites"][0]["scope"] = "tutorial"
    text = render(TutorialDraftV2.model_validate(data, context={"duration": 10}))
    assert headings(text) == [
        "Mục tiêu",
        "Chuẩn bị",
        "An toàn",
        "Nguyên liệu",
        "Dụng cụ",
        "Ngữ cảnh theo đoạn",
        "Các bước thực hiện",
        "Lỗi và cách xử lý",
        "Điểm chưa rõ",
        "Thông tin nguồn",
    ]


def test_labels_table_matches_spec():
    assert SECTION_LABELS["cooking"]["vi"] == ("Nguyên liệu", "Dụng cụ")
    assert SECTION_LABELS["cooking"]["en"] == ("Ingredients", "Utensils")
    assert SECTION_LABELS["software"]["vi"] == ("Tài nguyên", "Phần mềm cần có")
    assert SECTION_LABELS["software"]["en"] == ("Resources", "Required software")
    assert SECTION_LABELS["beauty"]["vi"] == ("Sản phẩm", "Dụng cụ")
    assert SECTION_LABELS["fitness"]["vi"] == ("Vật liệu", "Thiết bị")
    assert SECTION_LABELS["fitness"]["en"] == ("Materials", "Equipment")
    for domain in ("repair", "craft", "gardening", "music", "other"):
        assert SECTION_LABELS[domain]["vi"] == ("Vật liệu", "Dụng cụ")
        assert SECTION_LABELS[domain]["en"] == ("Materials", "Tools")
    assert SECTION_LABELS["beauty"]["en"] == ("Products", "Tools")


def test_empty_new_sections_are_hidden():
    text = render(build())
    assert "## Nguyên liệu" not in text and "## An toàn" not in text
    treatment = text.split("## Lỗi và cách xử lý", 1)[1].split("## Điểm chưa rõ", 1)[0]
    assert "Không được nêu trong video." in treatment


def test_parameter_line_and_badges():
    draft = with_step(build(), parameters=[parameter(), parameter("Thời gian", "20", "phút")])
    text = render(
        draft,
        report(
            **{
                "steps/0/parameters/0": verified(sec=135),
                "steps/0/parameters/1": unverified(),
            }
        ),
    )
    assert "Nhiệt độ: 180 °C · ✓ khớp lời nói [00:02:15](#t=135.000)" in text
    assert "Thời gian: 20 phút · ? chưa kiểm chứng" in text
    review = text.split("## Điểm chưa rõ", 1)[1].split("## Thông tin nguồn", 1)[0]
    assert "Thời gian: 20 phút" in review and "Nhiệt độ" not in review
    assert "chưa kiểm chứng" in review


def test_ocr_and_not_checkable_badges():
    draft = with_step(build(), parameters=[parameter(), parameter("Thời gian", "20", "phút")])
    text = render(
        draft,
        report(
            **{
                "steps/0/parameters/0": verified("ocr", 7),
                "steps/0/parameters/1": ItemVerification(status="not_checkable", method="none"),
            }
        ),
    )
    assert "✓ khớp chữ trên màn hình [00:00:07](#t=7.000)" in text
    assert "Thời gian: 20 phút · không có văn bản để đối chiếu" in text
    review = text.split("## Điểm chưa rõ", 1)[1]
    assert "Thời gian" not in review.split("## Thông tin nguồn", 1)[0]


def test_unverified_material_listed_with_collection_label():
    text = render(build(materials=[material()]), report(**{"materials/0": unverified()}))
    section = text.split("## Nguyên liệu", 1)[1].split("## Dụng cụ", 1)[0]
    assert "Bột mì: 200 gram" in section and "? chưa kiểm chứng" in section
    review = text.split("## Điểm chưa rõ", 1)[1]
    assert "Nguyên liệu, chưa kiểm chứng: Bột mì: 200 gram" in review


def test_inferred_material_only_in_review():
    draft = build(materials=[material("Muối", "1", "thìa", basis="inferred"), material()])
    text = render(draft)
    assert "Muối" not in text.split("## Điểm chưa rõ", 1)[0]
    assert "Bột mì" in text.split("## Điểm chưa rõ", 1)[0]
    assert "Nguyên liệu, chưa đủ bằng chứng: Muối: 1 thìa" in text.split("## Điểm chưa rõ", 1)[1]
    only_inferred = render(build(materials=[material("Muối", "1", "thìa", basis="inferred")]))
    assert "## Nguyên liệu" not in only_inferred


def test_inferred_step_items_only_in_review():
    draft = with_step(
        build(),
        parameters=[parameter(basis="inferred")],
        warnings=[claim("Cẩn thận bỏng", basis="inferred")],
        tips=[claim("Mẹo hay", basis="inferred")],
    )
    text = render(draft)
    main, review = text.split("## Điểm chưa rõ", 1)
    assert "180" not in main and "Cẩn thận bỏng" not in main and "Mẹo hay" not in main
    assert "180 °C" in review and "Cẩn thận bỏng" in review and "Mẹo hay" in review


def test_without_verification_no_badges():
    draft = with_step(build(materials=[material()]), parameters=[parameter()])
    text = render(draft)
    assert "✓" not in text and "?" not in text and "chưa kiểm chứng" not in text
    assert "Nhiệt độ: 180 °C" in text


def test_missing_report_entry_counts_as_not_checked():
    text = render(build(materials=[material()]), report())
    assert "Bột mì: 200 gram" in text and "? chưa kiểm chứng" in text


def test_warnings_tips_prefix_and_order():
    draft = with_step(
        build(),
        parameters=[parameter()],
        warnings=[claim("Cẩn thận bỏng")],
        tips=[claim("Dùng chảo gang")],
        expected_result="Bánh vàng",
    )
    text = render(draft)
    order = ["Nhiệt độ: 180", "Cảnh báo: Cẩn thận bỏng", "Mẹo: Dùng chảo gang", "Kết quả: Bánh vàng"]
    positions = [text.index(s) for s in order]
    assert positions == sorted(positions)


def test_exact_input_renders_fenced_block():
    exact = {
        "kind": "command",
        "language": "bash",
        "text": "echo ```hi```",
        "completeness": "complete",
        "evidence_spans": [span()],
        "basis": "observed",
        "quote": None,
        "on_screen_text": "echo ```hi```",
    }
    text = render(with_step(build(domain="software"), exact_inputs=[exact]))
    assert "````bash\necho ```hi```\n````" in text
    assert "*complete*" in text
    badged = render(
        with_step(build(domain="software"), exact_inputs=[exact]),
        report(**{"steps/0/exact_inputs/0": verified("ocr", 2)}),
    )
    assert "*complete* · ✓ khớp chữ trên màn hình [00:00:02]" in badged


def test_english_badges_and_labels():
    draft = with_step(
        build(language="en", materials=[material("Flour", "200", "g")]),
        parameters=[parameter("Temperature"), parameter("Time", "20", "min")],
        warnings=[claim("Hot oil")],
    )
    text = render(
        draft,
        report(
            **{
                "materials/0": unverified(),
                "steps/0/parameters/0": verified(sec=135),
                "steps/0/parameters/1": verified("ocr", 9),
                "steps/0/warnings/0": ItemVerification(status="not_checkable", method="none"),
            }
        ),
    )
    assert "✓ matches speech [00:02:15](#t=135.000)" in text
    assert "✓ matches on-screen text [00:00:09](#t=9.000)" in text
    assert "? not verified" in text and "no text to check against" in text
    assert "Warning: Hot oil" in text
    assert "## Ingredients" in text and "## Utensils" in text and "## Needs review" in text
    assert "Ingredients, not verified: Flour: 200 g" in text


def test_yield_line_directly_under_summary():
    text = render(build(**{"yield": "4 người ăn", "summary": "Tóm tắt"}))
    assert "Tóm tắt\n\nKhẩu phần: 4 người ăn\n" in text
    en = render(build(language="en", **{"yield": "4 servings", "summary": "Summary"}))
    assert "Summary\n\nYield: 4 servings\n" in en
    assert "Khẩu phần" not in render(build())


def test_clip_scoped_safety_goes_to_clip_context():
    draft = build(safety=[claim("Đeo găng", scope="tutorial"), claim("Tắt bếp", scope="clip")])
    text = render(draft)
    safety = text.split("## An toàn", 1)[1].split("## Dụng cụ", 1)[0]
    assert "Đeo găng" in safety and "Tắt bếp" not in safety
    assert "Tắt bếp" in text.split("## Ngữ cảnh theo đoạn", 1)[1].split("## Các bước", 1)[0]


def test_stamp_formats_hours():
    assert stamp(3725) == "01:02:05"


@pytest.mark.parametrize(
    "language,expected", [("vi", "Chỉ có bằng chứng âm thanh."), ("en", "Audio evidence only.")]
)
def test_audio_only_note(language, expected):
    draft = with_step(build(language=language), evidence_spans=[{**span("audio")}])
    assert expected in render(draft)
