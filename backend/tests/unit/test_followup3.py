"""Follow-up 3 (rulings X1-X4): quantities from an English video verified for a Vietnamese document.

Strings come from the live cooking run of 26/10 (docs/live-verification.md): an English transcript,
English on-screen captions, a Vietnamese draft. Every case that could hide a wrong value stays
`unverified`."""

import pytest
from app.schemas.verification import Transcript, Word
from app.services.verification import lexicon
from app.services.verification.matcher import NO_NAME, normalize, verify_item
from app.services.verification.numbers import number_tokens
from test_matcher import SCREEN_ONLY, SETTINGS, transcript
from test_matcher_final_review import mat, par

# the cooking video's narration has words (rulings R13 + R16b), in English
EN_SPEECH = Transcript(language="en", words=[Word(start=0.0, end=0.3, text="Hi")])
COOK_7_10 = "Cover with a lid and cook for 7 to 10 minutes. It should cook very low and slow."
COOK_5 = "slap a lid on it, and let it cook for another 5 minutes or so. Getting pancakes fluffy"


def screen(item, *frames, speech=EN_SPEECH, text_language="vi"):
    shots = [(11.0, f) for f in frames]
    return verify_item("p", item, speech, shots, SETTINGS, text_language=text_language)


def heard(item, spoken, lang="en", text_language="vi"):
    return verify_item(
        "p", item, transcript(spoken, language=lang), None, SETTINGS, text_language=text_language
    )


# ---- X1: the item name is not looked for in on-screen text of another language -------------------


