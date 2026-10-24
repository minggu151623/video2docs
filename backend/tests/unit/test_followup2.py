"""Follow-up 2 (rulings P1, P2): shell/REPL prompts on OCR rows, and claims whose quote matched but whose
paraphrase was not checked (`quote_matched`)."""

import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from app.core.config import Settings
from app.providers.mock import MockProvider
from app.schemas.tutorial_v2 import ExactInput, GroundedClaim, TutorialDraftV2
from app.schemas.verification import ItemVerification, Transcript, VerificationReport, Word
from app.services.rendering import render_markdown
from app.services.verification import guards, pipeline
from app.services.verification.matcher import verify_item
from app.services.verification.ocr import OCR
from test_matcher import SCREEN_ONLY, SETTINGS, span
from test_matcher_final_review import cl, mat, par, say, show


ENGINES = {"asr_status": "ok", "ocr_status": "ok"}


def command(text, kind="command", language="shell", spans=None):
    return ExactInput(
        kind=kind,
        language=language,
        text=text,
        completeness="complete",
        evidence_spans=spans or [span(source="visual")],
        basis="observed",
        quote=None,
        on_screen_text=text,
    )


# ---- P1: one leading prompt is stripped from an OCR row -------------------------------------------

LIVE_150 = "Microsoft Windows [Version 10.0.22631.4169]\nC:\\Users\\hp>python --version\nPython 3.13.0"
LIVE_179 = 'IDLE Shell 3.13.0\n>>> print("Amit Diwan")\nAmit Diwan\n>>>'


@pytest.mark.parametrize(
    "text,screen",
    [
        ("python --version", LIVE_150),
        ('print("Amit Diwan")', LIVE_179),
        ("dir", "C:\\>dir"),
        ("python --version", "D:\\Projects\\demo> python --version"),
        ("    return x", "... return x"),
        ("x = 1", "In [3]: x = 1"),
        ("x = 1", "In [12]:x = 1"),
        ("npm run build", "PS C:\\Users\\me> npm run build"),
    ],
)
def test_p1_prompt_before_command_is_stripped(text, screen):
    out = show(command(text), screen)
    assert out.status == "verified"
    assert out.matched_text.replace(" ", "") == text.replace(" ", "")


@pytest.mark.parametrize(
    "text,screen",
    [
        ("python --version", "C:\\Users\\hp>python --version --verbose"),
        ("print(2)", ">>> print(1)"),
        ("x = 1", "In [3]: x = 1; y = 2"),
        ("python --version", "C:\\Users\\hp>"),
        ("python --version", ">>>"),
        ("python --version", "In [3]:"),
        # at most one prompt: a second prompt left on the row is part of the row
        ("python --version", ">>> C:\\Users\\hp>python --version"),
        ("python --version", "C:\\Users\\hp>>>> python --version"),
    ],
)
def test_p1_row_must_still_equal_the_command(text, screen):
    assert show(command(text), screen).status == "unverified"


def test_p1_prompt_only_row_is_not_stripped_into_the_next_rows():
    """A row that is only a prompt does not start a match; the command row matches on its own."""
    assert guards.exact_rows("python --version", "C:\\Users\\hp>\npython --version") == "python --version"
    assert guards.exact_rows("python --version", "C:\\Users\\hp>\npython\n--version") == "python\n--version"


ROOT = Path(__file__).resolve().parents[3]
VIDEO = ROOT / "video_test" / "HowtoinstallPythonWindows11.mp4"
PADDLE_MODELS = Path.home() / ".paddlex" / "official_models"


def _real_ocr_ready() -> bool:
    models = ("PP-OCRv5_mobile_det", "en_PP-OCRv5_mobile_rec")
    return (
        VIDEO.is_file()
        and shutil.which("ffmpeg") is not None
        and importlib.util.find_spec("paddleocr") is not None
        and all((PADDLE_MODELS / m).is_dir() for m in models)
    )


