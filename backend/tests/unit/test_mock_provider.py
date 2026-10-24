import json

from app.core.config import Settings
from app.providers.mock import MockProvider
from app.schemas.tutorial_v2 import TutorialDraftV2
from app.services.verification.matcher import iter_grounded_items

PROVIDER = MockProvider(Settings(ai_provider="mock"))


def analyze(name=None, duration=10):
    metadata = {} if name is None else {"original_name": name}
    text = PROVIDER.analyze(None, duration, "vi", metadata)["text"]
    return TutorialDraftV2.model_validate_json(text, context={"duration": duration})


def test_default_output_has_a_stated_parameter_and_an_observed_material():
    draft = analyze("tutorial.mp4")
    assert draft.is_tutorial and len(draft.steps) == 1
    parameter = draft.steps[0].parameters[0]
    assert parameter.basis == "stated" and parameter.quote
    assert any(s.source in ("audio", "both") for s in parameter.evidence_spans)
    material = draft.materials[0]
    assert material.basis == "observed" and material.on_screen_text
    assert any(s.source in ("visual", "both") for s in material.evidence_spans)
    assert [path for path, _, _ in iter_grounded_items(draft)] == ["materials/0", "steps/0/parameters/0"]


def test_not_tutorial_name_prefix_returns_a_non_tutorial_draft():
    draft = analyze("mock-not-tutorial-vlog.mp4")
    assert draft.is_tutorial is False
    assert draft.steps == []
    assert draft.not_tutorial_reason == "MOCK: không phải tutorial"
    assert json.loads(PROVIDER.analyze(None, 5, "vi", {"original_name": "mock-not-tutorial"})["text"])


def test_other_names_and_missing_metadata_stay_tutorials():
    assert analyze("my-mock-not-tutorial.mp4").is_tutorial
    assert analyze(None).is_tutorial


def test_two_steps_name_adds_a_step_without_grounded_items():
    draft = analyze("mock-two-steps.mp4")
    assert [s.local_id for s in draft.steps] == ["fixture-step", "fixture-step-2"]
    paths = [path for path, _, _ in iter_grounded_items(draft)]
    assert paths == ["materials/0", "steps/0/parameters/0"]