@pytest.mark.parametrize(
    "item,frame",
    [
        (par("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Milk 4tsp"),
        (par("3", "tbsp", ost="All purpose flour 3 tbsp", name="Bột mì"), "All purpose flour 3 tbsp"),
        (mat("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Milk 4tsp"),
        (mat("1/2", "tsp", ost="Vanilla extract 1/2 tsp", name="Chiết xuất Vani"), "Vanilla extract 1/2 tsp"),
        (mat("3", "tbsp", ost="All purpose flour 3 tbsp", name="Bột mì đa dụng"), "All purpose flour 3 tbsp"),
    ],
)
def test_x1_live_cooking_quantities_verify_across_languages(item, frame):
    out = screen(item, frame)
    assert (out.status, out.method) == ("verified", "ocr")


def test_x1_name_still_checked_when_draft_and_video_share_a_language():
    vi_speech = Transcript(language="vi", words=[Word(start=0.0, end=0.3, text="chào")])
    wrong = mat("200", "g", ost="Đường 200 g", name="Muối")
    out = screen(wrong, "Đường 200 g", speech=vi_speech, text_language="vi")
    assert (out.status, out.reason) == ("unverified", NO_NAME)
    spoken = mat("200", "gram", "cho 200 gram đường vào", name="Muối")
    assert heard(spoken, "bây giờ cho 200 gram đường vào tô", "vi", "vi").status == "unverified"
    assert screen(
        mat("200", "g", ost="Đường 200 g", name="Đường"), "Đường 200 g", speech=vi_speech
    ).status == ("verified")


def test_x1_name_still_checked_without_a_draft_language():
    out = screen(mat("200", "g", ost="Sugar 200 g", name="Muối"), "Sugar 200 g", text_language=None)
    assert (out.status, out.reason) == ("unverified", NO_NAME)


def test_x1_material_without_quantity_keeps_the_name_check():
    # nothing but the name would be checked: 'Muối' must not verify from a 'Sugar' caption
    out = screen(mat(None, None, ost="Sugar", name="Muối"), "Sugar")
    assert (out.status, out.reason) == ("unverified", NO_NAME)


# ---- X2: units through the canonical table, glued units split ---------------------------------------


def test_x2_live_cooking_time_in_minutes_verifies_from_english_speech():
    # 'or so' is not one of the modifiers or range words the matcher blocks ('about 5 min' verifies too)
    item = par("5", "phút", quote="cook for another 5 minutes or so", name="Thời gian nấu")
    out = heard(item, COOK_5)
    assert (out.status, out.method) == ("verified", "asr")
    assert "5 minutes" in out.matched_text


@pytest.mark.parametrize(
    "unit,quote,spoken",
    [
        ("thìa cà phê", "add 4 teaspoons of milk", "now add 4 teaspoons of milk to the yolks"),
        ("muỗng canh", "add 3 tablespoons of flour", "then add 3 tablespoons of flour slowly"),
        ("giây", "whisk for 30 seconds", "whisk for 30 seconds until smooth"),
        ("giờ", "chill for 2 hours", "chill for 2 hours in the fridge"),
    ],
)
def test_x2_translated_units_verify(unit, quote, spoken):
    value = next(w for w in quote.split() if w.isdigit())
    item = par(value, unit, quote=quote, name="x")
    assert heard(item, spoken).status == "verified"


@pytest.mark.parametrize(
    "item,frame",
    [
        (par("4", "tsp", ost="Milk 4 tbsp", name="Sữa"), "Milk 4 tbsp"),
        (par("4", "thìa cà phê", ost="Milk 4 tbsp", name="Sữa"), "Milk 4 tbsp"),
        (par("180", "°C", ost="Bake 180°F", name="Nướng"), "Bake 180°F"),
        (par("180", "độ C", ost="Bake at 180 degrees F", name="Nướng"), "Bake at 180 degrees F"),
        (mat("2", "quả", ost="2 eggs", name="Trứng"), "2 eggs"),  # 'quả' is not in the table
        (mat("2", "eggs", ost="2 eggs", name="Trứng"), "2 eggs"),  # neither is 'eggs', languages differ
        (mat("200", "g", ost="Sugar 200 ml", name="Đường"), "Sugar 200 ml"),
    ],
)
def test_x2_unit_mismatch_or_unknown_across_languages_stays_unverified(item, frame):
    assert screen(item, frame).status == "unverified"


@pytest.mark.parametrize(
    "unit,quote,spoken",
    [
        ("phút", "cook for 5 hours", "cook for 5 hours on low"),
        ("phút", "cook for 5 seconds", "cook for 5 seconds on low"),
        ("thìa cà phê", "add 4 tablespoons of milk", "now add 4 tablespoons of milk"),
        ("quả", "add 2 eggs", "now add 2 eggs to the bowl"),
        ("°C", "bake at 350 degrees fahrenheit", "bake at 350 degrees fahrenheit for an hour"),
    ],
)
def test_x2_spoken_unit_mismatch_or_unknown_stays_unverified(unit, quote, spoken):
    value = next(w for w in quote.split() if w.isdigit())
    assert heard(par(value, unit, quote=quote, name="x"), spoken).status == "unverified"


def test_x2_imperial_units_are_in_the_table():
    assert screen(mat("8", "oz", ost="Cream cheese 8oz", name="Phô mai kem"), "Cream cheese 8oz").status == (
        "verified"
    )
    assert screen(
        mat("8", "oz", ost="Cream cheese 8 lb", name="Phô mai kem"), "Cream cheese 8 lb"
    ).status == ("unverified")
    assert screen(mat("1", "oz", ost="Milk 1 fl oz", name="Sữa"), "Milk 1 fl oz").status == "unverified"


def test_x2_unknown_unit_compares_as_written_in_one_language():
    item = mat("2", "quả", "cho 2 quả trứng vào", name="Trứng")
    assert heard(item, "bây giờ cho 2 quả trứng vào tô", "vi", "vi").status == "verified"
    other = mat("2", "cái", "cho 2 quả trứng vào", name="Trứng")
    assert heard(other, "bây giờ cho 2 quả trứng vào tô", "vi", "vi").status == "unverified"


def test_x2_unit_is_the_word_after_the_number():
    # the unit word must follow the value, not merely appear somewhere in the quote
    item = par("5", "phút", quote="cook 5 hours then rest a few minutes", name="x")
    assert heard(item, "cook 5 hours then rest a few minutes please").status == "unverified"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Milk 4tsp", "milk 4 tsp"),
        ("Bột 200g", "bột 200 g"),
        ("Vanilla 1/2tsp", "vanilla 1/2 tsp"),
        ("Nấu 5phút", "nấu 5 phút"),
        ("x2", "x2"),
        ("2x", "2x"),
        ("-18°C", "-18°c"),
        ("1h30", "1h30"),
        ("mp3s", "mp3s"),
        ("1st", "1st"),
        ("4k", "4k"),
    ],
)
def test_x2_glued_units_are_split_without_touching_numbers(raw, expected):
    assert normalize(raw) == expected
    assert number_tokens(lexicon.clean(raw), None) == number_tokens(raw, None)


