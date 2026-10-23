import json
import pytest
from app.core.config import Settings
from app.providers.mock import MockProvider
from app.schemas.tutorial_v2 import ExactInput, GroundedClaim, Material, Parameter, TutorialDraftV2
from app.schemas.verification import Transcript, Word
from app.services.verification.matcher import (
    NO_VALUE,
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


def material(
    quantity="200", quote="200 gram bột", basis="stated", on_screen_text=None, spans=None, unit="gram"
):
    return Material(
        name="Bột",
        quantity=quantity,
        unit=unit,
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


def parameter(
    value="180",
    on_screen_text="Nướng ở 180°C",
    basis="observed",
    quote=None,
    spans=None,
    unit="°C",
    name=None,
):
    # ruling I2: an OCR item's name must be in its own on-screen text, so by default the helper names the
    # parameter after that text; tests of the name check pass a name explicitly
    return Parameter(
        name=name or on_screen_text or quote or "Nhiệt độ",
        value=value,
        unit=unit,
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
        ("twenty-four minutes", "en", ["24"]),
        ("two three minutes", "en", []),
        ("four five", "en", []),
        ("hai ba", "vi", []),
        ("một hai", "vi", []),
        ("một nghìn không trăm hai mươi", "vi", ["1020"]),
        ("hai nghìn không trăm năm mươi", "vi", ["2050"]),
        ("năm nghìn không trăm linh năm", "vi", ["5005"]),
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


def test_korean_value_must_appear_exactly():
    verified = verify(
        material(quantity="두", unit="큰술", quote="설탕 두 큰술"),
        transcript("설탕 두 큰술 넣어주세요", language="ko"),
    )
    assert (verified.status, verified.method) == ("verified", "asr")
    wrong = verify(
        material(quantity="두", unit="큰술", quote="설탕 두 큰술"),
        transcript("설탕 세 큰술 넣어주세요", language="ko"),
    )
    assert wrong.status == "unverified"


def test_non_numeric_value_must_appear_exactly():
    item = parameter(
        value="lửa nhỏ", unit=None, basis="stated", quote="để lửa nhỏ", on_screen_text=None, spans=[span()]
    )
    assert verify(item, transcript("để lửa lớn")).status == "unverified"
    assert verify(item, transcript("để lửa nhỏ")).status == "verified"


def test_unit_and_quantity_are_exact_substrings_after_number_spelling():
    tr = transcript("cho hai trăm gram bột vào tô")
    assert verify(material(), tr).status == "verified"
    assert verify(material(quantity="200", quote="hai trăm gram bột"), tr).status == "verified"
    assert verify(material(quote="hai trăm gram bột", unit="ml"), tr).status == "unverified"


def test_ocr_value_must_appear_exactly():
    assert verify(parameter(unit=None), None, [(11.0, "Nưng ở 180°C")]).status == "verified"
    item = parameter(value="Nướng", unit=None, on_screen_text="Nướng ở 180°C")
    assert verify(item, None, [(11.0, "Nưng ở 180°C")]).status == "unverified"


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
    stated = parameter(basis="stated", quote="nướng ở 180 độ", on_screen_text=None, spans=[span()], unit="độ")
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
    assert snap["verify_max_ocr_frames"] == 3
    assert "verify_input_threshold" not in snap
    with pytest.raises(ValueError):
        Settings(ai_provider="mock", verify_text_threshold=101)
    for bad in ({"verify_max_ocr_frames": 0}, {"verify_max_ocr_frames": 11}, {"verify_window_seconds": 61}):
        with pytest.raises(ValueError):
            Settings(ai_provider="mock", **bad)


# ---- regression: false-verified paths found in review ----------------------------------------


def stated_exact(text, quote=None):
    return ExactInput(
        kind="command",
        language="bash",
        text=text,
        completeness="complete",
        evidence_spans=[span(source="audio")],
        basis="stated",
        quote=quote or text,
        on_screen_text=None,
    )


def stated_param(value, unit, quote):
    item = parameter(value=value, unit=unit, basis="stated", quote=quote, on_screen_text=None, spans=[span()])
    return item


def ocr(item, *texts):
    return verify(item, None, [(11.0, t) for t in texts])


SHORTER_COMMAND_CASES = [
    ("rm -rf /", "rm -rf /tmp/build", "rm -rf /tmp/build"),
    ("rm -rf /tmp", "rm -rf /tmp", "$ rm -rf /tmp/build"),
    ("ls", "ls", "cat tools/install.sh"),
    ("rm -rf /tmp/x", "rm -rf /tmp/x", "rm -rf /tmpx"),
    ("sudo rm -rf /var/lib/docker", "sudo rm -rf /var/lib/docker", "sudo rm -rf /var/lib/dockor"),
    ("git push --force", "git push --force", "git push --forge"),
    ("pip install flask", "pip install flask", "x pip install flask2"),
]


@pytest.mark.parametrize("text,on_screen,screen", SHORTER_COMMAND_CASES)
def test_exact_input_is_never_fuzzy_or_a_fragment(text, on_screen, screen):
    assert ocr(exact(text=text, on_screen_text=on_screen), screen).status == "unverified"


def test_exact_input_boundaries_are_whitespace_or_edges():
    item = exact(text="rm -rf /tmp", on_screen_text="rm -rf /tmp")
    assert ocr(item, "$ rm -rf /tmp").status == "verified"
    assert ocr(item, "line one\nrm  -rf   /tmp\nline three").status == "verified"
    assert ocr(item, "rm -rf /tmp.").status == "unverified"
    assert not exact_input_matches("ls", "tools/install.sh")


@pytest.mark.parametrize(
    "spoken", ["giờ ta chạy pip install flash nhé", "ta gõ pip install flasks", "pip install flask."]
)
def test_spoken_exact_input_is_exact(spoken):
    assert verify(stated_exact("pip install flask"), transcript(spoken)).status == "unverified"
    assert verify(stated_exact("npm run build"), transcript("ta gõ npm run built")).status == "unverified"


def test_spoken_exact_input_verifies_when_exact():
    # ruling C4: the command must be its own stretch of speech, so pauses (>= 0.7 s) surround it here
    words = [
        Word(start=10.0 + i * 0.4, end=10.3 + i * 0.4, text=w) for i, w in enumerate("giờ ta chạy".split())
    ]
    words += [
        Word(start=12.0 + i * 0.4, end=12.3 + i * 0.4, text=w)
        for i, w in enumerate("pip install flask".split())
    ]
    words += [Word(start=14.0, end=14.3, text="nhé")]
    out = verify(stated_exact("pip install flask"), Transcript(language="vi", words=words))
    assert (out.status, out.matched_text, out.matched_sec) == ("verified", "pip install flask", 12.0)
    tight = verify(stated_exact("pip install flask"), transcript("giờ ta chạy pip install flask nhé"))
    assert tight.status == "unverified"


def test_exact_input_text_must_equal_its_source_text():
    item = exact(text="rm -rf /", on_screen_text="rm -rf /tmp/build")
    assert ocr(item, "rm -rf /tmp/build").reason == NO_VALUE


@pytest.mark.parametrize(
    "item,spoken",
    [
        (material(quantity="두", unit="큰술", quote="설탕 두 큰술"), "설탕 세 큰술 모두 넣어주세요"),
        (material(quantity="200", unit="ml", quote="200 gram bột"), "cho 200 gram bột và 200 ml nước"),
        (stated_param("lửa lớn", None, "để lửa nhỏ"), "để lửa nhỏ rồi sau đó lửa lớn"),
        (material(quantity="200", unit="gram", quote="200 gram bột"), "cho 20 gram bột và 200 muỗng nước"),
    ],
)
def test_required_values_come_from_the_quote_and_the_segment(item, spoken):
    language = "ko" if "설탕" in spoken else "vi"
    assert verify(item, transcript(spoken, language=language)).status == "unverified"


def test_required_value_must_sit_inside_the_matched_segment():
    item = material(quantity="200", unit="gram", quote="cho gram bột vào tô").model_copy(
        update={"quote": "cho 200 gram bột"}
    )
    assert verify(item, transcript("cho gram bột rồi 200 muỗng nước", language="vi")).status == "unverified"


def test_ocr_required_value_comes_from_the_text_and_segment():
    item = parameter(value="cao", unit=None, on_screen_text="nhiệt độ thấp")
    assert ocr(item, "nhiệt độ thấp | chế độ cao").reason == NO_VALUE
    item = parameter(value="cao", unit=None, on_screen_text="nhiệt độ cao")
    assert ocr(item, "nhiệt độ thấp | chế độ cao").status == "unverified"
    assert ocr(item, "Nhiệt độ cao").status == "verified"


@pytest.mark.parametrize(
    "spoken,quote,value,unit",
    [
        ("nướng ở một trăm năm độ nhé", "nướng ở 105 độ", "105", "độ"),
        ("nướng ở một trăm năm độ nhé", "nướng ở 150 độ", "150", "độ"),
        ("nướng hai trăm tư độ", "nướng 204 độ", "204", "độ"),
        ("nướng hai trăm tư độ", "nướng 240 độ", "240", "độ"),
        ("cho một trăm mốt gram", "cho 101 gram", "101", "gram"),
        ("cho một nghìn hai gram bột", "cho 1002 gram bột", "1002", "gram"),
        ("cho một nghìn hai gram bột", "cho 1200 gram bột", "1200", "gram"),
        ("bảo hành hai mươi năm", "bảo hành 25 năm", "25", "năm"),
    ],
)
def test_colloquial_vietnamese_numbers_are_not_read(spoken, quote, value, unit):
    assert verify(stated_param(value, unit, quote), transcript(spoken)).status == "unverified"


@pytest.mark.parametrize(
    "spoken,quote,value,unit",
    [
        ("nướng ở một trăm năm mươi độ nhé", "nướng ở 150 độ", "150", "độ"),
        ("nướng ở một trăm linh năm độ nhé", "nướng ở 105 độ", "105", "độ"),
        ("cho hai trăm mười lăm gram bột", "cho 215 gram bột", "215", "gram"),
        ("cho một nghìn hai trăm gram bột", "cho 1200 gram bột", "1200", "gram"),
    ],
)
def test_formal_vietnamese_numbers_still_verify(spoken, quote, value, unit):
    assert verify(stated_param(value, unit, quote), transcript(spoken)).status == "verified"


@pytest.mark.parametrize(
    "quote,spoken",
    [
        ("a", "hôm nay ta làm bánh"),
        ("nóng", "cái này không nóng lắm"),
        ("ok", "được rồi okay nhé"),
    ],
)
def test_very_short_quotes_do_not_verify(quote, spoken):
    out = verify(claim(quote=quote, text="x"), transcript(spoken))
    assert out.status == "unverified"
    assert out.reason == "nguyên văn quá ngắn" or "không khớp" in out.reason


def test_short_value_quote_is_too_short():
    out = verify(stated_param("2", None, "2"), transcript("lấy 2 cái và 5 cái"))
    assert (out.status, out.reason) == ("unverified", "nguyên văn quá ngắn")
    assert verify(claim(quote="nóng", text="x"), transcript("cái này nóng")).reason == "nguyên văn quá ngắn"


def test_matches_snap_to_whole_words():
    assert verify(claim(quote="cho đường", text="x"), transcript("cho đường nhé")).matched_text == "cho đường"
    out = verify(claim(quote="ận nóng", text="x"), transcript("các bạn cẩn thận nóng nhé"))
    assert out.status == "verified" and out.matched_text == "thận nóng"
    assert out.matched_sec == pytest.approx(10.0 + 3 * 0.4)


@pytest.mark.parametrize(
    "quote,spoken",
    [
        ("cho 1/2 chén đường", "cho 1-2 chén đường"),
        ("cho 1/2 chén đường", "cho 1 2 chén đường"),
        ("cho 1,5 kg bột", "cho một năm kg bột"),
        ("cho 1,5 kg bột", "cho 15 kg bột"),
        ("cho 1.5 kg bột", "cho 1 5 kg bột"),
        ("đếm 2 2 nhịp", "đếm 1 2 nhịp"),
        ("cho 12 gram bột", "cho 1 2 gram bột"),
        ("cho 12 gram bột", "cho 120 gram bột"),
    ],
)
def test_claim_numbers_keep_their_shape(quote, spoken):
    assert verify(claim(quote=quote, text="x"), transcript(spoken)).status == "unverified"


def test_claim_numbers_equal_shape_verifies():
    assert (
        verify(claim(quote="cho 1,5 kg bột", text="1,5 kg"), transcript("cho 1.5 kg bột")).status
        == "verified"
    )
    assert (
        verify(claim(quote="cho 1/2 chén đường", text="1/2 chén"), transcript("cho 1/2 chén đường")).status
        == "verified"
    )
    # ruling R4c: the claim's number needs the unit its quote gives it ('1/2' alone, quote '1/2 chén')
    bare = claim(quote="cho 1/2 chén đường", text="1/2")
    assert verify(bare, transcript("cho 1/2 chén đường")).status == "unverified"


@pytest.mark.parametrize(
    "value,unit,quote,spoken",
    [
        ("1", "tiếng", "nướng 1 tiếng", "nướng một tiếng rưỡi là được"),
        ("3", "phút", "nấu 3 phút", "nấu khoảng 2-3 phút"),
        ("3", "phút", "nấu 3 phút", "nấu 2-3 phút nhé"),
        ("18", "độ", "cấp đông 18 độ", "để tủ cấp đông âm 18 độ"),
        ("2", "cups", "add 2 cups of flour", "add two and a half cups of flour"),
        ("5", "phút", "nướng 5 phút", "nướng 1.5 phút"),
        ("5", "phút", "nướng 5 phút", "nướng 1,5 phút"),
        ("200", "gram", "cho 200 gram bột", "cho hai trăm rưỡi gram bột"),
    ],
)
def test_modifiers_and_range_edges_next_to_a_number_block_verification(value, unit, quote, spoken):
    language = "en" if "cups" in spoken else "vi"
    out = verify(stated_param(value, unit, quote), transcript(spoken, language=language))
    assert out.status == "unverified"


@pytest.mark.parametrize(
    "value,screen",
    [("18", "Tủ đông -18°C"), ("5", "1.5 phút"), ("5", "Nồng độ 0.5%"), ("5", "15 phút"), ("3", "2-3 phút")],
)
def test_ocr_number_edges_block_verification(value, screen):
    unit = "%" if "%" in screen else None
    text = {"18": "18°C", "5": "5%" if "%" in screen else "5 phút", "3": "3 phút"}[value]
    assert ocr(parameter(value=value, unit=unit, on_screen_text=text), screen).status == "unverified"
    assert ocr(parameter(value=value, unit=unit, on_screen_text=text), text).status == "verified"


def test_two_numbers_and_ranges_verify_when_equal():
    out = verify(stated_param("2-3", "phút", "nấu khoảng 2-3 phút"), transcript("nấu khoảng 2-3 phút nhé"))
    assert out.status == "verified"
    assert (
        verify(stated_param("-18", "độ", "để ở -18 độ"), transcript("để ở -18 độ nhé")).status == "verified"
    )


def test_unit_attached_to_the_number_is_accepted():
    assert ocr(parameter(value="200", unit="g", on_screen_text="200g"), "Bột 200g").status == "verified"
    assert ocr(parameter(value="180", unit="°C", on_screen_text="180°C"), "Nướng 180°C").status == "verified"


def test_number_tokens_shapes():
    from app.services.verification.numbers import number_tokens

    assert number_tokens("1,5 1.5 1/2 2-3 -18 007 1.000 0,05 1.05", None) == [
        "1.5",
        "1.5",
        "1/2",
        "2-3",
        "-18",
        "7",
        "1.000",
        "0.05",
        "1.05",
    ]
    assert number_tokens("pt-18 và 3,", None) == ["18", "3"]


# ---- regression: round 2 (ranges and alternatives, zero groups, decimal zeros) ---------------


def oparam(value, unit, text, screen):
    return ocr(parameter(value=value, unit=unit, on_screen_text=text), screen)


def oclaim(text, screen):
    item = claim(basis="observed", quote=None, on_screen_text=text, text="x", spans=[span(source="visual")])
    return ocr(item, screen)


RANGE_AND_ALTERNATIVE_CASES = [
    lambda: oparam("3", "phút", "3 phút", "Nấu 2 - 3 phút"),
    lambda: oparam("18", "°C", "18°C", "Tủ đông - 18°C"),
    lambda: oparam("3", "phút", "3 phút", "Nấu 2 đến 3 phút"),
    lambda: oparam("3", "phút", "3 phút", "Nấu 2 ~ 3 phút"),
    lambda: oparam("3", "phút", "3 phút", "Nau 2 hoac 3 phut"),
    lambda: oparam("3", "phút", "3 phút", "Nấu 3 phút hoặc 5 phút"),
    lambda: oclaim("Tủ đông 18°C", "Tủ đông - 18°C"),
    lambda: verify(
        material(quantity="2", unit="chén", quote="cho 2 chén đường"), transcript("cho một hai chén đường")
    ),
    lambda: verify(stated_param("2", "chén", "cho 2 chén đường"), transcript("cho 1 2 chén đường")),
    lambda: verify(stated_param("3", "phút", "hai ba phút"), transcript("nấu chừng hai ba phút là chín")),
    lambda: verify(stated_param("3", "phút", "3 phút là chín"), transcript("nấu 2 hoặc 3 phút là chín")),
    lambda: verify(stated_param("3", "phút", "3 phút"), transcript("nấu khoảng 2 - 3 phút nhé")),
    lambda: verify(stated_param("3", "phút", "3 phút"), transcript("nấu 2 đến 3 phút nhé")),
    lambda: verify(stated_param("3", "phút", "nấu 3 phút"), transcript("nấu khoảng hai ba phút nhé")),
    lambda: verify(
        stated_param("5", "minutes", "five minutes until golden"),
        transcript("bake four or five minutes until golden", language="en"),
    ),
    lambda: verify(
        stated_param("3", "minutes", "cook for 3 minutes"),
        transcript("cook for 2 to 3 minutes", language="en"),
    ),
]


@pytest.mark.parametrize("case", RANGE_AND_ALTERNATIVE_CASES)
def test_ranges_and_alternatives_around_a_number_never_verify(case):
    assert case().status == "unverified"


def test_a_number_two_tokens_away_from_a_non_numeric_edge_is_fine():
    # round 4: another quantity must be more than 8 tokens from the quote's edge number (was 2-4)
    spoken = "cho 200 gram bột rồi khuấy đều cho thật kỹ xong thêm 100 gram đường"
    assert verify(material(quote="cho 200 gram bột"), transcript(spoken)).status == "verified"
    spoken = "cho 100 gram đường rồi khuấy đều cho thật kỹ sau đó cho 200 gram bột"
    assert verify(material(quote="cho 200 gram bột"), transcript(spoken)).status == "verified"


@pytest.mark.parametrize(
    "item,spoken,lang",
    [
        (
            stated_param("1120", "gram", "cho 1120 gram bột"),
            "cho một nghìn không trăm hai mươi gram bột",
            "vi",
        ),
        (
            stated_param("2150", "gram", "cho 2150 gram bột"),
            "cho hai nghìn không trăm năm mươi gram bột",
            "vi",
        ),
        (
            stated_param("5105", "gram", "cho 5105 gram bột"),
            "cho năm nghìn không trăm linh năm gram bột",
            "vi",
        ),
    ],
)
def test_zero_hundreds_group_is_not_counted_as_a_hundred(item, spoken, lang):
    assert verify(item, transcript(spoken, language=lang)).status == "unverified"


def test_zero_hundreds_group_correct_reading_verifies():
    spoken = transcript("cho một nghìn không trăm hai mươi gram bột")
    assert verify(stated_param("1020", "gram", "cho 1020 gram bột"), spoken).status == "verified"


@pytest.mark.parametrize(
    "quote,spoken",
    [
        ("pha loãng dung dịch 0,5%", "pha loãng dung dịch 0,05%"),
        ("cho 1.5 kg bột vào", "cho 1.05 kg bột vào"),
        ("cho 1.000 kg bột vào", "cho 1.0 kg bột vào"),
    ],
)
def test_decimal_leading_zeros_are_significant(quote, spoken):
    assert verify(claim(quote=quote, text="x"), transcript(spoken)).status == "unverified"


def test_decimal_leading_zeros_equal_verifies():
    assert (
        verify(
            claim(quote="pha loãng dung dịch 0,05%", text="x"), transcript("pha loãng dung dịch 0,05%")
        ).status
        == "verified"
    )
    assert oclaim("Dùng 0.05 ml thuốc", "Dùng 0.05 ml thuốc").status == "verified"
    assert oclaim("Dùng 0.5 ml thuốc", "Dùng 0.05 ml thuốc").status == "unverified"


def test_unit_g_is_not_found_in_gram_recall_trade_off():
    out = verify(material(unit="g"), transcript("cho 200 gram bột vào"))
    assert (out.status, out.reason) == ("unverified", NO_VALUE)


# ---- regression: round 3 (structural ranges, repeated scales, unread runs, bare decimals) ------


@pytest.mark.parametrize(
    "text,lang,expected",
    [
        ("hai trăm năm mươi", "vi", ["250"]),
        ("hai nghìn ba trăm", "vi", ["2300"]),
        ("hai trăm nghìn", "vi", ["200000"]),
        ("hai triệu ba trăm nghìn", "vi", ["2300000"]),
        ("một nghìn không trăm hai mươi", "vi", ["1020"]),
        ("hai chục", "vi", ["20"]),
        ("two hundred thousand", "en", ["200000"]),
        ("two million", "en", ["2000000"]),
        ("hai mươi ba mươi", "vi", []),
        ("ba mươi bốn mươi", "vi", []),
        ("mười hai mươi", "vi", []),
        ("hai nghìn ba nghìn", "vi", []),
        ("hai trăm nghìn ba trăm nghìn", "vi", []),
        ("two thousand three thousand", "en", []),
        ("two hundred three hundred", "en", []),
    ],
)
def test_repeated_scales_are_ambiguous_but_compounds_are_read(text, lang, expected):
    assert digit_runs(text, lang) == expected


def test_unread_number_words_become_opaque_tokens():
    from app.services.verification.numbers import number_tokens

    assert number_tokens("cho hai ba chén", "vi") == ["~hai ba"]
    assert number_tokens("cho hai ba chén và 5 muỗng", "vi") == ["~hai ba", "5"]
    assert number_tokens("Cho  hai   mươi ba mươi", "vi") == ["~hai mươi ba mươi"]
    assert number_tokens("Dùng .05 ml, 1,5 và ,5", None) == ["0.05", "1.5", "0.5"]  # ruling R3


UNREAD_CLAIM_CASES = [
    ("cho khoảng hai ba chén đường", "cho khoảng ba bốn chén đường", "vi"),
    ("add about two three cups of sugar", "add about four five cups of sugar", "en"),
    ("cho khoảng hai ba chén đường", "cho khoảng hai chén đường", "vi"),
    ("nấu hai mươi ba mươi phút nhé", "nấu hai mươi phút nhé", "vi"),
]


@pytest.mark.parametrize("quote,spoken,lang", UNREAD_CLAIM_CASES)
def test_unread_number_runs_still_have_to_agree(quote, spoken, lang):
    assert verify(claim(quote=quote, text="x"), transcript(spoken, language=lang)).status == "unverified"
    same = verify(claim(quote=quote, text="x"), transcript(quote, language=lang))
    assert same.status == "verified"


@pytest.mark.parametrize(
    "value,unit,quote,spoken,lang",
    [
        ("3", "phút", "3 phút nhé", "nấu 2 phút hay là 3 phút nhé", "vi"),
        ("3", "phút", "3 phút nhé", "nấu 2 hoặc là 3 phút nhé", "vi"),
        ("3", "phút", "ba phút nhé", "nấu hai đến tầm ba phút nhé", "vi"),
        ("3", "minutes", "3 minutes until golden", "bake 2 or maybe 3 minutes until golden", "en"),
        ("3", "minutes", "three minutes until golden", "bake two or maybe three minutes until golden", "en"),
        ("3", "minutes", "3 minutes until golden", "bake 2 to about 3 minutes until golden", "en"),
        (
            "3",
            "minutes",
            "three minutes until golden",
            "bake two minutes or three minutes until golden",
            "en",
        ),
        ("10", "phút", "nấu 10 phút là chín", "nấu hai mươi ba mươi phút là chín", "vi"),
        ("10", "phút", "nấu 10 phút là chín", "nấu ba mươi bốn mươi phút là chín", "vi"),
        ("5000", "đồng", "giá 5000 đồng một gói", "giá hai nghìn ba nghìn đồng một gói", "vi"),
        (
            "5000",
            "dollars",
            "about 5000 dollars total",
            "about two thousand three thousand dollars total",
            "en",
        ),
        ("500000", "đồng", "giá 500000 đồng", "giá hai trăm nghìn ba trăm nghìn đồng", "vi"),
        ("3", "분", "3분 끓여주세요", "2~3분 끓여주세요", "ko"),
        ("3", "분", "3분 끓여주세요", "2 ~ 3분 끓여주세요", "ko"),
    ],
)
def test_ranges_with_filler_words_and_repeated_scales_never_verify(value, unit, quote, spoken, lang):
    assert verify(stated_param(value, unit, quote), transcript(spoken, language=lang)).status == "unverified"


def test_range_in_ocr_with_filler_words():
    assert oparam("3", "phút", "3 phút", "Nấu 2 hoặc là 3 phút").status == "unverified"
    assert oparam("3", "phút", "3 phút", "Nau 2 hoac la 3 phut").status == "unverified"
    assert oparam("3", "phút", "3 phút", "Nấu hai đến tầm 3 phút").status == "unverified"
    assert oparam("3", "phút", "3 phút", "Nấu 3 phút").status == "verified"


def test_vietnamese_words_that_fold_to_number_words_do_not_block_speech():
    # "sau" (after) is the diacritic-free form of "sáu" (six) but is a plain word in speech
    spoken = "cho 100 gram đường rồi khuấy đều cho thật kỹ sau đó cho 200 gram bột"
    assert verify(material(quote="cho 200 gram bột"), transcript(spoken)).status == "verified"


def test_bare_leading_separator_numbers_read_with_a_zero():
    assert oclaim("Dùng 5 ml thuốc", "Dùng .05 ml thuốc").status == "unverified"
    assert oclaim("Dùng .05 ml thuốc", "Dùng .05 ml thuốc").status == "verified"
    # ruling R3: '.05' is written '0.05' ('0,05' too), so the two spellings agree
    assert oclaim("Dùng 0.05 ml thuốc", "Dùng .05 ml thuốc").status == "verified"
    assert oclaim("Dùng 0.5 ml thuốc", "Dùng .05 ml thuốc").status == "unverified"


def test_valid_compounds_verify_end_to_end():
    for spoken, value in [
        ("cho hai nghìn ba trăm gram bột", "2300"),
        ("cho hai trăm nghìn gram bột", "200000"),
        ("cho hai trăm năm mươi gram bột", "250"),
    ]:
        item = stated_param(value, "gram", f"cho {value} gram bột")
        assert verify(item, transcript(spoken)).status == "verified", spoken


# ---- regression: round 4 (number-token distance, bare scales, separator after a letter) --------


@pytest.mark.parametrize(
    "text,lang,expected",
    [
        ("vài chục gram", "vi", ["~chục"]),
        ("mấy chục", "vi", ["~chục"]),
        ("hàng chục", "vi", ["~chục"]),
        ("vài triệu đồng", "vi", ["~triệu"]),
        ("vài trăm gram", "vi", ["~trăm"]),
        ("mấy nghìn đồng", "vi", ["~nghìn"]),
        ("mươi phút", "vi", ["~mươi"]),
        ("hai nghìn trăm", "vi", ["~hai nghìn trăm"]),
        ("a few million dollars", "en", ["~million"]),
        ("a few hundred grams", "en", ["~hundred"]),
        ("hundred thousand", "en", ["~hundred thousand"]),
        ("a hundred grams", "en", ["100"]),
        ("a thousand dollars", "en", ["1000"]),
        ("an hundred", "en", ["100"]),
        ("a million", "en", ["1000000"]),
        ("hai chục", "vi", ["20"]),
        ("một trăm nghìn", "vi", ["100000"]),
        ("ba trăm hai nghìn", "vi", ["~ba trăm hai nghìn"]),
        ("một triệu hai nghìn", "vi", ["~một triệu hai nghìn"]),
        ("ba trăm linh hai nghìn", "vi", ["302000"]),
        ("một triệu hai trăm nghìn", "vi", ["1200000"]),
        ("hai mươi lăm nghìn", "vi", ["25000"]),
        ("dùng.05", None, ["0.05"]),
        ("muối,5 phút", None, ["0.5"]),
    ],
)
def test_bare_scales_are_unread_and_separators_after_letters_start_numbers(text, lang, expected):
    from app.services.verification.numbers import number_tokens

    assert number_tokens(text, lang) == expected


def vi_mat(quantity, unit, quote):
    return material(quantity=quantity, unit=unit, quote=quote)


ROUND_4_NEGATIVES = [
    # bare scale words after a vague quantifier are not exact numbers
    lambda: verify(vi_mat("10", "gram", "cho 10 gram muối"), transcript("cho vài chục gram muối")),
    lambda: verify(vi_mat("10", "gram", "cho vài chục gram muối"), transcript("cho vài chục gram muối")),
    lambda: verify(vi_mat("10", "gram", "cho mấy chục gram muối"), transcript("cho mấy chục gram muối")),
    lambda: verify(vi_mat("10", "gram", "cho hàng chục gram muối"), transcript("cho hàng chục gram muối")),
    lambda: verify(
        vi_mat("1000000", "đồng", "tốn vài triệu đồng thôi"), transcript("tốn vài triệu đồng thôi")
    ),
    lambda: verify(vi_mat("100", "gram", "cho vài trăm gram muối"), transcript("cho vài trăm gram muối")),
    lambda: verify(
        stated_param("1000000", "dollars", "a few million dollars total"),
        transcript("it cost a few million dollars total", language="en"),
    ),
    lambda: verify(vi_mat("302000", "đồng", "giá 302000 đồng"), transcript("giá ba trăm hai nghìn đồng")),
    # connectors with three or more filler words
    lambda: verify(stated_param("3", "phút", "3 phút nhé"), transcript("nấu 2 hoặc có thể là 3 phút nhé")),
    lambda: verify(stated_param("3", "phút", "3 phút nhé"), transcript("nấu 2 phút hoặc có thể 3 phút nhé")),
    lambda: verify(
        stated_param("3", "phút", "3 phút nhé"), transcript("nấu 2 phút hoặc là khoảng 3 phút nhé")
    ),
    lambda: verify(
        stated_param("3", "minutes", "3 minutes until golden"),
        transcript("bake 2 minutes or maybe about 3 minutes until golden", language="en"),
    ),
    lambda: verify(
        stated_param("3", "minutes", "three minutes until golden"),
        transcript("bake two, or if you like, three minutes until golden", language="en"),
    ),
    lambda: oparam("3", "phút", "3 phút", "Nấu 2 hoặc có thể là 3 phút"),
    lambda: verify(stated_param("2", "phút", "nấu 2 phút"), transcript("nấu 2 phút hay là tầm 3 phút")),
    # quotes with words before their number
    lambda: verify(stated_param("3", "phút", "khoảng tầm 3 phút"), transcript("nấu 2 hay khoảng tầm 3 phút")),
    lambda: verify(stated_param("3", "phút", "hoặc là 3 phút nhé"), transcript("nấu 2 hoặc là 3 phút nhé")),
    lambda: verify(
        stated_param("3", "minutes", "or maybe 3 minutes"),
        transcript("bake 2 or maybe 3 minutes", language="en"),
    ),
    lambda: oparam("3", "phút", "hoặc là 3 phút", "Nấu 2 hoặc là 3 phút"),
    # a separator right after a letter starts a number
    lambda: oclaim("Dùng 5 ml thuốc", "Dùng.05 ml thuốc"),
    lambda: oparam("5", "ml", "Dùng 5 ml", "Dùng.05 ml thuốc"),
]


@pytest.mark.parametrize("case", ROUND_4_NEGATIVES)
def test_round_4_false_verified_inputs_are_unverified(case):
    assert case().status == "unverified"


ROUND_4_POSITIVES = [
    lambda: verify(material(quote="cho 200 gram bột"), transcript("nhớ cho 200 gram bột vào tô nhé")),
    lambda: verify(
        stated_param("100", "grams", "add a hundred grams of flour"),
        transcript("now add a hundred grams of flour", language="en"),
    ),
    lambda: verify(
        stated_param("100", "grams", "add 100 grams of flour"),
        transcript("now add a hundred grams of flour", language="en"),
    ),
    lambda: verify(
        stated_param("1020", "gram", "cho 1020 gram bột"),
        transcript("cho một nghìn không trăm hai mươi gram bột"),
    ),
    lambda: verify(
        claim(quote="pha loãng dung dịch 0,05%", text="x"), transcript("pha loãng dung dịch 0,05%")
    ),
    lambda: oclaim("Dùng.05 ml thuốc", "Dùng.05 ml thuốc"),
    lambda: verify(vi_mat("20", "gram", "cho hai chục gram muối"), transcript("cho hai chục gram muối")),
]


@pytest.mark.parametrize("case", ROUND_4_POSITIVES)
def test_round_4_correct_readings_still_verify(case):
    assert case().status == "verified"


def test_numbers_within_eight_tokens_block_a_correct_quote_recall_trade_off():
    # ruling (a): safety over recall. A second quantity, or any number word such as the article
    # "một" (a/one), within 8 tokens of the quote's edge number makes a correct quote unverified.
    for spoken in [
        "cho 200 gram bột và 100 gram đường",
        "cho 100 gram đường rồi sau đó cho 200 gram bột",
        "cho 200 gram bột vào một cái tô",
    ]:
        assert verify(material(quote="cho 200 gram bột"), transcript(spoken)).status == "unverified", spoken
