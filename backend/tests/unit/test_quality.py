from types import SimpleNamespace as NS
import pytest
from app.core.config import Settings
from app.providers.mock import MockProvider
from app.schemas.tutorial import SourceClaim
from app.schemas.tutorial_v2 import GroundedClaim, TutorialDraftV2
from app.services.analysis import clip_metadata, evidence_timestamp, repair_payload
from app.services.documents import assemble, render_markdown, has_review_claims


@pytest.fixture
def draft():
    return TutorialDraftV2.model_validate_json(
        MockProvider(Settings(ai_provider="mock")).analyze(None, 10, "vi", {})["text"],
        context={"duration": 10},
    )


def claim(text, basis="observed", scope="tutorial", source="visual"):
    return GroundedClaim.model_validate(
        {
            "text": text,
            "basis": basis,
            "scope": scope,
            "quote": "Spoken words" if basis == "stated" else None,
            "evidence_spans": [{"start_sec": 0, "end_sec": 2, "source": source, "description": "Source"}],
        }
    )


def markdown(draft):
    return render_markdown(
        draft,
        NS(original_name="source.mp4", duration_sec=10),
        "configured-model",
        NS(id="generation", created_at="2026-10-21"),
        {},
    )


@pytest.mark.parametrize("basis,source", [("observed", "audio"), ("stated", "visual")])
def test_declared_claim_basis_requires_matching_evidence(basis, source):
    with pytest.raises(ValueError, match="evidence"):
        claim("A claim", basis=basis, source=source)


def test_inferred_advice_is_preserved_for_review_not_presented_as_troubleshooting(draft):
    draft.troubleshooting = [claim("Unproven PATH advice", basis="inferred")]
    text = markdown(draft)
    treatment = text.split("## Lỗi và cách xử lý", 1)[1].split("## Điểm chưa rõ", 1)[0]
    assert "Unproven PATH advice" not in treatment
    assert "chưa đủ bằng chứng: Unproven PATH advice" in text
    assert draft.troubleshooting[0].text == "Unproven PATH advice"
    assert has_review_claims(draft)
    draft.troubleshooting = [claim("Explicit remedy", basis="stated", source="audio")]
    assert "Explicit remedy" in markdown(draft).split("## Điểm chưa rõ", 1)[0]
    assert not has_review_claims(draft)


def test_legacy_claims_require_review_without_assuming_support():
    legacy = claim("Legacy").model_dump(exclude={"basis", "scope", "quote", "on_screen_text"})
    parsed = SourceClaim.model_validate(legacy)
    assert parsed.basis == "unclear" and parsed.scope == "clip"


def test_later_chunk_state_cannot_become_a_global_prerequisite(draft):
    first, second = draft.model_copy(deep=True), draft.model_copy(deep=True)
    first.prerequisites = [claim("Initial requirement")]
    second.prerequisites = [claim("Installation already running")]
    second.uncertainties[0].start_sec, second.uncertainties[0].end_sec = 0, 1
    merged = assemble([(0, first), (8, second)], 18)
    assert merged.prerequisites[0].scope == "tutorial"
    assert merged.prerequisites[1].scope == "clip"
    assert merged.prerequisites[1].evidence_spans[0].start_sec == 8
    assert second.prerequisites[0].scope == "tutorial"
    text = markdown(merged)
    preparation = text.split("## Chuẩn bị", 1)[1].split("## Công cụ", 1)[0]
    assert "Initial requirement" in preparation and "Installation already running" not in preparation
    assert "Installation already running" in text.split("## Ngữ cảnh theo đoạn", 1)[1]
    assert "Trong phạm vi đoạn nguồn [00:00:08]" in text


def test_evidence_prefers_supported_result_frame_and_keeps_candidate_data(draft):
    step = draft.steps[0]
    step.expected_result = "Result becomes visible"
    step.screenshot_candidates_sec = [0.5, 1.8]
    assert evidence_timestamp(step, 10) == (1.8, False)
    step.evidence_spans[0].end_sec = 1
    assert evidence_timestamp(step, 10) == (0.5, False)
    assert step.screenshot_candidates_sec == [0.5, 1.8]
    step.evidence_spans[0].source = "audio"
    assert evidence_timestamp(step, 10) == (None, True)


def test_evidence_fallback_stays_inside_both_step_and_visual_span(draft):
    step = draft.steps[0]
    step.start_sec, step.end_sec = 1, 2
    step.evidence_spans[0].start_sec, step.evidence_spans[0].end_sec = 0, 1.5
    step.screenshot_candidates_sec = []
    assert evidence_timestamp(step, 10) == (1.25, False)
    step.evidence_spans[0].end_sec = 0.5
    assert evidence_timestamp(step, 10) == (None, False)


def test_conflicting_candidate_uses_last_frame_of_latest_visual_evidence(draft):
    step = draft.steps[0]
    step.start_sec, step.end_sec = 136, 154
    step.expected_result = "Version shown"
    step.screenshot_candidates_sec = [148]
    span = step.evidence_spans[0]
    step.evidence_spans = [
        span.model_copy(update={"start_sec": 137, "end_sec": 140}),
        span.model_copy(update={"start_sec": 149, "end_sec": 160}),
        span.model_copy(update={"start_sec": 150, "end_sec": 153, "source": "audio"}),
    ]
    assert evidence_timestamp(step, 216) == (154, True)
    step.evidence_spans[1].end_sec = 152
    assert evidence_timestamp(step, 216) == (152, True)


def test_conflict_fallback_stays_before_end_of_file(draft):
    step = draft.steps[0]
    step.start_sec, step.end_sec = 0, 10
    step.expected_result = "Saved file"
    step.screenshot_candidates_sec = [5]
    step.evidence_spans[0].start_sec, step.evidence_spans[0].end_sec = 9, 10
    assert evidence_timestamp(step, 10) == (9.5, True)


