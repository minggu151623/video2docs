from copy import deepcopy

import pytest

from app.core.config import Settings
from app.providers.mock import MockProvider
from app.schemas.tutorial_v2 import TutorialDraftV2
from app.services.documents import assemble, render_markdown


@pytest.fixture
def pair():
    draft = TutorialDraftV2.model_validate_json(
        MockProvider(Settings(ai_provider="mock")).analyze(None, 10, "vi", {})["text"],
        context={"duration": 10},
    ).model_dump(by_alias=True)
    step = draft["steps"][0]
    step.update(
        start_sec=0, end_sec=10, title="Mix", actions=["Mix slowly"],
        expected_result="Smooth mixture", parameters=[], exact_inputs=[], warnings=[], tips=[],
        evidence_spans=[dict(start_sec=0, end_sec=10, source="visual", description="Mixing")],
        screenshot_candidates_sec=[1], needs_review=False, review_reason=None,
    )
    draft["steps"] = [step]
    return deepcopy(draft), deepcopy(draft)


def stitch(pair, offset=8):
    parts = [TutorialDraftV2.model_validate(p, context={"duration": 10}) for p in pair]
    before = [p.model_dump() for p in parts]
    result = assemble([(0, parts[0]), (offset, parts[1])], 20)
    assert [p.model_dump() for p in parts] == before
    return result


def warning(text="Do not overmix"):
    return dict(
        text=text, basis="stated", scope="clip", quote=text, on_screen_text=None,
        evidence_spans=[dict(start_sec=0, end_sec=2, source="audio", description="Warning")],
    )


def test_identical_boundary_steps_keep_full_timeline_and_evidence(pair):
    merged = stitch(pair)
    assert len(merged.steps) == 1
    step = merged.steps[0]
    assert (step.start_sec, step.end_sec) == (0, 18)
    assert [(s.start_sec, s.end_sec) for s in step.evidence_spans] == [(0, 10), (8, 18)]
    assert step.screenshot_candidates_sec == [1, 9]
    assert not step.needs_review


@pytest.mark.parametrize("field", ["warnings", "tips", "parameters", "exact_inputs", "expected_result"])
def test_same_actions_never_discard_new_details(pair, field):
    extra = {
        "warnings": [warning()], "tips": [warning("Chill first")],
        "parameters": [dict(name="Time", value="5", unit="min", basis="stated", quote="5 min",
                            on_screen_text=None, evidence_spans=warning()["evidence_spans"])],
        "exact_inputs": [dict(kind="command", language="sh", text="Run --CaseSensitive",
                              completeness="complete", basis="stated", quote="Run --CaseSensitive",
                              on_screen_text=None, evidence_spans=warning()["evidence_spans"])],
        "expected_result": "Stiff peaks",
    }[field]
    pair[1]["steps"][0][field] = extra
    merged = stitch(pair)
    assert len(merged.steps) == 2
    assert all(s.needs_review for s in merged.steps)
    assert getattr(merged.steps[1], field)
    assert "c1-" in merged.steps[1].review_reason


def test_same_title_with_different_actions_is_flagged_without_losing_content(pair):
    pair[0]["steps"][0]["tips"] = [warning("Chill first")]
    pair[1]["steps"][0]["actions"] = ["Stop once stiff peaks hold"]
    pair[1]["steps"][0]["warnings"] = [warning()]
    merged = stitch(pair)
    assert len(merged.steps) == 2 and all(s.needs_review for s in merged.steps)
    assert merged.steps[0].tips[0].text == "Chill first"
    assert merged.steps[1].warnings[0].text == "Do not overmix"


def test_review_reasons_and_nested_source_spans_survive_merging(pair):
    for p, reason in zip(pair, ("Check timing", "Check result")):
        p["steps"][0].update(warnings=[warning()], needs_review=True, review_reason=reason)
    step = stitch(pair).steps[0]
    assert step.needs_review and step.review_reason == "Check timing\nCheck result"
    assert [s.start_sec for s in step.warnings[0].evidence_spans] == [0, 8]


@pytest.mark.parametrize("offset", [10, 11])
def test_separate_repetitions_are_not_merged_or_flagged(pair, offset):
    # Both local clips must fit the global duration used by stitch().
    for p in pair:
        p["steps"][0]["end_sec"] = 9
        p["steps"][0]["evidence_spans"][0]["end_sec"] = 9
    result = stitch(pair, offset)
    assert len(result.steps) == 2 and not any(s.needs_review for s in result.steps)


def test_steps_in_same_clip_are_never_silently_dropped(pair):
    step = deepcopy(pair[0]["steps"][0])
    step["local_id"] = "second"
    pair[0]["steps"].append(step)
    draft = TutorialDraftV2.model_validate(pair[0], context={"duration": 10})
    assert len(assemble([(0, draft)], 10).steps) == 2


@pytest.mark.parametrize("overflow", ["frames", "spans", "nested_spans"])
def test_merge_limits_retain_both_steps_instead_of_truncating(pair, overflow):
    for p in pair:
        step = p["steps"][0]
        if overflow == "frames":
            step["screenshot_candidates_sec"] = [1, 2]
        else:
            if overflow == "nested_spans":
                step["warnings"] = [warning()]
                step = step["warnings"][0]
            step["evidence_spans"] = [
                dict(start_sec=i, end_sec=i + 1, source="both", description="Source") for i in range(3)
            ]
    result = stitch(pair)
    assert len(result.steps) == 2
    assert all(s.needs_review for s in result.steps)


def test_same_title_does_not_normalize_case_sensitive_content(pair):
    pair[0]["steps"][0]["actions"] = ["Set PATH"]
    pair[1]["steps"][0]["actions"] = ["Set path"]
    assert len(stitch(pair).steps) == 2


def test_boundary_warning_is_visible_in_english_markdown(pair):
    from types import SimpleNamespace as NS

    for p in pair:
        p["language"] = "en"
    pair[1]["steps"][0]["actions"] = ["Stop mixing"]
    draft = stitch(pair)
    text = render_markdown(draft, NS(original_name="test.mp4", duration_sec=20),
                           "mock", NS(id="g", created_at="today"), {})
    assert "May repeat or continue step" in text


def test_prior_review_reason_is_not_overwritten_at_limit(pair):
    pair[0]["steps"][0].update(needs_review=True, review_reason="X" * 2000)
    pair[1]["steps"][0]["actions"] = ["Stop mixing"]
    assert stitch(pair).steps[0].review_reason == "X" * 2000