def test_x2_glued_split_keeps_numbers_apart():
    assert number_tokens("Milk 4tsp", None) == ["4"]
    assert number_tokens("Milk 40tsp", None) == ["40"]
    assert number_tokens("1/2tsp", None) == ["1/2"]
    assert screen(par("4", "tsp", ost="Milk 40tsp", name="Sữa"), "Milk 40tsp").status == "unverified"
    assert screen(par("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Milk 40tsp").status == "unverified"
    assert screen(par("40", "tsp", ost="Milk 40tsp", name="Sữa"), "Milk 4tsp").status == "unverified"
    half = par("1/2", "tsp", ost="Vanilla 1/2tsp", name="Vani")
    assert screen(half, "Vanilla 1/2tsp").status == "verified"
    assert screen(par("2", "tsp", ost="Vanilla 1/2tsp", name="Vani"), "Vanilla 1/2tsp").status == "unverified"
    assert (
        screen(par("1/2", "tsp", ost="Vanilla 1/2tsp", name="Vani"), "Vanilla 1/3tsp").status == "unverified"
    )


def test_x2_glued_and_spaced_units_align_on_screen():
    assert screen(par("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Milk 4 tsp").status == "verified"
    assert screen(par("4", "tsp", ost="Milk 4 tsp", name="Sữa"), "Milk 4tsp").status == "verified"


def test_x2_glued_sign_rules_unchanged():
    assert (
        screen(par("18", "°C", ost="Freezer -18°C", name="Tủ đông"), "Freezer -18°C").status == "unverified"
    )
    assert screen(par("18", "°C", ost="Freezer 18°C", name="Tủ đông"), "Freezer-18°C").status == "unverified"
    assert number_tokens("Freezer-18°C", None) == ["~-18"]
    assert number_tokens("Speed x2", None) == number_tokens("Speed 2x", None) == ["2"]


# ---- X3: a range value meets the same range -----------------------------------------------------------


def test_x3_live_cooking_range_verifies():
    item = par("7-10", "phút", quote="cook for 7 to 10 minutes", name="Thời gian nấu")
    out = heard(item, COOK_7_10)
    assert (out.status, out.method) == ("verified", "asr")
    assert out.matched_text == "cook for 7 to 10 minutes"  # as spoken, not as joined


@pytest.mark.parametrize(
    "value,quote,spoken,lang",
    [
        ("7-10", "nấu từ 7 đến 10 phút", "đậy nắp rồi nấu từ 7 đến 10 phút nhé", "vi"),
        ("7-10", "nấu từ bảy đến mười phút", "đậy nắp rồi nấu từ bảy đến mười phút nhé", "vi"),
        ("7-10", "cook for seven to ten minutes", "cover and cook for seven to ten minutes please", "en"),
        ("7-10", "cook for 7-10 minutes", "cover and cook for 7-10 minutes please", "en"),
        ("7 đến 10", "cook for 7 to 10 minutes", "cover and cook for 7 to 10 minutes please", "en"),
    ],
)
def test_x3_range_forms_verify(value, quote, spoken, lang):
    # same language: the name must be in the quote (I2), so it is the verb here
    item = par(value, "phút", quote=quote, name="Nấu" if lang == "vi" else "Thời gian nấu")
    assert heard(item, spoken, lang).status == "verified"


def test_x3_range_on_screen_verifies():
    item = par("7-10", "phút", ost="Cook 7 to 10 min", name="Nấu")
    out = screen(item, "Menu\nCook 7 to 10 min")
    assert (out.status, out.matched_text) == ("verified", "cook 7 to 10 min")  # as shown, not as joined
    dashed = par("7-10", "phút", ost="Cook 7–10 min", name="Nấu")
    assert screen(dashed, "Cook 7–10 min").status == "verified"


@pytest.mark.parametrize(
    "value,quote,spoken",
    [
        ("7", "cook for 7 to 10 minutes", COOK_7_10),
        ("10", "cook for 7 to 10 minutes", COOK_7_10),
        ("7-10", "cook for 7 to 12 minutes", "cover and cook for 7 to 12 minutes please"),
        ("7-10", "cook for 7 minutes", "cover and cook for 7 minutes please"),
        ("7-10", "cook for 7 to 10 minutes", "cover and cook for 7 to 12 minutes please"),
        ("7-10", "cook for 7 to 10 minutes", "cover and cook for 7 to 10 to 12 minutes please"),
        ("7-10", "cook for 7 or 10 minutes", "cover and cook for 7 or 10 minutes please"),
        ("7-10", "cook for 7 to 10 minutes", "cover and cook for 7 to 10 or 12 minutes please"),
        ("7-10", "cook for 7 to 10 minutes", "cover and cook for 7 to 10 minutes and a half"),
        ("7-10", "cook between 7 and 10 minutes", "cover and cook between 7 and 10 minutes please"),
        ("1-2", "wait 1/2 to 2 minutes", "now wait 1/2 to 2 minutes please"),
        ("7-10", "cook for 7 to 10 hours", "cover and cook for 7 to 10 hours please"),
        ("7-10", "cook for 7 to 10.5 minutes", "cover and cook for 7 to 10.5 minutes please"),
        ("7-10", "cook for 5 7 to 10 minutes", "cover and cook for 5 7 to 10 minutes please"),
        ("7-10", "freeze at -7 to 10 minutes", "now freeze at -7 to 10 minutes please"),
    ],
)
def test_x3_range_mismatches_stay_unverified(value, quote, spoken):
    item = par(value, "phút", quote=quote, name="Thời gian nấu")
    assert heard(item, spoken).status == "unverified"


def test_x3_range_on_screen_mismatches_stay_unverified():
    assert screen(par("7-10", "phút", ost="Cook 7 to 12 min", name="Nấu"), "Cook 7 to 12 min").status == (
        "unverified"
    )
    assert screen(par("7-10", "phút", ost="Cook 7 to 10 min", name="Nấu"), "Cook 7 to 12 min").status == (
        "unverified"
    )
    assert screen(par("7", "phút", ost="Cook 7 to 10 min", name="Nấu"), "Cook 7 to 10 min").status == (
        "unverified"
    )


# ---- regression: R13 still needs speech with words for on-screen numbers -------------------------------


def test_x1_does_not_bypass_r13():
    silent = Transcript(language="en", words=[])
    out = screen(par("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Milk 4tsp", speech=silent)
    assert out.status == "unverified"
    assert (
        verify_item(
            "p",
            par("4", "tsp", ost="Milk 4tsp", name="Sữa"),
            None,
            [(11.0, "Milk 4tsp")],
            SETTINGS,
            text_language="vi",
        ).status
        == "unverified"
    )
    assert SCREEN_ONLY.language == "vi"


# ---- X4: prompt asks for on-screen quantities as observed ---------------------------------------------


def test_x4_prompt_prefers_on_screen_quantities():
    from app.providers.gemini import PROMPT

    text = PROMPT.read_text()
    assert "kể cả khi người nói cũng đọc" in text
    assert "basis=stated chỉ khi" in text