@pytest.mark.slow
@pytest.mark.skipif(not _real_ocr_ready(), reason="source video, ffmpeg or PaddleOCR models are not present")
def test_p1_real_ocr_reads_live_commands_with_prompts(tmp_path):
    """Live run 24/10: both commands were on screen behind a prompt. 177 s is the last OCR frame of the
    print item's evidence span; at 179 s OCR reads a trailing '—' (cursor) on that row, which the
    whole-row rule rightly rejects."""
    ocr = OCR(Settings())
    speech = Transcript(language="en", words=[Word(start=1.0, end=1.3, text="hello")])
    cases = [("python --version", 146.0, 150.0, 150), ('print("Amit Diwan")', 169.0, 177.0, 177)]
    for text, start, end, second in cases:
        frame = tmp_path / f"{second}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(second),
                "-i",
                str(VIDEO),
                "-frames:v",
                "1",
                str(frame),
            ],
            check=True,
        )
        screen = ocr.read(frame, "en")
        item = command(text, spans=[span(start, end, "visual")])
        out = verify_item("p", item, speech, [(float(second), screen)], SETTINGS, text_language="vi")
        assert out.status == "verified", screen
        assert out.matched_text == text


# ---- P2: a claim whose quote matched but whose own words were not checked -------------------------

EN_SPEECH = Transcript(language="en", words=[Word(start=100.0, end=100.3, text="next")])
LIVE_CLAIM = "Đã hoàn tất cài đặt Python trên Windows."


def observed(text, ost, start=115.0, end=130.0):
    return GroundedClaim(
        text=text,
        evidence_spans=[span(start, end, "visual")],
        basis="observed",
        scope="clip",
        on_screen_text=ost,
    )


def test_p2_live_claim_with_a_matching_screen_word_is_only_quote_matched():
    frames = [(115.0, "python-3.13.0-amd64\nSetup Progress\nInstalling:")]
    out = verify_item(
        "prerequisites/1",
        observed(LIVE_CLAIM, "Setup Progress"),
        EN_SPEECH,
        frames,
        SETTINGS,
        text_language="vi",
    )
    assert (out.status, out.method) == ("quote_matched", "ocr")
    assert (out.matched_text, out.matched_sec, out.checked_range) == ("setup progress", 115.0, (110.0, 135.0))
    # the same claim beside Vietnamese speech still paraphrases its quote
    vi = verify_item(
        "p", observed(LIVE_CLAIM, "Setup Progress"), SCREEN_ONLY, frames, SETTINGS, text_language="vi"
    )
    assert vi.status == "quote_matched"


def test_p2_same_language_claim_in_its_quotes_words_is_verified():
    item = cl("Nhấn nút Install", "nhấn nút Install")
    out = say(item, "bây giờ nhấn nút Install nhé", "vi", "vi")
    assert (out.status, out.method, out.matched_text) == ("verified", "asr", "nhấn nút install")
    assert say(item, "bây giờ nhấn nút Install nhé", "vi-VN", "VI").status == "verified"  # primary subtag
    on_screen = observed("Nhấn nút Install", "Nhấn nút Install", 10, 12)
    assert show(on_screen, "Nhấn nút Install", text_language="vi").status == "verified"


def test_p2_cross_or_unknown_language_is_quote_matched():
    item = cl("Install now", "install now")
    assert say(item, "please install now", "en", "vi").status == "quote_matched"
    assert say(item, "please install now", "en", None).status == "quote_matched"
    assert say(item, "please install now", None, "en").status == "quote_matched"
    assert say(item, "please install now", "en", "en-US").status == "verified"
    screen = observed("Install now", "Install now", 10, 12)
    no_words = Transcript(language="en", words=[])
    for transcript in (None, no_words):
        out = verify_item("p", screen, transcript, [(11.0, "Install now")], SETTINGS, text_language="en")
        assert out.status == "quote_matched"
    # on screen, the language comes from the transcript as long as it has words, wherever they lie
    out = verify_item("p", screen, EN_SPEECH, [(11.0, "Install now")], SETTINGS, text_language="en")
    assert out.status == "verified"


