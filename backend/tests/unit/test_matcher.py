import json
import pytest
from app.core.config import Settings
from app.providers.mock import MockProvider
from app.schemas.tutorial_v2 import ExactInput, GroundedClaim, Material, Parameter, TutorialDraftV2
from app.schemas.verification import Transcript, Word
from app.services.verification.matcher import (
    contains_numbers,
    exact_input_matches,
    fuzzy_contains,
    iter_grounded_items,
    normalize,
    transcript_window,
    verify_item,
)
from app.services.verification.numbers import digit_runs

SETTINGS = Settings(ai_provider="mock")


def span(start=10, end=12, source="both"):
    return {"start_sec": start, "end_sec": end, "source": source, "description": "Source"}


def transcript(text, at=10.0, language="vi"):
    words = [Word(start=at + i * 0.4, end=at + i * 0.4 + 0.3, text=w) for i, w in enumerate(text.split())]
    return Transcript(language=language, words=words)


def material(quantity="200", quote="200 gram bột", basis="stated", on_screen_text=None, spans=None):
    return Material(
        name="Bột",
        quantity=quantity,
        unit="g",
        note=None,
        evidence_spans=spans or [span()],
        basis=basis,
        quote=quote,
        on_screen_text=on_screen_text,
    )


def claim(basis="stated", quote="cẩn thận nóng", on_screen_text=None, text="Cẩn thận nóng", spans=None):
    return GroundedClaim(
        text=text,
        evidence_spans=spans or [span()],
        basis=basis,
        quote=quote,
        on_screen_text=on_screen_text,
    )


def exact(text="python --version", basis="observed", on_screen_text="python --version", quote=None):
    return ExactInput(
        kind="command",
        language="bash",
        text=text,
        completeness="complete",
        evidence_spans=[span(source="visual")],
        basis=basis,
        quote=quote,
        on_screen_text=on_screen_text,
    )


def parameter(value="180", on_screen_text="Nướng ở 180°C", basis="observed", quote=None, spans=None):
    return Parameter(
        name="Nhiệt độ",
        value=value,
        unit="°C",
        evidence_spans=spans or [span(source="visual")],
        basis=basis,
        quote=quote,
        on_screen_text=on_screen_text,
    )


def verify(item, tr=None, ocr=None):
    return verify_item("p", item, tr, ocr, SETTINGS)


@pytest.mark.parametrize(
    "text,lang,expected",
    [
        ("1,5 kg", "vi", ["1", "5"]),
        ("1/2 chén", "vi", ["1", "2"]),
        ("2-3 phút", "vi", ["2", "3"]),
        ("một trăm tám mươi độ", "vi", ["180"]),
        ("hai mươi lăm", "vi", ["25"]),
        ("one hundred eighty degrees", "en", ["180"]),
        ("180°C", None, ["180"]),
        ("007 và 0,5", "vi", ["7", "0", "5"]),
        ("hai trăm linh năm gram", "vi", ["205"]),
        ("hai nghìn năm trăm", "vi", ["2500"]),
        ("mười lăm phút", "vi", ["15"]),
        ("twenty five and one hundred and five", "en", ["25", "105"]),
        ("two three minutes", "en", ["2", "3"]),
        ("hai trăm năm mươi gram", "ko", []),
        ("1.000 gram", "vi", ["1", "0"]),
    ],
)
def test_digit_runs(text, lang, expected):
    assert digit_runs(text, lang) == expected


def test_korean_quote_matches_korean_transcript():
    tr = transcript("네 이제 설탕 두 큰술 넣어주세요 그리고", language="ko")
    out = verify(claim(quote="설탕 두 큰술", text="Thêm đường"), tr)
    assert (out.status, out.method) == ("verified", "asr")
    assert out.matched_text and "설탕" in out.matched_text
    assert out.matched_sec == pytest.approx(10.0 + 2 * 0.4)


def test_number_mismatch_never_verifies():
    tr = transcript("cho hai trăm năm mươi gram bột vào tô")
    out = verify(material(), tr)
    assert out.status == "unverified"
    assert "con số" in out.reason


def test_spelled_number_matches_digits():
    tr = transcript("cho hai trăm gram bột vào tô")
    out = verify(material(), tr)
    assert (out.status, out.method) == ("verified", "asr")
    assert out.checked_range == (5.0, 17.0)


