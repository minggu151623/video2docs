from types import SimpleNamespace
import pytest
from app.schemas.tutorial import TutorialDraftV1
from app.providers.mock import MockProvider
from app.services.media import plan_chunks
from app.services.documents import assemble, escape
from app.services.budget import normalized_usage, cost, check_budget
from app.core.config import Settings
from app.core.errors import AppError
from app.core.storage import safe_path, atomic_write
from app.services.exports import safe_html, markdown_images


@pytest.mark.parametrize("duration,count", [(0, 0), (1, 1), (299, 1), (300, 1), (301, 2), (1200, 5)])
def test_chunk_boundaries(duration, count):
    plan = plan_chunks(duration)
    assert len(plan) == count
    if plan:
        assert plan[0][0] == 0 and plan[-1][1] == duration
        assert all(0 < b - a <= 300 for a, b in plan)
        assert all(plan[i][1] - plan[i + 1][0] == 5 for i in range(len(plan) - 1))


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf")])
def test_invalid_chunk_timeline(duration):
    with pytest.raises(ValueError):
        plan_chunks(duration)


@pytest.fixture
def draft():
    return TutorialDraftV1.model_validate_json(
        MockProvider(Settings(ai_provider="mock")).analyze(None, 5, "vi", {})["text"], context={"duration": 5}
    )


@pytest.mark.parametrize(
    "mutation", ["nan", "infinity", "outside", "eof", "extra", "reason", "span", "empty"]
)
def test_reject_invalid_schema(draft, mutation):
    data = draft.model_dump()
    if mutation == "nan":
        data["steps"][0]["start_sec"] = float("nan")
    if mutation == "infinity":
        data["steps"][0]["end_sec"] = float("inf")
    if mutation == "outside":
        data["steps"][0]["end_sec"] = 6
    if mutation == "eof":
        data["steps"][0]["screenshot_candidates_sec"] = [5]
    if mutation == "extra":
        data["steps"][0]["url"] = "http://example.com"
    if mutation == "reason":
        data["steps"][0]["review_reason"] = None
    if mutation == "span":
        data["steps"][0]["evidence_spans"][0]["end_sec"] = 100
    if mutation == "empty":
        data["steps"], data["uncertainties"] = [], []
    with pytest.raises(ValueError):
        TutorialDraftV1.model_validate(data, context={"duration": 5})


def test_partial_command_requires_review(draft):
    data = draft.model_dump()
    data["steps"][0].update(
        needs_review=False,
        review_reason=None,
        commands=[
            {
                "language": "sh",
                "text": "npm ???",
                "completeness": "partial",
                "evidence_spans": data["steps"][0]["evidence_spans"],
            }
        ],
    )
    parsed = TutorialDraftV1.model_validate(data, context={"duration": 5})
    assert parsed.steps[0].needs_review and parsed.steps[0].review_reason


def test_assembly_preserves_close_steps_and_dedupes_exact(draft):
    first = draft.model_copy(deep=True)
    first.steps[0].start_sec, first.steps[0].end_sec = 2, 4
    first.steps[0].evidence_spans[0].start_sec, first.steps[0].evidence_spans[0].end_sec = 2, 4
    first.steps[0].screenshot_candidates_sec = [3]
    second = first.model_copy(deep=True)
    second.steps[0].start_sec, second.steps[0].end_sec = 0, 2
    second.steps[0].evidence_spans[0].start_sec, second.steps[0].evidence_spans[0].end_sec = 0, 2
    second.steps[0].screenshot_candidates_sec = [1]
    result = assemble([(0, first), (2, second)], 7)
    assert len(result.steps) == 1
    second.steps[0].title += " khác"
    result = assemble([(0, first), (2, second)], 7)
    assert len(result.steps) == 2 and result.steps[1].needs_review
    assert result.steps[1].start_sec == 2 and result.steps[1].screenshot_candidates_sec == [3]


def test_no_silent_limit_truncation(draft):
    with pytest.raises(AppError, match="giới hạn"):
        assemble([(0, draft), (5, draft)], 10, 1)


def test_unknown_usage_and_thinking_not_double_counted():
    assert normalized_usage(None) is None
    usage = normalized_usage(
        {"total_input_tokens": 100000, "total_output_tokens": 4000, "total_thought_tokens": 1000}
    )
    price = SimpleNamespace(
        effective_from="2026-10-20", effective_to="2026-12-31", input_rate=0.75, output_rate=3.75
    )
    assert cost(usage, price, "2026-10-20") == pytest.approx(0.09375)
    already_included = normalized_usage(
        {"total_input_tokens": 100000, "total_output_tokens": 5000, "total_thought_tokens": 1000},
        output_includes_thinking=True,
    )
    assert cost(already_included, price, "2026-10-20") == pytest.approx(0.09375)
    assert cost(usage, price, "2027-01-01") is None
    assert cost(None, price, "2026-10-20") is None


@pytest.mark.parametrize(
    "args,code",
    [
        ((12, 1, 12, 0, None, 1, True), "ATTEMPT_LIMIT"),
        ((0, 1, 12, 0, None, 1, False), "COST_UNKNOWN"),
        ((0, 1, 12, 0.9, 0.2, 1, True), "BUDGET_EXCEEDED"),
    ],
)
def test_bounded_budget(args, code):
    with pytest.raises(AppError) as exc:
        check_budget(*args)
    assert exc.value.code == code


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "x/../../secret"])
def test_traversal(tmp_path, path):
    with pytest.raises(AppError):
        safe_path(tmp_path, path)


def test_symlink(tmp_path):
    (tmp_path / "link").symlink_to("/tmp")
    with pytest.raises(AppError):
        safe_path(tmp_path, "link/a")


def test_atomic_write_and_escaping(tmp_path):
    atomic_write(tmp_path / "a", b"complete")
    assert (tmp_path / "a").read_bytes() == b"complete"
    assert not list(tmp_path.glob("*.partial"))
    assert "<script>" not in escape("<script>")


def test_sanitized_html_and_no_remote_network():
    html = safe_html(
        "<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n[remote](https://evil.example)", {}
    )
    assert "<script>" not in html and 'href="https' not in html and 'href="javascript' not in html
    assert markdown_images("![x](https://evil.example/x)") == ["https://evil.example/x"]


def test_invalid_settings(tmp_path):
    for values in (
        {"chunk_seconds": 2, "chunk_overlap_seconds": 2},
        {"enable_agentic_video": True},
        {"gemini_store_interactions": True},
        {"database_url": "sqlite:////tmp/outside.sqlite3"},
    ):
        with pytest.raises(ValueError):
            Settings(**values)
