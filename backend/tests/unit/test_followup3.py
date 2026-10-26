"""Follow-up 3 (rulings X1-X5, X1a, X2a): quantities from an English video checked for a Vietnamese
document.

Strings come from the live cooking run of 26/10 (docs/live-verification.md): an English transcript,
English on-screen captions, a Vietnamese draft. Across languages a value that matches but whose name
cannot be tied to the source is `quote_matched` (≈), never `verified`; every case that could hide a wrong
value stays `unverified`."""

import pytest
from app.schemas.verification import Transcript, Word
from app.services.verification import lexicon
from app.services.verification.matcher import NEGATED, NO_NAME, normalize, verify_item
from app.services.verification.numbers import number_tokens
from test_matcher import SCREEN_ONLY, SETTINGS, transcript
from test_matcher_final_review import mat, par

# the cooking video's narration has words (rulings R13 + R16b), in English
EN_SPEECH = Transcript(language="en", words=[Word(start=0.0, end=0.3, text="Hi")])
VI_SPEECH = Transcript(language="vi", words=[Word(start=0.0, end=0.3, text="chào")])
COOK_7_10 = "Cover with a lid and cook for 7 to 10 minutes. It should cook very low and slow."
COOK_5 = "slap a lid on it, and let it cook for another 5 minutes or so. Getting pancakes fluffy"
NAME_UNPROVEN = "quote_matched"  # X1a: the values matched; the translated name is not proven


def screen(item, *frames, speech=EN_SPEECH, text_language="vi"):
    shots = [(11.0, f) for f in frames]
    return verify_item("p", item, speech, shots, SETTINGS, text_language=text_language)


def heard(item, spoken, lang="en", text_language="vi"):
    return verify_item(
        "p", item, transcript(spoken, language=lang), None, SETTINGS, text_language=text_language
    )


# ---- X1 + X1a: names across languages ---------------------------------------------------------------