def test_cut_number_does_not_verify():
    tr = transcript("cho 1200 gram bột vào tô")
    assert verify(material(quantity="200", quote="200 gram bột"), tr).status == "unverified"
    tr = transcript("cho 1,5 kg bột vào tô")
    assert verify(material(quantity="5", quote="5 kg bột"), tr).status == "unverified"


def test_value_missing_from_own_quote():
    tr = transcript("cho một chén bột")
    out = verify(material(quantity="200", quote="một chén bột"), tr)
    assert out.status == "unverified"
    assert out.reason == "giá trị không có trong nguyên văn"


def test_value_must_be_in_the_text_of_its_own_basis():
    tr = transcript("cho bột vào tô")
    item = material(quantity="200", quote="cho bột vào tô", on_screen_text="200 g")
    assert verify(item, tr).reason == "giá trị không có trong nguyên văn"


def test_quote_outside_window_is_unverified():
    tr = transcript("cẩn thận nóng", at=40.0)
    out = verify(claim(), tr)
    assert out.status == "unverified"
    assert out.checked_range == (5.0, 17.0)


def test_each_span_is_checked_separately():
    tr = transcript("cẩn thận nóng", at=30.0)
    far = [span(0, 1), span(60, 61)]
    out = verify(claim(spans=far), tr)
    assert out.status == "unverified"
    assert out.checked_range == (0.0, 66.0)
    near = [span(0, 1), span(29, 31)]
    out = verify(claim(spans=near), tr)
    assert out.status == "verified"
    assert out.matched_sec == 30.0


def test_visual_only_spans_are_not_used_for_quotes():
    tr = transcript("cẩn thận nóng", at=10.0)
    out = verify(claim(spans=[span(source="both"), span(0, 1, "visual")]), tr)
    assert out.status == "verified"
    assert out.checked_range == (5.0, 17.0)


def test_exact_input_ignores_whitespace_only():
    assert verify(exact(), None, [(11.0, "$ python  --version\n3.12")]).status == "verified"
    out = verify(exact(), None, [(11.0, "$ python --versoin")])
    assert out.status == "unverified"


def test_exact_input_keeps_case_and_digits():
    assert (
        verify(exact(text="ls -la", on_screen_text="ls -la"), None, [(11.0, "LS -LA")]).status == "unverified"
    )
    one = exact(text="sleep 5", on_screen_text="sleep 5")
    assert verify(one, None, [(11.0, "$ sleep 50")]).status == "unverified"
    assert verify(one, None, [(11.0, "$ sleep 5")]).status == "verified"


def test_exact_input_text_must_be_in_on_screen_text():
    out = verify(
        exact(text="rm -rf build", on_screen_text="python --version"), None, [(11, "python --version")]
    )
    assert (out.status, out.reason) == ("unverified", "giá trị không có trong nguyên văn")


def test_missing_sources_are_not_checked():
    out = verify(claim(), None)
    assert (out.status, out.method, out.reason) == ("not_checked", "asr", "không có bản ghi lời nói")
    out = verify(exact(), None, None)
    assert (out.status, out.method, out.reason) == ("not_checked", "ocr", "không có kết quả OCR")


def test_action_only_is_not_checkable():
    out = verify(claim(basis="observed", quote=None, on_screen_text=None), None, None)
    assert (out.status, out.method) == ("not_checkable", "none")


@pytest.mark.parametrize("basis", ["inferred", "unclear"])
def test_inferred_and_unclear_are_unverified(basis):
    out = verify(claim(basis=basis, quote="cẩn thận nóng"), transcript("cẩn thận nóng"))
    assert (out.status, out.method, out.reason) == ("unverified", "none", f"basis {basis}")


def test_vietnamese_diacritics_are_significant():
    tr = transcript("cho bot mi vào tô")
    assert verify(claim(quote="bột mì", text="Bột mì"), tr).status == "unverified"
    assert verify(claim(quote="bột mì", text="Bột mì"), transcript("cho bột mì vào tô")).status == "verified"


def test_ocr_tolerates_dropped_diacritics_but_not_numbers():
    item = parameter()
    out = verify(item, None, [(11.0, "Nưng ở 180°C")])
    assert (out.status, out.method, out.matched_sec) == ("verified", "ocr", 11.0)
    assert verify(item, None, [(11.0, "Nưng ở 170°C")]).status == "unverified"