def test_previous_context_is_bounded_and_converts_times_once(draft):
    draft.steps = [draft.steps[0].model_copy(deep=True) for _ in range(5)]
    for index, step in enumerate(draft.steps):
        step.title = str(index) * 300
        step.end_sec = index + 1
    data = clip_metadata("source.mp4", 1, [NS(start_sec=0), NS(start_sec=115)], 216, [(10, draft)])
    assert data["clip_index"] == 2 and data["clip_start_sec"] == 115
    assert len(data["previous_steps"]) == 3
    assert all(len(s["title"]) == 200 for s in data["previous_steps"])
    assert data["previous_steps"][-1]["end_sec"] == 15


def test_later_clips_receive_first_clip_domain(draft):
    cooking = draft.model_copy(update={"domain": "cooking"})
    later = draft.model_copy(update={"domain": "repair"})
    chunks = [NS(start_sec=0), NS(start_sec=115), NS(start_sec=230)]
    assert clip_metadata("x.mp4", 1, chunks[:2], 216, [(0, cooking)])["domain"] == "cooking"
    assert clip_metadata("x.mp4", 2, chunks, 345, [(0, cooking), (115, later)])["domain"] == "cooking"


def test_first_clip_has_no_domain_context(draft):
    assert clip_metadata("x.mp4", 0, [NS(start_sec=0), NS(start_sec=115)], 216, [])["domain"] is None


def test_repair_carries_exact_previous_response_and_refuses_oversized_input():
    import json
    from app.core.errors import AppError

    original = '{"title":"Bản nháp", "steps": invalid}'
    payload = json.loads(repair_payload(120, [{"loc": ["steps"], "type": "json_invalid"}], original))
    assert payload["previous_output"] == original and payload["clip_duration_sec"] == 120
    with pytest.raises(AppError) as exc:
        repair_payload(120, [], "a" * (128 * 1024 + 1))
    assert exc.value.code == "REPAIR_INPUT_LIMIT"


def test_same_tool_from_later_chunk_is_merged_not_repeated(draft):
    from app.schemas.tutorial_v2 import Equipment

    def tool(name, version, start):
        span = {"start_sec": start, "end_sec": start + 1, "source": "visual", "description": "Tool"}
        return Equipment.model_validate({"name": name, "spec": version, "evidence_spans": [span]})

    first, second = draft.model_copy(deep=True), draft.model_copy(deep=True)
    first.equipment = [tool("Python", "3.13.0", 0)]
    second.equipment = [tool("python ", "3.13.0", 1), tool("IDLE", None, 2)]
    merged = assemble([(0, first), (8, second)], 20)
    assert [(t.name, t.spec) for t in merged.equipment] == [("Python", "3.13.0"), ("IDLE", None)]
    assert [s.start_sec for s in merged.equipment[0].evidence_spans] == [0, 9]


def grounded(text, start=0):
    span = {"start_sec": start, "end_sec": start + 1, "source": "audio", "description": "Spoken"}
    return GroundedClaim.model_validate(
        {"text": text, "basis": "stated", "scope": "tutorial", "quote": text, "evidence_spans": [span]}
    )


def material(name, start=0):
    from app.schemas.tutorial_v2 import Material

    span = {"start_sec": start, "end_sec": start + 1, "source": "visual", "description": "Shown"}
    return Material.model_validate(
        {
            "name": name,
            "quantity": None,
            "unit": None,
            "note": None,
            "evidence_spans": [span],
            "basis": "observed",
            "quote": None,
            "on_screen_text": None,
        }
    )


def test_assemble_carries_safety_and_materials_from_every_part(draft):
    first, second = draft.model_copy(deep=True), draft.model_copy(deep=True)
    first.safety, first.materials = [grounded("Unplug first")], [material("Flour")]
    second.safety, second.materials = [grounded("Wear gloves")], [material("Sugar", 2)]
    merged = assemble([(0, first), (8, second)], 20)
    assert [c.text for c in merged.safety] == ["Unplug first", "Wear gloves"]
    assert [m.name for m in merged.materials] == ["Flour", "Sugar"]
    assert merged.safety[1].evidence_spans[0].start_sec == 8
    assert merged.materials[1].evidence_spans[0].start_sec == 10


def test_assemble_takes_document_fields_from_first_part_and_dumps_yield_by_alias(draft):
    first, second = draft.model_copy(deep=True), draft.model_copy(deep=True)
    first.yield_, first.domain, first.is_tutorial = "4 người ăn", "cooking", True
    second.yield_, second.domain = "other yield", "repair"
    second.is_tutorial, second.not_tutorial_reason = False, "Not a tutorial"
    merged = assemble([(0, first), (8, second)], 20)
    assert merged.yield_ == "4 người ăn" and merged.domain == "cooking" and merged.is_tutorial
    dumped = merged.model_dump(by_alias=True)
    assert dumped["yield"] == "4 người ăn" and "yield_" not in dumped


def test_exact_input_without_language_renders_plain_fence(draft):
    from app.schemas.tutorial_v2 import ExactInput

    step = draft.steps[0]
    step.exact_inputs = [
        ExactInput.model_validate(
            {
                "kind": "text",
                "language": None,
                "text": "pinch of salt",
                "completeness": "complete",
                "evidence_spans": [s.model_dump() for s in step.evidence_spans],
                "basis": "unclear",
                "quote": None,
                "on_screen_text": None,
            }
        )
    ]
    lines = markdown(draft).splitlines()
    index = lines.index("pinch of salt")
    assert lines[index - 1] == "```" and lines[index + 1] == "```"
