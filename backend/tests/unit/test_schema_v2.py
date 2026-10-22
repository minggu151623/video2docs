import json
import pytest
from pydantic import ValidationError
from app.core.config import Settings
from app.providers.mock import MockProvider
from app.schemas.tutorial import TutorialDraftV1
from app.schemas.tutorial_v2 import (
    ExactInput,
    GroundedClaim,
    Material,
    Parameter,
    TutorialDraftV2,
    load_draft,
)


def span(source="both"):
    return {"start_sec": 0, "end_sec": 2, "source": source, "description": "Source"}


def claim(**extra):
    return {"text": "Claim", "evidence_spans": [span()], "basis": "observed", "scope": "clip", **extra}


@pytest.fixture
def v2_data():
    text = MockProvider(Settings(ai_provider="mock")).analyze(None, 10, "vi", {})["text"]
    return json.loads(text)


def test_stated_claim_requires_quote():
    with pytest.raises(ValidationError, match="quote"):
        GroundedClaim.model_validate(claim(basis="stated", quote=None, on_screen_text=None))
    assert GroundedClaim.model_validate(claim(basis="stated", quote="Nguyên văn", on_screen_text=None))


def test_observed_value_requires_on_screen_text():
    base = {"evidence_spans": [span()], "basis": "observed", "quote": None, "on_screen_text": None}
    with pytest.raises(ValidationError, match="on_screen_text"):
        Parameter.model_validate({"name": "Nhiệt độ", "value": "180", "unit": "°C", **base})
    material = {"name": "Bột", "quantity": "200", "unit": "g", "note": None, **base}
    with pytest.raises(ValidationError, match="on_screen_text"):
        Material.model_validate(material)
    assert Material.model_validate({**material, "quantity": None, "unit": None})
    exact = {"kind": "command", "language": "sh", "text": "ls", "completeness": "complete", **base}
    with pytest.raises(ValidationError, match="on_screen_text"):
        ExactInput.model_validate(exact)
    assert ExactInput.model_validate({**exact, "on_screen_text": "$ ls"})


ITEMS = {
    "material": (Material, {"name": "Bột", "quantity": None, "unit": None, "note": None}),
    "parameter": (Parameter, {"name": "Nhiệt độ", "value": "180", "unit": "°C"}),
    "exact_input": (
        ExactInput,
        {"kind": "command", "language": "sh", "text": "ls", "completeness": "complete"},
    ),
}


def grounded_item(name, source, basis, **extra):
    model, fields = ITEMS[name]
    base = {"evidence_spans": [span(source)], "basis": basis, "quote": None, "on_screen_text": None}
    return model.model_validate({**fields, **base, **extra})


@pytest.mark.parametrize("name", ITEMS)
def test_stated_item_requires_audio_evidence(name):
    with pytest.raises(ValidationError, match="audio"):
        grounded_item(name, "visual", "stated", quote="Nguyên văn")
    assert grounded_item(name, "audio", "stated", quote="Nguyên văn")
    assert grounded_item(name, "both", "stated", quote="Nguyên văn")


@pytest.mark.parametrize("name", ITEMS)
def test_observed_item_requires_visual_evidence(name):
    with pytest.raises(ValidationError, match="visual"):
        grounded_item(name, "audio", "observed", on_screen_text="180")
    assert grounded_item(name, "visual", "observed", on_screen_text="180")
    assert grounded_item(name, "both", "observed", on_screen_text="180")


@pytest.mark.parametrize("name", ITEMS)
def test_unclear_item_needs_no_modality(name):
    assert grounded_item(name, "audio", "unclear")
    assert grounded_item(name, "visual", "inferred")


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_whitespace_only_verbatim_text_counts_as_missing(blank):
    with pytest.raises(ValidationError, match="quote"):
        GroundedClaim.model_validate(claim(basis="stated", quote=blank, on_screen_text=None))
    with pytest.raises(ValidationError, match="quote"):
        grounded_item("parameter", "audio", "stated", quote=blank)
    with pytest.raises(ValidationError, match="on_screen_text"):
        grounded_item("parameter", "visual", "observed", on_screen_text=blank)
    with pytest.raises(ValidationError, match="on_screen_text"):
        grounded_item("exact_input", "visual", "observed", on_screen_text=blank)


def test_observed_action_claim_needs_no_text():
    parsed = GroundedClaim.model_validate(claim(quote=None, on_screen_text=None))
    assert parsed.basis == "observed"