def test_ocr_frame_must_lie_inside_span_window():
    item = parameter()
    assert verify(item, None, [(30.0, "Nướng ở 180°C")]).status == "unverified"
    out = verify(item, None, [(30.0, "Nướng ở 180°C"), (16.5, "x"), (11.0, "Nướng ở 180°C")])
    assert (out.status, out.matched_sec) == ("verified", 11.0)
    assert out.checked_range == (5.0, 17.0)


def test_ocr_frame_with_wrong_number_beats_nothing():
    item = parameter(value="200", on_screen_text="200")
    assert verify(item, None, [(11.0, "Nhiệt độ 2000")]).status == "unverified"


def test_stated_checks_speech_not_ocr_and_vice_versa():
    tr = transcript("nướng ở 180 độ")
    assert verify(parameter(), tr, []).status == "unverified"
    stated = parameter(basis="stated", quote="nướng ở 180 độ", on_screen_text=None, spans=[span()])
    assert verify(stated, tr, None).status == "verified"


def test_helpers():
    assert normalize("  Ａ  Bột\tMÌ ") == "a bột mì"
    tr = transcript("a b c d e", at=10.0)
    assert transcript_window(tr, 10.4, 10.8, 0) == "b c"
    assert transcript_window(tr, 0, 1, 0) == ""
    assert contains_numbers("2 trứng 2 muỗng", "hai quả trứng, 2 muỗng", "vi")
    assert not contains_numbers("2 trứng 2 muỗng", "2 trứng 3 muỗng", "vi")
    assert fuzzy_contains("bột mì", "cho bột mì vào", 85) == "bột mì"
    assert fuzzy_contains("bột mì", "cho bot mi vào", 85) is None
    assert exact_input_matches("a  b", "x a b y") is not None
    assert exact_input_matches("long command here", "lo") is None


def test_iter_grounded_items_paths():
    data = json.loads(MockProvider(Settings(ai_provider="mock")).analyze(None, 10, "vi", {})["text"])
    sp = span()
    c = {"text": "c", "evidence_spans": [sp], "basis": "observed", "scope": "clip", "quote": None}
    c["on_screen_text"] = None
    mat = {"name": "n", "quantity": None, "unit": None, "note": None, "evidence_spans": [sp]}
    mat.update(basis="observed", quote=None, on_screen_text=None)
    par = {"name": "n", "value": "1", "unit": None, "evidence_spans": [sp], "basis": "observed"}
    par.update(quote=None, on_screen_text="1")
    ex = {"kind": "command", "language": None, "text": "ls", "completeness": "complete"}
    ex.update(evidence_spans=[sp], basis="observed", quote=None, on_screen_text="ls")
    data.update(prerequisites=[c], safety=[c, c], materials=[mat], troubleshooting=[c])
    step = data["steps"][0]
    step.update(parameters=[par, par], exact_inputs=[ex], warnings=[c], tips=[c, c])
    draft = TutorialDraftV2.model_validate(data, context={"duration": 100})
    got = [(path, kind) for path, kind, _ in iter_grounded_items(draft)]
    assert got[:5] == [
        ("prerequisites/0", "prerequisites"),
        ("safety/0", "safety"),
        ("safety/1", "safety"),
        ("materials/0", "materials"),
        ("troubleshooting/0", "troubleshooting"),
    ]
    assert got[5:] == [
        ("steps/0/parameters/0", "parameters"),
        ("steps/0/parameters/1", "parameters"),
        ("steps/0/exact_inputs/0", "exact_inputs"),
        ("steps/0/warnings/0", "warnings"),
        ("steps/0/tips/0", "tips"),
        ("steps/0/tips/1", "tips"),
    ]
    assert isinstance(next(iter_grounded_items(draft))[2], GroundedClaim)


def test_verify_settings_are_in_snapshot_and_bounded():
    snap = Settings(ai_provider="mock").snapshot()
    assert (snap["verify_window_seconds"], snap["verify_text_threshold"]) == (5, 85)
    assert (snap["verify_input_threshold"], snap["verify_max_ocr_frames"]) == (95, 3)
    with pytest.raises(ValueError):
        Settings(ai_provider="mock", verify_text_threshold=101)
    with pytest.raises(ValueError):
        Settings(ai_provider="mock", verify_max_ocr_frames=0)