def test_p2_same_language_reworded_claim_is_quote_matched():
    item = cl("Cài xong Python", "nhấn nút Install")
    assert say(item, "bây giờ nhấn nút Install nhé", "vi", "vi").status == "quote_matched"


@pytest.mark.parametrize(
    "case",
    [
        lambda: say(cl("Nấu 3 phút", "nấu 3 phút"), "giờ nấu 4 phút nhé", "vi", "en"),
        lambda: say(cl("Cook for 4 minutes", "nấu 3 phút"), "giờ nấu 3 phút nhé", "vi", "en"),
        lambda: say(
            cl("Add 2 tablespoons of salt", "add 2 tablespoons of salt"), "add 2 teaspoons of salt", "en"
        ),
        lambda: show(cl("Add 2 tbsp salt", ost="Add 2 tbsp salt"), "Add 2 tsp salt", text_language="vi"),
        lambda: say(cl("Chấm nước mắm", "không chấm nước mắm"), "nhớ không chấm nước mắm nhé", "vi", "en"),
        lambda: say(
            cl("Dip in fish sauce", "không chấm nước mắm"), "nhớ không chấm nước mắm nhé", "vi", "en"
        ),
    ],
)
def test_p2_failed_checks_stay_unverified(case):
    assert case().status == "unverified"


def test_p2_materials_parameters_and_inputs_are_unchanged():
    material = mat("200", "gram", "cho 200 gram đường vào", name="Sugar")
    assert say(material, "bây giờ cho 200 gram đường vào tô", text_language="en").status == "verified"
    assert say(par("3", "phút", "nấu 3 phút nhé"), "bây giờ nấu 3 phút nhé").status == "verified"
    assert show(command("python --version"), "python --version").status == "verified"


def quote_matched(method="ocr", sec=115.0, text="setup progress"):
    return ItemVerification(status="quote_matched", method=method, matched_text=text, matched_sec=sec)


def test_p2_quote_matched_makes_the_generation_need_review():
    from app.workers.runner import quality_status

    data = MockProvider(Settings(ai_provider="mock")).analyze(None, 10, "vi", {})["text"]
    draft = TutorialDraftV2.model_validate_json(data, context={"duration": 10})
    draft = draft.model_copy(update={"uncertainties": []})
    for step in draft.steps:
        step.needs_review, step.review_reason = False, None
    ok = VerificationReport(items={"p": ItemVerification(status="verified", method="ocr")}, **ENGINES)
    flagged = VerificationReport(items={"p": quote_matched()}, **ENGINES)
    assert not pipeline.needs_review(ok) and pipeline.needs_review(flagged)
    assert (quality_status(draft, ok), quality_status(draft, flagged)) == ("succeeded", "needs_review")


# ---- P2 rendering ---------------------------------------------------------------------------------


def draft_with(language, **collections):
    data = MockProvider(Settings(ai_provider="mock")).analyze(None, 10, language, {})["text"]
    payload = TutorialDraftV2.model_validate_json(data, context={"duration": 10}).model_dump(by_alias=True)
    payload.update(language=language, **collections)
    return TutorialDraftV2.model_validate(payload, context={"duration": 10})


def screen_claim(text, ost, scope="tutorial"):
    spans = [{"start_sec": 1, "end_sec": 3, "source": "visual", "description": "Source"}]
    return {"text": text, "evidence_spans": spans, "basis": "observed", "scope": scope, "on_screen_text": ost}


def render_with(draft, items):
    report = VerificationReport(items=items, **ENGINES)
    return render_markdown(
        draft, NS(original_name="v.mp4", duration_sec=10), "m", NS(id="g", created_at="t"), {}, report
    )