@pytest.mark.parametrize(
    "item,frame",
    [
        (mat("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Milk\n4tsp"),
        (
            mat("1/2", "tsp", ost="Vanilla extract 1/2 tsp", name="Chiết xuất Vani"),
            "Vanilla extract\n1/2 tsp",
        ),
        # 'bột mì đa dụng' is its own dictionary entry: all-purpose flour
        (
            mat("3", "tbsp", ost="All purpose flour 3 tbsp", name="Bột mì đa dụng"),
            "All purpose flour\n3 tbsp",
        ),
        (mat(None, None, ost="Sugar", name="Đường"), "s\nSugar"),
    ],
)
def test_x1a_live_cooking_materials_verify_through_the_dictionary(item, frame):
    out = screen(item, frame)
    assert (out.status, out.method) == ("verified", "ocr")


@pytest.mark.parametrize(
    "item,frame,row",
    [
        (par("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Milk\n4tsp", "Milk 4tsp"),
        (par("1/2", "tsp", ost="Vanilla extract 1/2 tsp", name="Vani"), "Vanilla extract\n1/2 tsp", None),
        (par("3", "tbsp", ost="All purpose flour 3 tbsp", name="Bột mì"), "All purpose flour\n3 tbsp", None),
    ],
)
def test_x1a_parameters_across_languages_are_only_quote_matched(item, frame, row):
    out = screen(item, frame)
    assert (out.status, out.method) == (NAME_UNPROVEN, "ocr")
    assert out.matched_text == (row or frame.replace("\n", " "))


@pytest.mark.parametrize(
    "item,frame,row",
    [
        (mat("200", "g", ost="Sugar 200g", name="Muối"), "Sugar 200g", "Sugar 200g"),
        (mat("3", "tbsp", ost="Sugar 3 tbsp", name="Bột mì"), "Sugar 3 tbsp", "Sugar 3 tbsp"),
        # on_screen_text holds only the number: the whole row is shown, with the ingredient it names
        (mat("5", "g", ost="5g", name="Muối"), "Ingredients\nSugar 5g", "Sugar 5g"),
        (par("180", "°C", ost="Fridge 180°C", name="Nhiệt độ lò"), "Fridge 180°C", "Fridge 180°C"),
        (par("high", None, ost="Fan: high", name="Mức lửa"), "Fan: high", "Fan: high"),
        (mat(None, None, ost="Sugar", name="Muối"), "Sugar", "Sugar"),
        # modifiers that make another ingredient, and words left out of the dictionary
        (mat("200", "ml", ost="Coconut milk 200 ml", name="Sữa"), "Coconut milk 200 ml", None),
        (mat("2", None, ost="2 egg yolks", name="Trứng"), "2 egg yolks", None),
        (mat("200", "g", ost="Rice flour 200g", name="Bột mì"), "Rice flour 200g", None),
        (mat("3", "tbsp", ost="All purpose flour 3 tbsp", name="Bột mì"), "All purpose flour 3 tbsp", None),
        (mat("1/2", "tsp", ost="Vanilla extract 1/2 tsp", name="Vani"), "Vanilla extract 1/2 tsp", None),
        (mat("1", None, ost="Bell pepper 1", name="Tiêu"), "Bell pepper 1", None),
        (mat("50", "g", ost="Butter 50g", name="Bơ"), "Butter 50g", None),
        (mat("2", "tbsp", ost="Oil 2 tbsp", name="Dầu"), "Oil 2 tbsp", None),
    ],
)
def test_x1a_unproven_names_are_quote_matched_with_the_whole_row(item, frame, row):
    out = screen(item, frame)
    assert out.status == NAME_UNPROVEN
    assert out.matched_text == (row or frame)


def test_x1a_screen_row_with_a_modifier_outside_on_screen_text():
    # the model copied 'Milk 4tsp' from a row that says 'Coconut milk 4tsp'
    out = screen(mat("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Coconut milk 4tsp")
    assert (out.status, out.matched_text) == (NAME_UNPROVEN, "Coconut milk 4tsp")


def test_x1a_a_vietnamese_caption_in_an_english_video_proves_the_name_word_for_word():
    item = par("180", "°C", ost="Nướng ở 180°C", name="Nướng")
    assert screen(item, "Nướng ở 180°C").status == "verified"


@pytest.mark.parametrize(
    "item,spoken,status",
    [
        (
            mat(None, None, quote="now add the sugar", name="Muối"),
            "okay now add the sugar to the bowl",
            NAME_UNPROVEN,
        ),
        (
            mat("200", "g", quote="add 200 grams of sugar", name="Muối"),
            "now add 200 grams of sugar",
            NAME_UNPROVEN,
        ),
        (
            mat("200", "g", quote="add 200 grams of sugar", name="Đường"),
            "now add 200 grams of sugar",
            "verified",
        ),
        (
            mat("4", "thìa cà phê", "add 4 teaspoons of milk", name="Sữa"),
            "now add 4 teaspoons of milk",
            "verified",
        ),
        (mat("4", "tsp", "add 4 tsp", name="Sữa"), "now add 4 tsp coconut milk", NAME_UNPROVEN),
    ],
)
def test_x1a_spoken_names_across_languages(item, spoken, status):
    out = heard(item, spoken)
    assert (out.status, out.method) == (status, "asr")


def test_x1a_spoken_quote_matched_shows_the_segment():
    out = heard(mat("200", "g", quote="add 200 grams of sugar", name="Muối"), "now add 200 grams of sugar")
    assert out.matched_text == "add 200 grams of sugar"


def test_x1a_english_draft_of_a_vietnamese_video_uses_the_dictionary_backwards():
    sugar = mat("200", "gram", "cho 200 gram đường vào", name="Sugar")
    assert heard(sugar, "bây giờ cho 200 gram đường vào tô", "vi", "en").status == "verified"
    salt = mat("200", "gram", "cho 200 gram đường vào", name="Salt")
    assert heard(salt, "bây giờ cho 200 gram đường vào tô", "vi", "en").status == NAME_UNPROVEN


def test_x1a_dictionary_is_strict_one_to_one():
    assert lexicon.ingredient_words("Sữa") == [["milk"]]
    assert lexicon.ingredient_words("Bột mì đa dụng") == [["all", "purpose", "flour"]]
    for polysemous in ("Bột", "Bơ", "Dầu", "Chanh", "Kem", "Thịt"):
        assert lexicon.ingredient_words(polysemous) == []
    english = [w for forms in lexicon.INGREDIENTS.values() for w in forms.split("|")]
    shared = {"pepper", "yeast", "pork", "soy sauce"}  # one English word, synonymous Vietnamese names
    assert {w for w in english if english.count(w) > 1} == shared


def test_x1_name_still_checked_when_draft_and_video_share_a_language():
    wrong = mat("200", "g", ost="Đường 200 g", name="Muối")
    out = screen(wrong, "Đường 200 g", speech=VI_SPEECH, text_language="vi")
    assert (out.status, out.reason) == ("unverified", NO_NAME)
    spoken = mat("200", "gram", "cho 200 gram đường vào", name="Muối")
    assert heard(spoken, "bây giờ cho 200 gram đường vào tô", "vi", "vi").status == "unverified"
    right = mat("200", "g", ost="Đường 200 g", name="Đường")
    assert screen(right, "Đường 200 g", speech=VI_SPEECH).status == "verified"


def test_x1_name_still_checked_without_a_draft_language():
    out = screen(mat("200", "g", ost="Sugar 200 g", name="Muối"), "Sugar 200 g", text_language=None)
    assert (out.status, out.reason) == ("unverified", NO_NAME)


# ---- X2 + X2a: units --------------------------------------------------------------------------------


def test_x2_live_cooking_time_in_minutes_matches_english_speech():
    # 'or so' is not one of the modifiers or range words the matcher blocks ('about 5 min' verifies too);
    # the value and unit match, the parameter name is a translation (X1a)
    item = par("5", "phút", quote="cook for another 5 minutes or so", name="Thời gian nấu")
    out = heard(item, COOK_5)
    assert (out.status, out.method) == (NAME_UNPROVEN, "asr")
    assert out.matched_text == "cook for another 5 minutes or so"


@pytest.mark.parametrize(
    "item,spoken",
    [
        (
            mat("4", "thìa cà phê", "add 4 teaspoons of milk", name="Sữa"),
            "now add 4 teaspoons of milk to the yolks",
        ),
        (
            mat("3", "muỗng canh", "add 3 tablespoons of flour", name="Bột mì"),
            "then add 3 tablespoons of flour",
        ),
        (mat("1", "chén", "add 1 cup of sugar", name="Đường"), "now add 1 cup of sugar"),
        (mat("2", "lít", "add 2 liters of water", name="Nước"), "now add 2 liters of water"),
    ],
)
def test_x2_translated_units_verify(item, spoken):
    assert heard(item, spoken).status == "verified"


@pytest.mark.parametrize(
    "unit,quote,spoken",
    [
        ("giây", "whisk for 30 seconds", "whisk for 30 seconds until smooth"),
        ("giờ", "chill for 2 hours", "chill for 2 hours in the fridge"),
    ],
)
def test_x2_translated_time_units_reach_the_name_check(unit, quote, spoken):
    value = next(w for w in quote.split() if w.isdigit())
    assert heard(par(value, unit, quote=quote, name="x"), spoken).status == NAME_UNPROVEN


@pytest.mark.parametrize(
    "item,frame",
    [
        (mat("4", "tsp", ost="Milk 4 tbsp", name="Sữa"), "Milk 4 tbsp"),
        (mat("4", "thìa cà phê", ost="Milk 4 tbsp", name="Sữa"), "Milk 4 tbsp"),
        (par("180", "°C", ost="Bake 180°F", name="Nướng"), "Bake 180°F"),
        (par("180", "độ C", ost="Bake at 180 degrees F", name="Nướng"), "Bake at 180 degrees F"),
        (mat("2", "quả", ost="2 eggs", name="Trứng"), "2 eggs"),  # 'quả' is not in the table
        (mat("2", "eggs", ost="2 eggs", name="Trứng"), "2 eggs"),  # neither is 'eggs', languages differ
        (mat("200", "g", ost="Sugar 200 ml", name="Đường"), "Sugar 200 ml"),
        (par("25", "Nm", ost="Torque 25 Nm", name="Lực siết"), "Torque 25 Nm"),
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
        # reviewer minor: spellings without Vietnamese marks are units only in OCR text
        ("độ", "these 2 do it", "and these 2 do it well"),
        ("lít", "the 5 lit candles", "look at the 5 lit candles"),
    ],
)
def test_x2_spoken_unit_mismatch_or_unknown_stays_unverified(unit, quote, spoken):
    value = next(w for w in quote.split() if w.isdigit())
    assert heard(par(value, unit, quote=quote, name="x"), spoken).status == "unverified"


def test_x2_ocr_reads_unit_spellings_without_marks():
    assert screen(mat("1", "lít", ost="Water 1 lit", name="Nước"), "Water 1 lit").status == "verified"


@pytest.mark.parametrize(
    "unit,quote,spoken",
    [
        ("chén", "cho 1 cốc đường vào", "bây giờ cho 1 cốc đường vào tô"),
        ("thìa", "cho 2 thìa canh đường", "giờ cho 2 thìa canh đường vào"),
        ("thìa", "cho 2 thìa cà phê đường", "giờ cho 2 thìa cà phê đường vào"),
        ("muỗng", "cho 2 muỗng canh đường", "giờ cho 2 muỗng canh đường vào"),
        ("muỗng canh", "cho 2 muỗng đường", "giờ cho 2 muỗng đường vào"),
        ("thìa canh", "cho 2 muỗng canh đường", "giờ cho 2 muỗng canh đường vào"),
        ("giờ", "ủ 2 tiếng đường", "giờ ta ủ 2 tiếng đường nhé"),
        ("giờ", "học 2 tiếng anh đường", "mỗi ngày học 2 tiếng anh đường nhé"),
    ],
)
def test_x2a_same_language_units_compare_as_written(unit, quote, spoken):
    value = next(w for w in quote.split() if w.isdigit())
    out = heard(mat(value, unit, quote, name="đường"), spoken, "vi", "vi")
    assert (out.status, out.method) == ("unverified", "none")


def test_x2a_same_language_units_as_written_still_verify():
    item = mat("2", "thìa canh", "cho 2 thìa canh đường", name="đường")
    assert heard(item, "giờ cho 2 thìa canh đường vào", "vi", "vi").status == "verified"
    assert screen(
        mat("1", "chén", ost="Đường 1 cốc", name="Đường"), "Đường 1 cốc", speech=VI_SPEECH
    ).status == ("unverified")
    assert screen(
        mat("1", "chén", ost="Đường 1 chén", name="Đường"), "Đường 1 chén", speech=VI_SPEECH
    ).status == ("verified")


def test_x2_unknown_unit_compares_as_written_in_one_language():
    item = mat("2", "quả", "cho 2 quả trứng vào", name="Trứng")
    assert heard(item, "bây giờ cho 2 quả trứng vào tô", "vi", "vi").status == "verified"
    other = mat("2", "cái", "cho 2 quả trứng vào", name="Trứng")
    assert heard(other, "bây giờ cho 2 quả trứng vào tô", "vi", "vi").status == "unverified"


def test_x2_unit_is_the_word_after_the_number():
    item = par("5", "phút", quote="cook 5 hours then rest a few minutes", name="x")
    assert heard(item, "cook 5 hours then rest a few minutes please").status == "unverified"


def test_x2_imperial_units_are_in_the_table():
    assert screen(mat("8", "oz", ost="Cheese 8oz", name="Phô mai"), "Cheese 8oz").status == "verified"
    assert screen(mat("8", "oz", ost="Cheese 8 lb", name="Phô mai"), "Cheese 8 lb").status == "unverified"
    assert screen(mat("1", "oz", ost="Milk 1 fl oz", name="Sữa"), "Milk 1 fl oz").status == "unverified"


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
    assert screen(mat("4", "tsp", ost="Milk 40tsp", name="Sữa"), "Milk 40tsp").status == "unverified"
    assert screen(mat("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Milk 40tsp").status == "unverified"
    assert screen(mat("40", "tsp", ost="Milk 40tsp", name="Sữa"), "Milk 4tsp").status == "unverified"
    half = mat("1/2", "tsp", ost="Vanilla extract 1/2tsp", name="Chiết xuất vani")
    assert screen(half, "Vanilla extract 1/2tsp").status == "verified"
    two = mat("2", "tsp", ost="Vanilla extract 1/2tsp", name="Chiết xuất vani")
    assert screen(two, "Vanilla extract 1/2tsp").status == "unverified"
    assert screen(half, "Vanilla extract 1/3tsp").status == "unverified"


def test_x2_glued_and_spaced_units_align_on_screen():
    assert screen(mat("4", "tsp", ost="Milk 4tsp", name="Sữa"), "Milk 4 tsp").status == "verified"
    assert screen(mat("4", "tsp", ost="Milk 4 tsp", name="Sữa"), "Milk 4tsp").status == "verified"


def test_x2_glued_sign_rules_unchanged():
    assert (
        screen(par("18", "°C", ost="Freezer -18°C", name="Tủ đông"), "Freezer -18°C").status == "unverified"
    )
    assert screen(par("18", "°C", ost="Freezer 18°C", name="Tủ đông"), "Freezer-18°C").status == "unverified"
    assert number_tokens("Freezer-18°C", None) == ["~-18"]
    assert number_tokens("Speed x2", None) == number_tokens("Speed 2x", None) == ["2"]


# ---- X3: a range value meets the same range -----------------------------------------------------------


def test_x3_live_cooking_range_matches():
    item = par("7-10", "phút", quote="cook for 7 to 10 minutes", name="Thời gian nấu")
    out = heard(item, COOK_7_10)
    assert (out.status, out.method) == (NAME_UNPROVEN, "asr")  # X1a: a parameter across languages
    assert out.matched_text == "cook for 7 to 10 minutes"  # as spoken, not as joined


@pytest.mark.parametrize(
    "value,quote,spoken",
    [
        ("7-10", "nấu từ 7 đến 10 phút", "đậy nắp rồi nấu từ 7 đến 10 phút nhé"),
        ("7-10", "nấu từ bảy đến mười phút", "đậy nắp rồi nấu từ bảy đến mười phút nhé"),
        ("7-10", "nấu 7 tới 10 phút", "đậy nắp nấu 7 tới 10 phút nhé"),
        ("7 đến 10", "nấu 7 - 10 phút", "đậy nắp nấu 7 - 10 phút nhé"),
    ],
)
def test_x3_range_forms_verify(value, quote, spoken):
    assert heard(par(value, "phút", quote=quote, name="Nấu"), spoken, "vi", "vi").status == "verified"


@pytest.mark.parametrize(
    "value,quote,spoken",
    [
        ("7-10", "cook for seven to ten minutes", "cover and cook for seven to ten minutes please"),
        ("7-10", "cook for 7-10 minutes", "cover and cook for 7-10 minutes please"),
        ("7 đến 10", "cook for 7 to 10 minutes", "cover and cook for 7 to 10 minutes please"),
    ],
)
def test_x3_range_forms_match_across_languages(value, quote, spoken):
    assert heard(par(value, "phút", quote=quote, name="Thời gian nấu"), spoken).status == NAME_UNPROVEN


def test_x3_range_material_across_languages_verifies():
    item = mat("2-3", "chén", "add 2 to 3 cups of flour", name="Bột mì")
    assert heard(item, "now add 2 to 3 cups of flour").status == "verified"


def test_x3_range_on_screen():
    item = par("7-10", "phút", ost="Nấu 7 đến 10 phút", name="Nấu")
    out = screen(item, "Menu\nNấu 7 đến 10 phút", speech=VI_SPEECH)
    assert (out.status, out.matched_text) == ("verified", "nấu 7 đến 10 phút")  # as shown, not as joined
    dashed = par("7-10", "phút", ost="Nấu 7–10 phút", name="Nấu")
    assert screen(dashed, "Nấu 7–10 phút", speech=VI_SPEECH).status == "verified"
    english = par("7-10", "phút", ost="Cook 7 to 10 min", name="Nấu")
    out = screen(english, "Menu\nCook 7 to 10 min")
    assert (out.status, out.matched_text) == (NAME_UNPROVEN, "Cook 7 to 10 min")


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
    def shown(value, text, frame):
        return screen(par(value, "phút", ost=text, name="Nấu"), frame, speech=VI_SPEECH).status

    assert shown("7-10", "Nấu 7 đến 12 phút", "Nấu 7 đến 12 phút") == "unverified"
    assert shown("7-10", "Nấu 7 đến 10 phút", "Nấu 7 đến 12 phút") == "unverified"
    assert shown("7", "Nấu 7 đến 10 phút", "Nấu 7 đến 10 phút") == "unverified"


# ---- X5: a quantity said or shown under a negation ------------------------------------------------------


@pytest.mark.parametrize(
    "item,spoken,lang,text_language",
    [
        (
            mat("2", "chén", "đừng cho 2 chén đường", name="đường"),
            "nhớ là đừng cho 2 chén đường vào nhé",
            "vi",
            "vi",
        ),
        (
            mat("2", "chén", "don't add 2 cups of sugar", name="Đường"),
            "please don't add 2 cups of sugar",
            "en",
            "vi",
        ),
        (
            par("7-10", "phút", "don't cook 7 to 10 minutes", name="x"),
            "please don't cook 7 to 10 minutes",
            "en",
            "vi",
        ),
        (mat("200", "g", "don't add 200 g sugar", name="Đường"), "please don't add 200 g sugar", "en", "vi"),
        (
            par("7-10", "phút", "không nấu 7 đến 10 phút", name="nấu"),
            "nhớ là không nấu 7 đến 10 phút nhé",
            "vi",
            "vi",
        ),
    ],
)
def test_x5_negated_quote_is_unverified(item, spoken, lang, text_language):
    out = heard(item, spoken, lang, text_language)
    assert (out.status, out.reason) == ("unverified", NEGATED)


@pytest.mark.parametrize(
    "item,spoken",
    [
        (mat("2", "chén", "add 2 cups of sugar", name="Đường"), "never add 2 cups of sugar please"),
        (par("7-10", "phút", "cook for 7 to 10 minutes", name="x"), "do not cook for 7 to 10 minutes please"),
    ],
)
def test_x5_negation_right_before_the_matched_speech_is_unverified(item, spoken):
    assert heard(item, spoken).status == "unverified"


def test_x5_negated_screen_text():
    no_salt = mat("5", "g", ost="Salt 5g", name="Muối")
    assert screen(no_salt, "No salt 5g").status == "unverified"
    assert screen(mat("5", "g", ost="No salt 5g", name="Muối"), "No salt 5g").reason == NEGATED


def test_x5_spoken_decimal_khong_is_not_a_negation_for_a_quantity():
    item = mat("0.5", "lít", "cho không phẩy năm lít nước", name="nước")
    assert heard(item, "bây giờ cho không phẩy năm lít nước vào nồi", "vi", "vi").status == "verified"


# ---- regression: R13 still needs speech with words for on-screen numbers -------------------------------


def test_x1_does_not_bypass_r13():
    silent = Transcript(language="en", words=[])
    item = mat("4", "tsp", ost="Milk 4tsp", name="Sữa")
    assert screen(item, "Milk 4tsp", speech=silent).status == "unverified"
    shots = [(11.0, "Milk 4tsp")]
    assert verify_item("p", item, None, shots, SETTINGS, text_language="vi").status == "unverified"
    assert SCREEN_ONLY.language == "vi"


# ---- X4: prompt asks for on-screen quantities as observed ---------------------------------------------


def test_x4_prompt_prefers_on_screen_quantities():
    from app.providers.gemini import PROMPT

    text = PROMPT.read_text()
    assert "kể cả khi người nói cũng đọc" in text
    assert "basis=stated chỉ khi" in text


# ---- X1a rendering: a material whose translated name is unproven ---------------------------------------


def test_x1a_material_review_line_says_the_name_is_unchecked():
    from test_followup2 import draft_with, quote_matched, render_with

    spans = [{"start_sec": 1, "end_sec": 3, "source": "visual", "description": "Source"}]
    salt = {
        "name": "Muối",
        "quantity": "200",
        "unit": "g",
        "note": None,
        "evidence_spans": spans,
        "basis": "observed",
        "quote": None,
        "on_screen_text": "Sugar 200g",
    }
    text = render_with(
        draft_with("vi", materials=[salt]), {"materials/0": quote_matched("ocr", 2.0, "Sugar 200g")}
    )
    main, review = text.split("## Điểm chưa rõ", 1)
    assert "≈ khớp nguyên văn chữ trên màn hình [00:00:02](#t=2.000): “Sugar 200g”" in main
    assert "tên mục chưa kiểm chứng: Muối" in review
    assert "câu diễn giải" not in review