def test_not_tutorial_requires_reason_and_no_steps(v2_data):
    data = {**v2_data, "is_tutorial": False, "not_tutorial_reason": None}
    with pytest.raises(ValidationError, match="not_tutorial_reason"):
        TutorialDraftV2.model_validate(data, context={"duration": 10})
    data["not_tutorial_reason"] = "Bài giảng, không có thao tác."
    with pytest.raises(ValidationError, match="must not contain steps"):
        TutorialDraftV2.model_validate(data, context={"duration": 10})
    data["steps"] = []
    assert TutorialDraftV2.model_validate(data, context={"duration": 10}).is_tutorial is False


def test_yield_round_trips_by_alias(v2_data):
    draft = TutorialDraftV2.model_validate({**v2_data, "yield": "4 người ăn"}, context={"duration": 10})
    assert draft.yield_ == "4 người ăn"
    dumped = draft.model_dump(by_alias=True)
    assert dumped["yield"] == "4 người ăn" and "yield_" not in dumped
    assert TutorialDraftV2.model_validate(dumped, context={"duration": 10}).yield_ == "4 người ăn"
    assert "yield" in TutorialDraftV2.model_json_schema()["properties"]


def test_checkpoint_json_round_trips_through_load_draft(v2_data):
    draft = TutorialDraftV2.model_validate({**v2_data, "yield": "2 phần"}, context={"duration": 10})
    stored = draft.model_dump_json(by_alias=True).encode()
    assert json.loads(stored)["yield"] == "2 phần"
    assert load_draft(stored, duration=10).yield_ == "2 phần"


def test_limits(v2_data):
    material = {
        "name": "Bột",
        "quantity": None,
        "unit": None,
        "note": None,
        "evidence_spans": [span()],
        "basis": "unclear",
        "quote": None,
        "on_screen_text": None,
    }
    with pytest.raises(ValidationError):
        TutorialDraftV2.model_validate({**v2_data, "materials": [material] * 61}, context={"duration": 10})
    assert TutorialDraftV2.model_validate({**v2_data, "materials": [material] * 60}, context={"duration": 10})
    parameter = {
        "name": "n",
        "value": "1",
        "unit": None,
        "evidence_spans": [span()],
        "basis": "unclear",
        "quote": None,
        "on_screen_text": None,
    }
    v2_data["steps"][0]["parameters"] = [parameter] * 11
    with pytest.raises(ValidationError):
        TutorialDraftV2.model_validate(v2_data, context={"duration": 10})


def v1_json():
    s = span("visual")
    return {
        "schema_version": "1.0",
        "title": "Cài Python",
        "summary": "Tóm tắt",
        "language": "vi",
        "objectives": ["Cài đặt"],
        "prerequisites": [
            {"text": "Windows", "evidence_spans": [s], "basis": "observed", "scope": "tutorial"},
            {
                "text": "Nói rõ",
                "evidence_spans": [span("audio")],
                "basis": "stated",
                "scope": "clip",
            },
        ],
        "tools": [{"name": "Python", "version": "3.13.0", "evidence_spans": [s]}],
        "steps": [
            {
                "local_id": "s1",
                "title": "Chạy",
                "start_sec": 0,
                "end_sec": 2,
                "actions": ["Gõ lệnh"],
                "expected_result": None,
                "commands": [
                    {
                        "language": "sh",
                        "text": "python --version",
                        "completeness": "complete",
                        "evidence_spans": [s],
                    }
                ],
                "evidence_spans": [s],
                "screenshot_candidates_sec": [1],
                "needs_review": False,
                "review_reason": None,
            }
        ],
        "troubleshooting": [],
        "uncertainties": [],
    }


def test_load_draft_upgrades_v1():
    raw = json.dumps(v1_json())
    TutorialDraftV1.model_validate_json(raw, context={"duration": 10})
    draft = load_draft(raw, duration=10)
    assert draft.schema_version == "2.0" and draft.domain == "software" and draft.is_tutorial
    assert draft.equipment[0].spec == "3.13.0"
    assert draft.steps[0].exact_inputs[0].kind == "command"
    assert draft.steps[0].exact_inputs[0].basis == "unclear"
    assert draft.materials == [] and draft.safety == [] and draft.yield_ is None
    assert draft.prerequisites[0].basis == "observed" and draft.prerequisites[1].basis == "unclear"
    assert draft.steps[0].parameters == []


def test_upgrade_does_not_mutate_input():
    from app.schemas.tutorial_v2 import upgrade_v1

    data = v1_json()
    upgrade_v1(data)
    assert data == v1_json()