def test_p2_badge_and_review_line_vi():
    draft = draft_with("vi", prerequisites=[screen_claim(LIVE_CLAIM, "Setup Progress")])
    text = render_with(draft, {"prerequisites/0": quote_matched(sec=7.0)})
    main, review = text.split("## Điểm chưa rõ", 1)
    assert "· ≈ khớp nguyên văn chữ trên màn hình [00:00:07](#t=7.000): “setup progress”" in main
    assert "✓" not in main.split("## Chuẩn bị", 1)[1].split("##", 1)[0]
    assert "Chuẩn bị, câu diễn giải chưa kiểm chứng: Đã hoàn tất cài đặt Python trên Windows\\." in review
    spoken = render_with(draft, {"prerequisites/0": quote_matched("asr", 7.0, "nhấn nút install")})
    assert "· ≈ khớp nguyên văn lời nói [00:00:07](#t=7.000): “nhấn nút install”" in spoken


def test_p2_badge_and_review_line_en_with_escaping_and_truncation():
    long = "click *here* " + "x" * 100
    draft = draft_with("en", safety=[screen_claim("Unplug first", "Unplug")])
    text = render_with(draft, {"safety/0": quote_matched("ocr", 9.0, long)})
    shown = "click \\*here\\* " + "x" * 67 + "…"  # 80 characters of matched text, then escaped
    assert f"· ≈ quote matches on-screen text [00:00:09](#t=9.000): “{shown}”" in text
    assert "Safety, paraphrase not verified: Unplug first" in text.split("## Needs review", 1)[1]
    spoken = render_with(draft, {"safety/0": quote_matched("asr", None, "unplug it")})
    assert "· ≈ quote matches speech: “unplug it”" in spoken


def test_p2_step_tip_review_line_names_the_step():
    draft = draft_with("vi")
    payload = draft.model_dump(by_alias=True)
    payload["steps"][0]["tips"] = [screen_claim("Bấm Install", "Install now")]
    draft = TutorialDraftV2.model_validate(payload, context={"duration": 10})
    text = render_with(draft, {"steps/0/tips/0": quote_matched()})
    assert "Mẹo (bước 1), câu diễn giải chưa kiểm chứng: Bấm Install" in text.split("## Điểm chưa rõ", 1)[1]


# ---- P2a: a claim verifies only word for word -----------------------------------------------------

SUBSETS = [
    ("vi", "Không chạm vào chảo", "không chạm vào chảo cho đến khi nguội"),
    ("en", "Add salt", "add salt only if needed"),
    ("vi", "Rút điện", "rút điện sau khi tắt máy"),
    ("en", "Bake until golden", "bake until golden then rest 10 minutes"),
    ("vi", "Cài đặt Python", "cài đặt Python thất bại"),
    ("en", "Python is installed", "python is installed incorrectly"),
    ("vi", "Uống thuốc", "uống thuốc là sai"),
    ("en", "Use bleach", "use bleach and you will ruin it"),
    ("en", "Press the red button", "press the red button and the machine explodes"),
]
SUPERSETS = [
    ("en", "Add salt and pepper", "add salt"),
    ("en", "Install Python and reboot the computer", "install python"),
    ("vi", "Rút điện và tháo pin ra", "rút điện"),
    ("en", "Click Install and then delete the old folder", "click install"),
]
OPPOSITES = [
    ("vi", "Bật nguồn điện", "tắt nguồn điện"),
    ("en", "Enable the firewall", "disable the firewall"),
    ("en", "Uncheck the box", "check the box"),
    ("en", "Turn left at the valve", "turn right at the valve"),
    ("en", "Select the first option", "select the last option"),
    ("en", "Press the red button", "press the green button"),
    ("en", "Save the file", "save the files"),
]


@pytest.mark.parametrize("lang,text,quote", SUBSETS + SUPERSETS + OPPOSITES)
def test_p2a_claims_that_are_not_their_quote_word_for_word_are_quote_matched(lang, text, quote):
    """Review probes: every guard passes (the numbers agree), but the claim says something else."""
    out = say(cl(text, quote), f"okay so {quote} right now", lang, lang)
    assert out.status == "quote_matched", out.reason


@pytest.mark.parametrize("lang,text,quote", SUPERSETS + OPPOSITES)
def test_p2a_on_screen_claims_that_are_not_their_text_word_for_word_are_quote_matched(lang, text, quote):
    speech = Transcript(language=lang, words=[Word(start=0.0, end=0.3, text="ok")])
    item = observed(text, quote, 10, 12)
    out = verify_item("p", item, speech, [(11.0, "Menu\n" + quote)], SETTINGS, text_language=lang)
    assert out.status == "quote_matched", out.reason


def test_p2a_only_case_whitespace_and_punctuation_may_differ():
    assert say(
        cl("Nhấn nút Install.", "nhấn nút install"), "giờ nhấn nút install nhé", "vi", "vi"
    ).status == ("verified")
    item = cl("“Nhấn  nút” Install!", "nhấn nút, install")
    assert say(item, "giờ nhấn nút, install nhé", "vi", "vi").status == "verified"
    assert show(cl("Giá $5", ost="Giá $ 5"), "Giá $ 5", text_language="vi").status == "verified"
    # diacritics stay significant
    assert say(cl("Nhan nut Install", "nhấn nút install"), "giờ nhấn nút install nhé", "vi", "vi").status == (
        "quote_matched"
    )


# ---- P2b: meaningful punctuation and word boundaries stay -----------------------------------------

PUNCTUATION_CHANGES = [
    ("Run rm rf", "run rm -rf"),
    ("Run python m venv", "run python -m venv"),
    ("Run git commit m", "run git commit -m"),
    ("Use flag force", "use flag --force"),
    ("Delete git folder", "delete .git folder"),
    ("Open env", "open .env"),
    ("Install NET", "install .NET"),
    ("Install C", "install C#"),
    ("Add PATH", "add %PATH%"),
    ("Go to etc", "go to /etc"),
    ("Press the button", "press the - button"),
    ("Salt pepper", "salt & pepper"),
    ("Use the key", "use the * key"),
    ("Use the key", "use the – key"),
]
WORD_SPLITS = [
    ("Apart from the pan", "a part from the pan"),
    ("Move away", "move a way"),
    ("Anyone can do it", "any one can do it"),
    ("Take it off", "take it of f"),
]


@pytest.mark.parametrize("text,quote", PUNCTUATION_CHANGES + WORD_SPLITS)
def test_p2b_punctuation_and_word_boundaries_are_significant(text, quote):
    out = say(cl(text, quote), f"okay so {quote} right now", "en", "en")
    assert out.status == "quote_matched", out.reason
    speech = Transcript(language="en", words=[Word(start=0.0, end=0.3, text="ok")])
    item = observed(text, quote, 10, 12)
    out = verify_item("p", item, speech, [(11.0, "Menu\n" + quote)], SETTINGS, text_language="en")
    assert out.status == "quote_matched", out.reason


def test_p2b_sentence_marks_and_spaces_around_symbols_may_differ():
    assert say(
        cl("Nhấn nút Install.", "nhấn nút install"), "giờ nhấn nút install nhé", "vi", "vi"
    ).status == ("verified")
    assert show(cl("Giá $5", ost="Giá $ 5"), "Giá $ 5", text_language="vi").status == "verified"
    assert say(cl("Is it safe?", "is it safe"), "so is it safe now", "en", "en").status == "verified"
    item = cl("Run rm -rf", "run rm -rf")
    assert say(item, "okay so run rm -rf right now", "en", "en").status == "verified"
    item = observed("Open .env", "open .env", 10, 12)
    assert verify_item("p", item, EN_SPEECH, [(11.0, "open .env")], SETTINGS, text_language="en").status == (
        "verified"
    )
