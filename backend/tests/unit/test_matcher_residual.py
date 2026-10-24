"""Residual false-verified inputs after the final review (follow-up rulings R1-R5).

Every negative case here used to come back `verified`; each must now be `unverified`. The pipeline always
passes the draft language, so the cases pass `text_language` too."""

import pytest
from app.schemas.verification import Transcript, Word
from app.services.verification.lexicon import foreign_number_word
from app.services.verification.matcher import NO_DIGITS, NO_LANGUAGE, verify_item
from app.services.verification.numbers import number_tokens
from app.services.verification.units import prefix_at
from test_matcher import SETTINGS, exact
from test_matcher_final_review import cl, mat, par, say, show


def ocr_with(item, screen, language):
    """An on-screen item checked while a transcript in `language` exists (OCR reads no number words)."""
    words = [Word(start=10.0, end=10.3, text="hello")]
    t = Transcript(language=language, words=words)
    return verify_item("p", item, t, [(11.0, screen)], SETTINGS, text_language="vi")


# ---- R1: more fraction words ---------------------------------------------------------------------

R1_CASES = [
    lambda: say(
        mat("1", "cup", "one fourth cup of sugar", name="sugar"), "add one fourth cup of sugar", "en", "en"
    ),
    lambda: say(
        mat("3", "cup", "three fourths cup of milk", name="milk"), "add three fourths cup of milk", "en", "en"
    ),
    lambda: say(
        mat("1", "teaspoon", "one eighth teaspoon of salt", name="salt"),
        "add one eighth teaspoon of salt",
        "en",
        "en",
    ),
    lambda: say(
        par("1", "tiếng", "hầm một tiếng rưởi", name="hầm"), "rồi hầm một tiếng rưởi nhé", "vi", "vi"
    ),
    lambda: say(mat("2", "lạng", "hai lạng rưởi thịt", name="thịt"), "mua hai lạng rưởi thịt", "vi", "vi"),
    lambda: say(
        cl("Add 1 cup sugar", "add one fourth cup sugar"), "now add one fourth cup sugar", "en", "en"
    ),
    lambda: say(mat("1", "cup", "add a fifth of a cup", name="cup"), "add a fifth of a cup", "en", "en"),
    lambda: say(
        mat("3", "chén", "ba phần tư chén đường", name="đường"), "cho ba phần tư chén đường", "vi", "vi"
    ),
    lambda: say(mat("1", "chén", "1 phần 3 chén đường", name="đường"), "cho 1 phần 3 chén đường", "vi", "vi"),
    lambda: show(mat("1", "cup", ost="one tenth cup oil", name="oil"), "one tenth cup oil"),
    # the speech goes on with a fraction word the quote left out
    lambda: say(par("1", "tiếng", "hầm một tiếng", name="hầm"), "hầm một tiếng rưởi nhé", "vi", "vi"),
    lambda: show(par("1", "tiếng", ost="Hầm 1 tiếng", name="Hầm"), "Hầm 1 tiếng rưỡi"),
]


@pytest.mark.parametrize("case", R1_CASES)
def test_r1_fraction_words_never_verify(case):
    assert case().status == "unverified"


def test_r1_percent_is_not_a_fraction():
    item = cl("Giảm 10 phần trăm muối", "giảm 10 phần trăm muối")
    assert say(item, "các bạn giảm 10 phần trăm muối nhé", "vi", "vi").status == "verified"
    assert number_tokens("mười phần trăm", "vi") == ["10"]


# ---- R2: languages without number words ----------------------------------------------------------

R2A_CASES = [
    lambda: say(
        par("2", "minutes", "cuire 2 minutes et demie", name="cuire"), "cuire 2 minutes et demie", "fr", "vi"
    ),
    lambda: say(
        mat("2", "tazas", "2 tazas y media de harina", name="harina"), "2 tazas y media de harina", "es", "vi"
    ),
    lambda: say(
        mat("2", "큰술", "설탕 2 큰술 또는 세 큰술", name="Đường"), "설탕 2 큰술 또는 세 큰술", "ko", "vi"
    ),
    lambda: say(mat("2", "큰술", "설탕 2 큰술 반", name="Đường"), "설탕 2 큰술 반", "ko", "vi"),
    lambda: say(cl("Cuire 2 minutes", "cuire 2 ou trois minutes"), "cuire 2 ou trois minutes", "fr", "vi"),
    lambda: say(cl("Cuire deux minutes", "cuire 2 minutes"), "cuire 2 minutes", "fr", "vi"),
    lambda: ocr_with(cl("Cuire 2 minutes", ost="Cuire 2 minutes"), "Cuire 2 minutes et demie", "fr"),
]


@pytest.mark.parametrize("case", R2A_CASES)
def test_r2a_digits_in_a_language_without_number_words_never_verify(case):
    out = case()
    assert (out.status, out.reason) == ("unverified", NO_DIGITS)


R2B_CASES = [
    lambda: show(
        cl("Cuire", ost="Cuire pendant trois minutes"), "Cuire pendant quatre minutes", text_language="vi"
    ),
    lambda: ocr_with(cl("Cuire", ost="Cuire pendant trois minutes"), "Cuire pendant quatre minutes", "en"),
    lambda: ocr_with(cl("Cuire", ost="Cuire pendant trois minutes"), "Cuire pendant quatre minutes", "vi"),
    lambda: show(cl("Hornear", ost="Hornear durante tres minutos"), "Hornear durante cuatro minutos"),
    lambda: show(cl("Backen", ost="Backen Sie drei Minuten lang"), "Backen Sie vier Minuten lang"),
    lambda: ocr_with(cl("Backen", ost="Backen Sie drei Minuten lang"), "Backen Sie vier Minuten lang", "en"),
]


@pytest.mark.parametrize("case", R2B_CASES)
def test_r2b_ocr_text_without_numbers_must_match_token_for_token(case):
    assert case().status == "unverified"


def test_r2_exact_text_still_verifies():
    # ruling P2: without the draft language (or in another language) a claim's match is only quote_matched
    item = cl("Cuire", ost="Cuire pendant trois minutes")
    assert show(item, "Recette\nCuire pendant trois minutes").status == "quote_matched"
    item = cl("Chạm vào chảo nóng", ost="Chạm vào chảo nóng")
    assert show(item, "Cham vao chao nong").status == "quote_matched"
    assert show(item, "Cham vao chao nong", text_language="vi").status == "verified"
    item = cl("Cuire", "faites cuire pendant trois minutes")
    assert say(item, "alors faites cuire pendant trois minutes", "fr", "vi").status == "quote_matched"


def test_r2b_recall_cost_vietnamese_ocr_needs_every_word():
    # accepted by ruling R2b: one misread word on screen no longer verifies a text without numbers
    item = cl("Chạm vào chảo nóng", ost="Không chạm vào chảo nóng")
    assert show(item, "Khong cham vao chao nqng").status == "unverified"


# ---- R3: spoken and written decimals -------------------------------------------------------------

R3_CASES = [
    lambda: say(
        mat("5", "lít", "dùng không phẩy năm lít nước", name="nước"),
        "các bạn dùng không phẩy năm lít nước nhé",
        "vi",
        "vi",
    ),
    lambda: say(
        mat("5", "liters", "use point five liters of water", name="water"),
        "use point five liters of water",
        "en",
        "en",
    ),
    lambda: say(
        cl("Dùng 5 lít nước", "dùng không phẩy năm lít nước"), "dùng không phẩy năm lít nước nhé", "vi", "vi"
    ),
    lambda: say(
        mat("5", "lít", "dùng không chấm năm lít nước", name="nước"),
        "dùng không chấm năm lít nước",
        "vi",
        "vi",
    ),
    lambda: say(
        mat("5", "liters", "use zero point five liters of water", name="water"),
        "use zero point five liters of water",
        "en",
        "en",
    ),
    lambda: say(
        mat("5", "lít", "dùng một phẩy năm lít nước", name="nước"), "dùng một phẩy năm lít nước", "vi", "vi"
    ),
    lambda: say(mat("5", "lít", "dùng nước", name="nước"), "dùng không phẩy năm lít nước", "vi", "vi"),
]


@pytest.mark.parametrize("case", R3_CASES)
def test_r3_spoken_decimals_are_not_whole_numbers(case):
    assert case().status == "unverified"


@pytest.mark.parametrize(
    "text,lang,expected",
    [
        ("không phẩy năm lít", "vi", ["0.5"]),
        ("một phẩy năm", "vi", ["1.5"]),
        ("hai chấm hai lăm", "vi", ["2.25"]),
        ("phẩy không năm", "vi", ["0.05"]),
        ("point five liters", "en", ["0.5"]),
        ("zero point five", "en", ["0.5"]),
        ("three point one four", "en", ["3.14"]),
        ("2 point 5", "en", ["2.5"]),
        ("hai ba phẩy năm", "vi", ["~hai ba phẩy năm"]),
        (".5 ml", None, ["0.5"]),
        (",5 ml", None, ["0.5"]),
        ("1,5 1.5 1,25", None, ["1.5", "1.5", "1.25"]),
        ("1,500 1.500", None, ["1,500", "1.500"]),
        ("1:30 30:1", None, ["1:30", "30:1"]),
    ],
)
def test_r3_decimal_tokens(text, lang, expected):
    assert number_tokens(text, lang) == expected


def test_r3_decimal_written_and_spoken_agree():
    item = mat("0,5", "lít", "dùng không phẩy năm lít nước", name="nước")
    assert say(item, "các bạn dùng không phẩy năm lít nước nhé", "vi", "vi").status == "verified"
    item = mat("0.5", "liters", "use point five liters of water", name="water")
    assert say(item, "now use point five liters of water", "en", "en").status == "verified"


# ---- R4: ratios, symbols before numbers, claim units against the quote ---------------------------

R4_CASES = [
    lambda: say(cl("Để bột nghỉ 30 giờ", "để bột nghỉ 30 phút"), "giờ để bột nghỉ 30 phút nhé", "vi", "vi"),
    lambda: say(
        cl("Add 2 tablespoons salt", "add 2 teaspoons of salt"), "now add 2 teaspoons of salt", "en", "en"
    ),
    lambda: say(cl("Tỉ lệ 1:30", "tỉ lệ 30:1 nhé"), "tỉ lệ 30:1 nhé", "vi", "vi"),
    lambda: say(par("30:1", None, "tỉ lệ 1:30 nhé", name="tỉ lệ"), "tỉ lệ 1:30 nhé", "vi", "vi"),
    lambda: say(
        cl("The kit costs $5 per bag", "the kit costs $5 per bag"),
        "so the kit costs €5 per bag here",
        "en",
        "en",
    ),
    lambda: say(
        cl("The kit costs $5", "the kit costs €5 per bag"), "so the kit costs €5 per bag here", "en", "en"
    ),
    lambda: show(cl("Costs $5 per bag", ost="Costs $5 per bag"), "Costs €5 per bag", text_language="en"),
    lambda: show(cl("Speed x2", ost="Playback speed x2"), "Playback speed ÷2", text_language="en"),
    lambda: say(cl("Nhân x2 công thức", "nhân x2 công thức"), "nhân ÷2 công thức nhé", "vi", "vi"),
    lambda: say(cl("Speed x2", "set the speed to ÷2"), "set the speed to ÷2", "en", "en"),
    lambda: say(cl("Cook 5 minutes", "cook for 5 minutes"), "cook for ~5 minutes", "en", "en"),
    # Vietnamese spoon names are two or three words; the first word alone is not the unit
    lambda: say(cl("Cho 2 muỗng canh muối", "cho 2 muỗng canh muối"), "cho 2 muỗng cà phê muối", "vi", "vi"),
    lambda: say(cl("Nướng 180 độ F", "nướng 180 độ F"), "nướng 180 độ C nhé", "vi", "vi"),
    # different languages: units go through the canonical table
    lambda: say(cl("Nấu 3 phút", "cook for 3 hours"), "now cook for 3 hours", "en", "vi"),
    lambda: say(
        cl("Cook for 2 tablespoons", "cho 2 muỗng cà phê muối"), "cho 2 muỗng cà phê muối", "vi", "en"
    ),
    lambda: say(cl("Nướng 180°C", "bake at 180 °F"), "bake at 180 °F", "en", "vi"),
]


@pytest.mark.parametrize("case", R4_CASES)
def test_r4_claim_units_ratios_and_symbols_must_agree(case):
    assert case().status == "unverified"


def test_r4_recall_cost_unknown_units_across_languages():
    # accepted by ruling R4c: 'quả' and 'eggs' are not in the unit table, so the claim is not checked
    item = cl("Thêm 2 quả trứng", "add 2 eggs to the bowl")
    assert say(item, "now add 2 eggs to the bowl", "en", "vi").status == "unverified"


def test_r4_same_units_and_symbols_verify():
    assert (
        say(cl("Pha tỉ lệ 1:30 nhé", "pha tỉ lệ 1:30 nhé"), "pha tỉ lệ 1:30 nhé", "vi", "vi").status
        == "verified"
    )
    # R4c recall cost: the claim ends on the number while its quote goes on ('1:30' then 'nhé')
    assert say(cl("Tỉ lệ 1:30", "tỉ lệ 1:30 nhé"), "tỉ lệ 1:30 nhé", "vi", "vi").status == "unverified"
    item = cl("The kit costs $5 per bag", "the kit costs $5 per bag")
    assert say(item, "so the kit costs $5 per bag here", "en", "en").status == "verified"
    item = cl("Speed x2", ost="Playback speed x2")
    assert show(item, "Playback speed x2").status == "quote_matched"  # ruling P2: no draft language
    assert ocr_lang(item, "Playback speed x2", "en").status == "quote_matched"  # P2: draft vi, video en
    item = cl("Cho 2 muỗng canh muối", "cho 2 muỗng canh muối")
    assert say(item, "bây giờ cho 2 muỗng canh muối", "vi", "vi").status == "verified"


# ---- R5: claim text is read with Vietnamese and English number words -----------------------------

R5_CASES = [
    lambda: say(
        cl("Cook for three minutes", "cook for four minutes"), "now cook for four minutes ok", "en", "vi"
    ),
    lambda: say(cl("Nấu ba phút", "nấu bốn phút"), "giờ nấu bốn phút nhé", "vi", "en"),
]


@pytest.mark.parametrize("case", R5_CASES)
def test_r5_claim_numbers_are_read_in_both_languages(case):
    assert case().status == "unverified"


# ---- positives that must keep verifying ----------------------------------------------------------


def test_residual_positives_still_verify():
    assert (
        say(
            mat("200", "gram", "cho 200 gram bột", name="bột"), "bây giờ cho 200 gram bột nhé", "vi", "vi"
        ).status
        == "verified"
    )
    assert (
        say(par("180", "độ", "nướng ở 180 độ", name="nướng"), "giờ nướng ở 180 độ nhé", "vi", "vi").status
        == "verified"
    )
    assert (
        say(cl("Nướng ở 180 độ", "nướng ở 180 độ"), "giờ nướng ở 180 độ nhé", "vi", "vi").status == "verified"
    )
    assert (
        say(cl("Rest 30 minutes", "rest 30 minutes"), "now rest 30 minutes", "en", "en").status == "verified"
    )
    assert (
        say(cl("Rest 30 minutes", "rest 30 minutes"), "now rest 30 minutes", "en", None).status
        == "quote_matched"  # ruling P2: no draft language given
    )
    # different languages, units from the table: every guard passes, but by ruling P2 a translated claim
    # is only quote_matched
    assert (
        say(cl("Nấu ba phút", "cook for three minutes"), "now cook for three minutes", "en", "vi").status
        == "quote_matched"
    )
    item = cl("Cook for 3 minutes", "nấu 3 phút")
    assert say(item, "giờ nấu 3 phút nhé", "vi", "en").status == "quote_matched"
    item = cl("Add 2 tablespoons of salt", "cho 2 muỗng canh muối")
    assert say(item, "cho 2 muỗng canh muối", "vi", "en").status == "quote_matched"
    assert (
        say(
            par("1:30", "giờ", "nướng bánh 1:30 giờ", name="nướng bánh"),
            "nướng bánh 1:30 giờ nhé",
            "vi",
            "vi",
        ).status
        == "verified"
    )


# ---- R6: fraction words in the source next to the number, in many languages; more negations ------

R6_CASES = [
    lambda: show(
        cl("Cuire 2 minutes", ost="Cuire 2 minutes"), "Cuire 2 minutes et demie", text_language="vi"
    ),
    lambda: show(cl("Usar 2 tazas", ost="2 tazas"), "2 tazas y media", text_language="vi"),
    lambda: say(mat("2", "큰술", "설탕 2 큰술", name="Đường"), "설탕 2 큰술 반", "ko", "vi"),
    lambda: show(cl("Thêm đường 2 큰술", ost="설탕 2 큰술"), "설탕 2 큰술 반", text_language="vi"),
    lambda: show(cl("Dùng 2 杯", ost="砂糖 2 杯"), "砂糖 2 杯半", text_language="vi"),
    lambda: say(
        mat("2", "cups", "add 2 cups of flour", name="flour"), "add 2 cups of flour and a half", "en", "en"
    ),
    lambda: say(par("1", "tiếng", "hầm 1 tiếng", name="hầm"), "hầm 1 tiếng hoặc hơn chút rưỡi", "vi", "vi"),
    lambda: show(
        cl("Backen 2 Stunden", ost="Backen 2 Stunden"), "Backen 2 Stunden und eine halbe", text_language="vi"
    ),
    lambda: show(cl("Cuocere 2 ore", ost="Cuocere 2 ore"), "Cuocere 2 ore e mezza", text_language="vi"),
    lambda: show(
        cl("Cozinhar 2 horas", ost="Cozinhar 2 horas"), "Cozinhar 2 horas e meia", text_language="vi"
    ),
    # the same words inside the on-screen text itself, when it holds a number
    lambda: show(
        cl("Cuire 2 minutes", ost="Cuire 2 minutes et demie"), "Cuire 2 minutes et demie", text_language="vi"
    ),
]


@pytest.mark.parametrize("case", R6_CASES)
def test_r6_fraction_words_near_the_number_in_the_source_never_verify(case):
    assert case().status == "unverified"


def test_r6_positives_unaffected():
    item = cl("Cuire 2 minutes", ost="Cuire 2 minutes")
    assert show(item, "Cuire 2 minutes", text_language="vi").status == "verified"
    item = mat("2", "cups", "add 2 cups of flour", name="flour")
    assert say(item, "now add 2 cups of flour", "en", "en").status == "verified"
    # a foreign fraction word in a text without numbers is not a fraction
    item = cl("Ouvrir le menu", ost="Ouvrir le menu demi")
    assert show(item, "Ouvrir le menu demi").status == "quote_matched"  # ruling P2: no draft language


R6_NEGATION_CASES = [
    lambda: say(
        cl("Cần rút điện", "cần rút điện trước khi mở máy"), "khỏi cần rút điện trước khi mở máy", "vi", "vi"
    ),
    lambda: say(
        cl("Cần rút điện", "cần rút điện trước khi mở máy"), "chả cần rút điện trước khi mở máy", "vi", "vi"
    ),
    lambda: say(
        cl("Should unplug", "you should unplug it first"), "you shouldnt unplug it first", "en", "en"
    ),
    lambda: say(cl("It is safe", "it is safe to touch now"), "it isnt safe to touch now", "en", "en"),
    lambda: say(cl("They are hot", "they are hot right now"), "they arent hot right now", "en", "en"),
]


@pytest.mark.parametrize("case", R6_NEGATION_CASES)
def test_r6_more_negation_words(case):
    assert case().status == "unverified"


# ---- round 2: R7-R11 -----------------------------------------------------------------------------


def ocr_none(item, screen):
    """No transcript language to read numbers by; since R13 `show` supplies a Vietnamese one."""
    return show(item, screen, text_language="vi")


ROUND2_CASES = [
    # R8: a sign glued to a word makes the number unreadable
    lambda: ocr_none(par("18", "°C", ost="Freezer-18°C", name="Freezer"), "Freezer-18°C"),
    lambda: ocr_none(mat("5", "g", ost="Đường-5g", name="Đường"), "Đường-5g"),
    lambda: ocr_none(cl("Đặt nhiệt độ 5°C", ost="Nhiệt độ-5°C"), "Nhiệt độ-5°C"),
    # R9: 'không chấm' with no number after is a negation
    lambda: say(cl("Chấm muối ớt", "chấm muối ớt"), "món này không chấm muối ớt", "vi", "vi"),
    lambda: say(
        cl("Chấm nước mắm", "chấm nước mắm cho ngon"), "nhớ là không chấm nước mắm cho ngon", "vi", "vi"
    ),
    # R7: on-screen words compare exactly after folding, also when a word folds into a vi number word
    lambda: ocr_none(
        cl("Tapez", ost="Entrez le mot de passe trois fois"), "Entrez le mot de passe quatre fois"
    ),
    lambda: ocr_none(
        cl("Hornear", ost="Ten cuidado, hornea tres minutos"), "Ten cuidado, hornea cuatro minutos"
    ),
    lambda: ocr_none(
        cl("Cuire", ost="Cuire trois minutes à 180 degrés"), "Cuire quatre minutes à 180 degrés"
    ),
    lambda: ocr_none(
        cl("Backen", ost="Backen Sie drei Minuten bei 180 Grad"), "Backen Sie vier Minuten bei 180 Grad"
    ),
    # number words of other languages next to digits in the on-screen text
    lambda: ocr_none(
        mat("2", "tasses", ost="2 ou trois tasses de farine", name="farine"), "2 ou trois tasses de farine"
    ),
    lambda: ocr_with(
        mat("2", "tasses", ost="2 ou trois tasses de farine", name="farine"),
        "2 ou trois tasses de farine",
        "en",
    ),
    lambda: ocr_none(
        mat("2", "tazas", ost="2 o tres tazas de harina", name="harina"), "2 o tres tazas de harina"
    ),
    lambda: ocr_none(
        mat("2", "큰술", ost="설탕 2 큰술 또는 세 큰술", name="설탕"), "설탕 2 큰술 또는 세 큰술"
    ),
    lambda: say(
        par("2", "minutes", "cuire 2 ou trois minutes", name="cuire"), "cuire 2 ou trois minutes", None, "vi"
    ),
    # R10: fraction words without diacritics
    lambda: ocr_none(par("2", "tiếng", ost="Ham 2 tieng ruoi", name="Ham"), "Ham 2 tieng ruoi"),
    lambda: ocr_none(mat("2", "chén", ost="Bot 2 chen nua", name="Bot"), "Bot 2 chen nua"),
    # R11: comparison symbols, claim negation against its quote, more languages' negations
    lambda: ocr_none(cl("Bake 5 min", ost="Bake <5 min"), "Bake <5 min"),
    lambda: ocr_none(cl("Bake 5 min", ost="Bake ≥5 min"), "Bake ≥5 min"),
    lambda: say(
        cl("Chấm nước mắm", "không chấm nước mắm cho ngon"), "nhớ là không chấm nước mắm cho ngon", "vi", "vi"
    ),
    lambda: say(cl("Ajouter le sel", "ajouter le sel"), "ne pas ajouter le sel", "fr", "fr"),
    lambda: say(cl("Salz verwenden", "salz verwenden"), "kein salz verwenden", "de", "de"),
    lambda: say(cl("Aggiungere sale", "aggiungere sale"), "non aggiungere sale", "it", "it"),
    lambda: say(cl("Adicionar sal", "adicionar sal"), "não adicionar sal", "pt", "pt"),
    lambda: say(cl("Añadir sal", "añadir sal"), "nunca añadir sal", "es", "es"),
]


@pytest.mark.parametrize("case", ROUND2_CASES)
def test_round2_inputs_never_verify(case):
    assert case().status == "unverified"


def test_round2_positives():
    item = cl("Nướng ở 180°C", ost="Nướng ở 180°C")
    assert ocr_none(item, "Nưng ở 180°C").status == "verified"  # R7: stacked-diacritic loss tolerated
    assert ocr_none(cl("Cuire 2 minutes", ost="Cuire 2 minutes"), "Cuire 2 minutes").status == "verified"
    item = mat("0,5", "lít", "dùng không phẩy năm lít nước", name="nước")
    assert say(item, "các bạn dùng không phẩy năm lít nước nhé", "vi", "vi").status == "verified"
    assert number_tokens("không chấm nước mắm", "vi") == []
    assert number_tokens("không phẩy năm", "vi") == ["0.5"]
    assert number_tokens("freezer-18°c", None) == ["~-18"]
    item = cl("Không chạm vào chảo nóng", "đừng chạm vào chảo đang nóng")
    # ruling P2a: every guard passes, but the claim rewords its quote, so only the quote matched
    assert say(item, "các bạn đừng chạm vào chảo đang nóng nhé", "vi", "vi").status == "quote_matched"
    assert ocr_none(par("18", "°C", ost="Freezer 18°C", name="Freezer"), "Freezer 18°C").status == "verified"


def test_round2_recall_cost_ocr_words_without_marks_compare_exactly():
    # ruling R7: 'chao' has no diacritic in the on_screen_text, so a misread 'chao' -> 'chau' is not tolerated
    assert (
        ocr_none(cl("Bật bếp", ost="Bat bep cho chao nong"), "Bat bep cho chau nong").status == "unverified"
    )


# ---- round 3: R12 ----------------------------------------------------------------------------------

ROUND3_CASES = [
    # (a) only Vietnamese-specific letters are tolerated, never number words
    lambda: ocr_none(cl("Hornear", ost="Hornea veintitrés minutos"), "Hornea veintiséis minutos"),
    lambda: ocr_with(cl("Hornear", ost="Hornea veintitrés minutos"), "Hornea veintiséis minutos", "en"),
    lambda: ocr_none(cl("Cuocere", ost="Cuocere ottantatré minuti"), "Cuocere novantatré minuti"),
    lambda: ocr_none(cl("Cuocere", ost="Cuocere sessantatré minuti"), "Cuocere settantatré minuti"),
    # (b) every dash is '-'
    lambda: ocr_none(par("18", "°C", ost="Freezer‐18°C", name="Freezer"), "Freezer‐18°C"),
    lambda: ocr_none(par("18", "°C", ost="Freezer‑18°C", name="Freezer"), "Freezer‑18°C"),
    lambda: ocr_none(par("18", "°C", ost="Freezer‒18°C", name="Freezer"), "Freezer‒18°C"),
    lambda: ocr_none(par("18", "°C", ost="Freezer—18°C", name="Freezer"), "Freezer—18°C"),
    lambda: ocr_none(cl("Đặt 18°C", ost="18°C"), "Freezer‐18°C"),
    lambda: ocr_none(cl("Đặt 18°C", ost="18°C"), "Freezer—18°C"),
    lambda: ocr_none(par("18", "°C", ost="Freezer - 18°C", name="Freezer"), "Freezer - 18°C"),
    # (c) the whole symbol run before a number
    lambda: ocr_none(cl("Bake 5 min", ost="Bake <=5 min"), "Bake <=5 min"),
    lambda: ocr_none(cl("Bake 5 min", ost="Bake >=5 min"), "Bake >=5 min"),
    lambda: ocr_none(cl("Bake 5 min", ost="Bake ≈5 min"), "Bake ≈5 min"),
    lambda: ocr_none(cl("Bake 5 min", ost="Bake ≦5 min"), "Bake ≦5 min"),
    lambda: ocr_none(cl("Bake 5 min", ost="Bake ≧5 min"), "Bake ≧5 min"),
    lambda: ocr_none(cl("Bake 5 min", ost="Bake ⩽5 min"), "Bake ⩽5 min"),
    lambda: ocr_none(cl("Bake 5 min", ost="Bake 5 min"), "Bake <=5 min"),
    # (d) number words of other languages next to digits
    lambda: ocr_none(
        mat("2", "tazze", ost="2 o tre tazze di farina", name="farina"), "2 o tre tazze di farina"
    ),
    lambda: ocr_none(mat("2", "tazze", ost="2 tazze, o tre", name="tazze"), "2 tazze, o tre"),
    lambda: ocr_none(
        par("10", "minutes", ost="Cuire 10 à quinze minutes", name="Cuire"), "Cuire 10 à quinze minutes"
    ),
    lambda: ocr_none(
        par("10", "minutos", ost="Hornear 10 o quince minutos", name="Hornear"), "Hornear 10 o quince minutos"
    ),
    lambda: ocr_none(
        par("20", "minutos", ost="Hornear 20 o treinta minutos", name="Hornear"),
        "Hornear 20 o treinta minutos",
    ),
    lambda: ocr_none(
        par("10", "Minuten", ost="Backen 10 bis fünfzehn Minuten", name="Backen"),
        "Backen 10 bis fünfzehn Minuten",
    ),
    lambda: ocr_none(
        par("20", "Minuten", ost="Backen 20 oder dreißig Minuten", name="Backen"),
        "Backen 20 oder dreißig Minuten",
    ),
    lambda: ocr_none(
        par("20", "minutes", ost="Cuire 20 ou trente minutes", name="Cuire"), "Cuire 20 ou trente minutes"
    ),
    lambda: ocr_none(mat("2", "큰술", ost="설탕 2 큰술 또는 세큰술", name="설탕"), "설탕 2 큰술 또는 세큰술"),
    lambda: ocr_none(
        mat("2", "큰술", ost="설탕 2 큰술 또는 두세 큰술", name="설탕"), "설탕 2 큰술 또는 두세 큰술"
    ),
    lambda: ocr_none(mat("2", "tazas", ost="2 tazas", name="tazas"), "2 tazas o veintitrés"),
    # (e)/(f) negations
    lambda: say(cl("Chấm 2 lần", "chấm 2 lần"), "món này không chấm 2 lần", "vi", "vi"),
    lambda: say(cl("Chấm hai lần", "chấm hai lần"), "món này không chấm hai lần", "vi", "vi"),
    lambda: say(
        cl("Không chấm nước mắm", "chưa ướp thì chấm nước mắm"), "chưa ướp thì chấm nước mắm", "vi", "vi"
    ),
    lambda: say(
        cl("Không chấm nước mắm", "không ướp muối, chấm nước mắm"),
        "không ướp muối, chấm nước mắm",
        "vi",
        "vi",
    ),
    lambda: ocr_none(cl("Chấm nước mắm", ost="Không chấm nước mắm"), "Không chấm nước mắm"),
    lambda: say(cl("Dip in fish sauce", "không chấm nước mắm"), "không chấm nước mắm", "vi", "en"),
    lambda: say(cl("Chấm nước mắm", "không chấm nước mắm"), "không chấm nước mắm", "vi", None),
]


@pytest.mark.parametrize("case", ROUND3_CASES)
def test_round3_inputs_never_verify(case):
    assert case().status == "unverified"


def test_round3_positives():
    assert ocr_none(cl("Nướng ở 180°C", ost="Nướng ở 180°C"), "Nưng ở 180°C").status == "verified"
    assert ocr_none(cl("Cuire 2 minutes", ost="Cuire 2 minutes"), "Cuire 2 minutes").status == "verified"
    item = mat("0,5", "lít", "dùng không phẩy năm lít nước", name="nước")
    assert say(item, "các bạn dùng không phẩy năm lít nước nhé", "vi", "vi").status == "verified"
    item = cl("Không chạm vào chảo nóng", "đừng chạm vào chảo đang nóng")
    # ruling P2a: every guard passes, but the claim rewords its quote, so only the quote matched
    assert say(item, "các bạn đừng chạm vào chảo đang nóng nhé", "vi", "vi").status == "quote_matched"
    assert ocr_none(cl("Bake 5 min", ost="Bake 5 min"), "Bake 5 min").status == "verified"
    assert ocr_none(cl("Bột (200 g)", ost="Bột (200 g)"), "Bột (200 g)").status == "verified"
    # ruling P2d: brackets inside the sequence stay, so the unbracketed claim only paraphrases
    assert ocr_none(cl("Bột 200 g", ost="Bột (200 g)"), "Bột (200 g)").status == "quote_matched"
    item = mat("2", "cups", "add 2 cups of milk until smooth", name="milk")
    assert say(item, "now add 2 cups of milk until smooth", "en", "en").status == "verified"
    assert number_tokens("freezer‐18°c", None) == ["~-18"]


def test_round3_recall_cost_khong_before_decimal_word_is_a_negation_for_claims():
    # ruling R12e: 'không phẩy năm' is 0.5 for numbers but still a negation, so the claim lacks one
    item = cl("Dùng 0,5 lít nước", "dùng không phẩy năm lít nước")
    assert say(item, "các bạn dùng không phẩy năm lít nước nhé", "vi", "vi").status == "unverified"


def test_round3_quantity_written_as_digits_meets_spoken_khong_decimal():
    # R12e: for a Material the spoken 'không phẩy năm' is 0.5, not a negation
    item = mat("0,5", "lít", "dùng 0,5 lít nước", name="nước")
    assert say(item, "dùng không phẩy năm lít nước", "vi", "vi").status == "verified"


def test_round3_recall_cost_symbol_before_the_number_must_be_in_the_value():
    # R12c: '+5' in the quote is not the bare value '5'
    assert (
        say(par("5", "mm", "offset +5 mm", name="offset"), "offset +5 mm", "en", "en").status == "unverified"
    )
    assert (
        say(par("+5", "mm", "offset +5 mm", name="offset"), "offset +5 mm", "en", "en").status == "verified"
    )
    assert say(par("5", "mm", "offset 5 mm", name="offset"), "offset 5 mm", "en", "en").status == "verified"


# ---- round 4: R13-R15 ------------------------------------------------------------------------------


def ocr_vi(item, screen):
    """R13: an on-screen number is only checked while a Vietnamese or English transcript exists."""
    return ocr_with(item, screen, "vi")


def ocr_lang(item, screen, language):
    t = (
        None
        if language is False
        else Transcript(language=language, words=[Word(start=10, end=10.3, text="a")])
    )
    return verify_item("p", item, t, [(11.0, screen)], SETTINGS, text_language="vi")


R13_NUMERIC = [
    par("180", "°C", ost="Nướng ở 180°C", name="Nướng"),
    mat("200", "g", ost="Bột 200 g", name="Bột"),
    par("cao", None, ost="Lửa cao", name="Lửa"),  # a parameter value is a value even without digits
    cl("Cuire 2 minutes", ost="Cuire 2 minutes"),
    cl("Nướng hai phút", ost="Nướng hai phút"),
    cl("Nướng phút", ost="Nướng hai phút"),  # a number word in the on-screen text alone
    cl("Hornear", ost="Hornear veinte minutos"),  # a number word of another language
    exact("python3 app.py", on_screen_text="python3 app.py"),
]


@pytest.mark.parametrize("item", R13_NUMERIC)
@pytest.mark.parametrize("language", [False, None, "", "und"])
def test_r13_ocr_numbers_need_a_vietnamese_or_english_transcript(item, language):
    result = ocr_lang(item, item.on_screen_text, language)
    assert result.status == "unverified"
    # R2a keeps its own reason for a named language without number words ('und' with digits)
    assert result.reason == NO_LANGUAGE or (language == "und" and result.reason == NO_DIGITS)


@pytest.mark.parametrize("language", ["fr", "ko", "ja"])
def test_r13_other_transcript_languages_keep_r2a(language):
    item = cl("Cuire 2 minutes", ost="Cuire 2 minutes")
    assert ocr_lang(item, "Cuire 2 minutes", language).reason == NO_DIGITS


def test_r13_vietnamese_or_english_transcript_lets_ocr_numbers_verify():
    for language in ("vi", "en", "vi-VN", "EN"):
        # ruling P2: the draft is vi, so the claim is verified only beside a vi transcript (primary subtag)
        expected = "verified" if language.lower().startswith("vi") else "quote_matched"
        assert ocr_lang(cl("Cuire 2 minutes", ost="Cuire 2 minutes"), "Cuire 2 minutes", language).status == (
            expected
        )
        item = par("180", "°C", ost="Nướng ở 180°C", name="Nướng")
        assert ocr_lang(item, "Nướng ở 180°C", language).status == "verified"
    assert (
        ocr_vi(exact("python3 app.py", on_screen_text="python3 app.py"), "python3 app.py").status
        == "verified"
    )


def test_r13_text_without_numbers_still_verifies_without_a_transcript():
    # ruling P2: without a transcript the screen's language is unknown, so a claim is only quote_matched
    assert ocr_lang(cl("Bấm nút Lưu", ost="Bấm nút Lưu"), "Bấm nút Lưu", False).status == "quote_matched"
    item = exact("git status", on_screen_text="git status")
    assert ocr_lang(item, "git status", False).status == "verified"
    assert ocr_lang(mat(None, None, ost="Muối", name="Muối"), "Muối", False).status == "verified"


def test_r13_spoken_items_are_not_gated():
    assert say(mat("200", "gram", "200 gram bột"), "cho 200 gram bột vào", "vi", "vi").status == "verified"


N2_WORDS = (
    "sechzehn siebzehn einhundert eintausend dezasseis dezassete dezanove doscientos trescientos "
    "quinientos novecientos duecento seicento ottocento novecento duemila tremila duzentos quinhentos "
    "novecentos septante nonante 스무 쉰 예순 일흔 여든 아흔 석 넉 兩 萬 零 〇 廿"
).split()


@pytest.mark.parametrize("word", N2_WORDS)
def test_r13_lexicon_backstop_words(word):
    assert foreign_number_word(word)


def test_r13_lexicon_still_spares_english_words():
    for word in "milk until under unsalted centimeters dozen novel ventilation quarantine percent".split():
        assert not foreign_number_word(word), word


N2_CASES = [
    lambda: par("10", "Minuten", ost="Backen 10 bis sechzehn Minuten", name="Backen"),
    lambda: par("10", "Minuten", ost="Backen 10 bis siebzehn Minuten", name="Backen"),
    lambda: mat("50", "g", ost="Mehl 50 oder einhundert g", name="Mehl"),
    lambda: mat("100", "gramos", ost="Harina 100 o doscientos gramos", name="Harina"),
    lambda: mat("400", "gramos", ost="Harina 400 o quinientos gramos", name="Harina"),
    lambda: mat("100", "grammi", ost="Farina 100 o duecento grammi", name="Farina"),
    lambda: mat("100", "gramas", ost="Farinha 100 ou duzentos gramas", name="Farinha"),
    lambda: par("10", "minutos", ost="Assar 10 a dezasseis minutos", name="Assar"),
    lambda: par("60", "minutes", ost="Cuire 60 ou septante minutes", name="Cuire"),
    lambda: par("80", "minutes", ost="Cuire 80 ou nonante minutes", name="Cuire"),
    lambda: mat("10", "개", ost="계란 10 개 또는 스무 개", name="계란"),
    lambda: mat("40", "개", ost="계란 40 개 또는 쉰 개", name="계란"),
    lambda: mat("2", "잔", ost="물 2 잔 또는 석 잔", name="물"),
    lambda: mat("3", "잔", ost="물 3 잔 또는 넉 잔", name="물"),
    lambda: mat("1", "杯", ost="水 1 杯 或 兩 杯", name="水"),
    lambda: mat("5000", "元", ost="價格 5000 元 或 萬 元", name="價格"),
    lambda: cl("계란 10 개", ost="계란 10 개 또는 스무 개"),
]


@pytest.mark.parametrize("case", N2_CASES)
def test_r13_lexicon_inputs_never_verify(case):
    item = case()
    assert ocr_vi(item, item.on_screen_text).status == "unverified"
    assert ocr_lang(item, item.on_screen_text, False).reason == NO_LANGUAGE


def test_r13_lexicon_short_needles_next_to_foreign_words():
    item = mat("100", "gramos", ost="Harina 100 gramos", name="Harina")
    assert ocr_vi(item, "Harina 100 gramos o doscientos").status == "unverified"
    item = par("10", "Minuten", ost="Backen 10 Minuten", name="Backen")
    assert ocr_vi(item, "Backen 10 Minuten oder sechzehn").status == "unverified"


# R14: the symbol before a number, past spaces and opening brackets/quotes
PREFIXES = [
    ("nhân x 2", "x"),
    ("scale x 2 cups", "x"),
    ("scale × 2 cups", "×"),
    ("temp< 5", "<"),
    ("giá$ 5", "$"),
    ("bake≤ 5", "≤"),
    ("cups+ 5", "+"),
    ("$ 5", "$"),
    ("$  5", "$"),
    ("- 18", "-"),
    ("x5", "x"),
    ("(x5)", "x"),
    ("x (5)", "x"),
    ("≤(5)", "≤"),
    ("<= (5", "<="),
    ("≤ (5)", "≤"),
    ("≤ '5'", "≤"),
    ("≤ [5]", "≤"),
    ("≤ “5”", "≤"),
    ("~ (5)", "~"),
    ("- (5)", "-"),
    ("+ (5)", "+"),
    ("$ (5)", "$"),
    ("≈ «5»", "≈"),
    ("bake ≈5", "≈"),
    ("(5)", ""),
    ("'5'", ""),
    ("bột (200 g)", ""),
    ("max 5", ""),
    ("box 5", ""),
    ("thêm 2 cốc, 5 phút", ""),
    ("đợi... 5 phút", ""),
    ("bước: 5 phút", ""),
    ("5", ""),
]


@pytest.mark.parametrize("text,want", PREFIXES)
def test_r14_prefix_at(text, want):
    at = max(k for k, ch in enumerate(text) if ch.isdigit() and not text[k + 1 : k + 2].isdigit())
    while at and text[at - 1].isdigit():
        at -= 1
    assert prefix_at(text, at) == want


R14_SYMBOLS = ["≤ (5)", "≤ '5'", "≤ [5]", "≤ “5”", "~ (5)", "- (5)", "+ (5)", "$ (5)", "≈ «5»"]
R14_CASES = [
    lambda: ocr_vi(cl("Bake 5 min", ost="Bake≤ 5 min"), "Bake≤ 5 min"),
    lambda: ocr_vi(cl("Price 5", ost="Price$ 5"), "Price$ 5"),
    lambda: ocr_vi(cl("Scale 2 cups", ost="Scale x 2 cups"), "Scale x 2 cups"),
    lambda: ocr_vi(cl("Temp 5", ost="temp< 5"), "temp< 5"),
    lambda: ocr_vi(cl("Thêm 5 cốc", ost="Thêm+ 5 cốc"), "Thêm+ 5 cốc"),
    lambda: ocr_vi(par("2", "cups", ost="Recipe x 2 cups", name="Recipe"), "Recipe x 2 cups"),
    lambda: ocr_vi(cl("Scale 2 cups", ost="Scale 2 cups"), "Scale x 2 cups"),
    lambda: say(cl("Nhân 2 công thức", "nhân x 2 công thức"), "giờ nhân x 2 công thức nhé", "vi", "vi"),
    lambda: say(par("2", "lần", "nhân x 2 lần", name="nhân"), "giờ nhân x 2 lần nhé", "vi", "vi"),
    *[
        lambda s=s: ocr_vi(par("5", "min", ost=f"Bake {s} min", name="Bake"), f"Bake {s} min")
        for s in R14_SYMBOLS
    ],
    *[lambda s=s: ocr_vi(cl("Bake 5 min", ost=f"Bake {s} min"), f"Bake {s} min") for s in R14_SYMBOLS],
    *[
        lambda s=s: say(par("5", "min", f"bake {s} min", name="bake"), f"now bake {s} min ok", "en", "en")
        for s in R14_SYMBOLS
    ],
]


@pytest.mark.parametrize("case", R14_CASES)
def test_r14_symbols_before_a_space_or_bracket_never_verify(case):
    assert case().status == "unverified"


def test_r14_positives():
    assert ocr_vi(cl("Bake 5 min", ost="Bake 5 min"), "Bake 5 min").status == "verified"
    assert ocr_vi(cl("Bake ≤5 min", ost="Bake ≤5 min"), "Bake ≤5 min").status == "verified"
    assert ocr_vi(cl("Bột (200 g)", ost="Bột (200 g)"), "Bột (200 g)").status == "verified"
    # ruling P2d: brackets inside the sequence stay, so the unbracketed claim only paraphrases
    assert ocr_vi(cl("Bột 200 g", ost="Bột (200 g)"), "Bột (200 g)").status == "quote_matched"
    assert ocr_vi(cl("Giá $5", ost="Giá $ 5"), "Giá $ 5").status == "verified"
    item = mat("2", "cốc", "thêm 2 cốc sữa, rồi 5 phút sau khuấy đều", name="sữa")
    assert (
        say(item, "thêm 2 cốc sữa, rồi 5 phút sau khuấy đều", "vi", "vi").status == "unverified"
    )  # 2 numbers
    item = par("5", "phút", "đợi... 5 phút", name="đợi")
    assert say(item, "giờ đợi... 5 phút nhé", "vi", "vi").status == "verified"


# R15: negation pairs compare the next word as written; OCR misreads of 'không'/'đừng'; superscripts
R15_CASES = [
    lambda: say(
        cl("Không chấm nước mắm", "chấm nước mắm, không chạm tay"),
        "các bạn chấm nước mắm, không chạm tay nhé",
        "vi",
        "vi",
    ),
    lambda: say(cl("Không nấu 5 phút", "nấu 5 phút không nâu"), "nấu 5 phút không nâu nhé", "vi", "vi"),
    lambda: say(cl("Không bật lửa to", "bật lửa to không bắt"), "bật lửa to không bắt nhé", "vi", "vi"),
    *[
        lambda n=n: ocr_vi(cl("Chấm nước mắm", ost="Chấm nước mắm"), f"{n} chấm nước mắm")
        for n in ["Kh0ng", "Khônq", "Khóng", "Khồng", "Khong", "KHÔNG", "Dừng", "Đưng"]
    ],
    lambda: ocr_vi(par("102", "m", ost="Diện tích 10² m", name="Diện tích"), "Diện tích 10² m"),
    lambda: ocr_vi(par("100", "m", ost="Diện tích 10² m", name="Diện tích"), "Diện tích 10² m"),
    lambda: ocr_vi(cl("Bake 51 min", ost="Bake 5¹ min"), "Bake 5¹ min"),
    lambda: ocr_vi(cl("Area 102 m", ost="Area 10² m"), "Area 10² m"),
    lambda: ocr_vi(par("12", "mm", ost="Size 1₂ mm", name="Size"), "Size 1₂ mm"),
    lambda: say(par("102", "m", "diện tích 10² m", name="diện tích"), "diện tích 10² m nhé", "vi", "vi"),
]


@pytest.mark.parametrize("case", R15_CASES)
def test_r15_inputs_never_verify(case):
    assert case().status == "unverified"


def test_r15_superscripts_stay_apart_from_digits():
    assert number_tokens("10² m", None) != ["102"]
    assert number_tokens("5¹ min", None) != ["51"]
    assert number_tokens("1₂ mm", None) != ["12"]


def test_r15_positives():
    item = cl("Không chạm vào chảo nóng", "đừng chạm vào chảo đang nóng")
    # ruling P2a: every guard passes, but the claim rewords its quote, so only the quote matched
    assert say(item, "các bạn đừng chạm vào chảo đang nóng nhé", "vi", "vi").status == "quote_matched"
    item = cl("Không chạm vào chảo", "không chạm vào chảo")
    assert say(item, "nhớ là không chạm vào chảo nhé", "vi", "vi").status == "verified"
    item = cl("Không chấm", ost="Không chấm nước mắm")  # P2a: a shorter claim is only quote_matched
    assert ocr_vi(item, "Khong chấm nước mắm").status == "quote_matched"
    item = cl("Không chấm nước mắm", ost="Không chấm nước mắm")
    assert ocr_vi(item, "Khong chấm nước mắm").status == "verified"
    assert ocr_vi(cl("Dùng 2 thìa", ost="Dùng 2 thìa"), "Dùng 2 thìa").status == "verified"
    assert ocr_vi(cl("Đúng 5 phút", ost="Đúng 5 phút"), "Đúng 5 phút").status == "verified"
    assert ocr_vi(cl("Diện tích 10² m", ost="Diện tích 10² m"), "Diện tích 10² m").status == "verified"


def test_round4_positives():
    item = cl("Nướng ở 180°C", ost="Nướng ở 180°C")
    assert ocr_vi(item, "Nưng ở 180°C").status == "verified"
    assert ocr_lang(item, "Nưng ở 180°C", False).reason == NO_LANGUAGE  # R13 recall cost: silent video
    cuire = cl("Cuire 2 minutes", ost="Cuire 2 minutes")
    assert ocr_lang(cuire, "Cuire 2 minutes", False).reason == NO_LANGUAGE
    assert ocr_lang(cuire, "Cuire 2 minutes", "fr").reason == NO_DIGITS
    assert ocr_lang(cuire, "Cuire 2 minutes", "en").status == "quote_matched"  # P2: draft vi, video en
    assert ocr_lang(cuire, "Cuire 2 minutes", "vi").status == "verified"
    item = mat("0,5", "lít", "dùng không phẩy năm lít nước", name="nước")
    assert say(item, "các bạn dùng không phẩy năm lít nước nhé", "vi", "vi").status == "verified"


# round 4 siblings (same classes as N2/R15, found by probe29)
SIBLING_CASES = [
    # foreign spelled numbers with no digit: the neighbour check now sees them on screen
    lambda: ocr_vi(cl("Cuire trois minutes", ost="trois minutes"), "Cuire deux ou trois minutes"),
    lambda: ocr_vi(
        par("trois", "minutes", ost="trois minutes", name="minutes"), "Cuire deux ou trois minutes"
    ),
    lambda: ocr_vi(cl("두 컵", ost="두 컵"), "두 컵 또는 세 컵"),
    lambda: ocr_vi(cl("Usa tres tazas", ost="tres tazas"), "Usa dos o tres tazas"),
    lambda: ocr_vi(cl("drei Tassen", ost="drei Tassen"), "zwei oder drei Tassen"),
    # the Japanese long-vowel mark right before a digit reads as a minus
    lambda: ocr_vi(par("18", "°C", ost="Freezerー18°C", name="Freezer"), "Freezerー18°C"),
    lambda: ocr_vi(par("18", "°C", ost="Freezer ー18°C", name="Freezer"), "Freezer ー18°C"),
    # a misread negation copied into on_screen_text still counts against the claim text
    *[
        lambda n=n: ocr_vi(cl("Chấm nước mắm", ost=f"{n} chấm nước mắm"), f"{n} chấm nước mắm")
        for n in ["Kh0ng", "Khônq", "Khóng", "Khồng", "Dừng"]
    ],
]


@pytest.mark.parametrize("case", SIBLING_CASES)
def test_round4_siblings_never_verify(case):
    assert case().status == "unverified"


@pytest.mark.parametrize("word", "fuenfzehn zwoelf zwo 卅 壹 貳 參 拾".split())
def test_round4_more_lexicon_words(word):
    assert foreign_number_word(word)


def test_round4_sibling_positives():
    assert ocr_vi(mat("2", "杯", ost="ラーメン 2 杯", name="ラーメン"), "ラーメン 2 杯").status == "verified"
    assert ocr_vi(cl("Use three cups", ost="Use three cups"), "Use three cups").status == "verified"
    assert (
        ocr_vi(cl("Cuire trois minutes", ost="Cuire trois minutes"), "Cuire trois minutes").status
        == "verified"
    )


def test_round4_recall_cost_folded_dung_is_not_a_negation():
    # R15: 'Dung' without marks is usually 'dùng' (use), so it does not negate: no guard fails; the claim
    # leaves 'Dung' out, so by ruling P2a only the quote matched
    item = cl("Chấm nước mắm", ost="Dung chấm nước mắm")
    assert ocr_vi(item, "Dung chấm nước mắm").status == "quote_matched"


def test_round4_recall_cost_superscript_units_are_not_plain_digits():
    # R15: 'm²' is 'm^2', so a claim that writes 'm2' no longer meets it
    assert ocr_vi(cl("Lát 10 m2", ost="10 m²"), "10 m²").status == "unverified"


# ---- round 5: R16 ----------------------------------------------------------------------------------
# R16a: misread-negation tolerance reads only the OCR frame text, never the model's claim text or the
# on_screen_text needle, so a real word one edit from 'không'/'đừng' there cannot stand in for one.
R16_NEGATION_CASES = [
    lambda: ocr_vi(cl("Mở nắp đúng 10 phút", ost="Đúng mở nắp 10 phút"), "Đừng mở nắp 10 phút"),
    lambda: ocr_vi(cl("Đúng mở nắp 10 phút", ost="Đúng mở nắp 10 phút"), "Đừng mở nắp 10 phút"),
    lambda: ocr_vi(cl("Đúng 5 phút", ost="Đúng 5 phút"), "Đừng 5 phút"),
    lambda: ocr_vi(par("5", "phút", ost="Đúng 5 phút", name="phút"), "Đừng 5 phút"),
    lambda: ocr_vi(cl("Đứng khuấy 5 phút", ost="Đứng khuấy 5 phút"), "Đừng khuấy 5 phút"),
    lambda: ocr_vi(cl("Dừng khuấy 5 phút", ost="Dừng khuấy 5 phút"), "Đừng khuấy 5 phút"),
    lambda: ocr_vi(cl("Thông gió 5 phút", ost="Thông gió 5 phút"), "Không gió 5 phút"),
    lambda: ocr_vi(cl("Nấu đúng 5 phút", ost="Không nấu 5 phút"), "Không nấu 5 phút"),
    lambda: ocr_vi(cl("Đậy nắp đúng 5 phút", ost="Không đậy nắp 5 phút"), "Không đậy nắp 5 phút"),
    lambda: ocr_vi(cl("Mở nắp, đứng chờ 5 phút", ost="Đừng mở nắp 5 phút"), "Đừng mở nắp 5 phút"),
    lambda: ocr_vi(cl("Đúng lúc thì chấm nước mắm", ost="Không chấm nước mắm"), "Không chấm nước mắm"),
    # siblings: every real word one edit from 'không' / a marked word one edit from 'đừng'
    *[
        lambda w=w: ocr_vi(cl(f"{w} gió 5 phút", ost=f"{w} gió 5 phút"), "Không gió 5 phút")
        for w in ["Hông", "Khống", "Khổng", "Phông", "Nhông", "Chông"]
    ],
    *[
        lambda w=w: ocr_vi(cl(f"Nấu {w} 5 phút", ost="Không nấu 5 phút"), "Không nấu 5 phút")
        for w in ["thông", "hông", "phông", "đựng", "dừng", "đứng"]
    ],
    lambda: ocr_vi(cl("Đựng khuấy 5 phút", ost="Đựng khuấy 5 phút"), "Đừng khuấy 5 phút"),
    lambda: ocr_vi(cl("Đúng giờ tắt bếp", ost="Đúng giờ tắt bếp"), "Đừng giờ tắt bếp"),
]


@pytest.mark.parametrize("case", R16_NEGATION_CASES)
def test_r16_model_text_words_never_stand_in_for_a_negation(case):
    assert case().status == "unverified"


def test_r16_misread_negations_on_the_frame_still_count():
    # the frame's misread 'Khóng' is a negation: it must be in the needle, and then it agrees
    assert ocr_vi(cl("Chấm nước mắm", ost="Chấm nước mắm"), "Khóng chấm nước mắm").status == "unverified"
    item = cl("Không chấm nước mắm", ost="Không chấm nước mắm")
    assert ocr_vi(item, "Khóng chấm nước mắm").status == "verified"
    assert ocr_vi(item, "Khônq chấm nước mắm").status == "verified"
    # a misread copied into on_screen_text but left out of the claim text still counts
    assert ocr_vi(cl("Chấm nước mắm", ost="Kh0ng chấm nước mắm"), "Kh0ng chấm nước mắm").status == (
        "unverified"
    )


def test_r16_positives_words_the_model_wrote_as_shown():
    assert ocr_vi(cl("Đúng 5 phút", ost="Đúng 5 phút"), "Đúng 5 phút").status == "verified"
    assert ocr_vi(par("5", "phút", ost="Đúng 5 phút", name="phút"), "Đúng 5 phút").status == "verified"
    assert ocr_vi(cl("Dừng khuấy 5 phút", ost="Dừng khuấy 5 phút"), "Dừng khuấy 5 phút").status == "verified"
    assert ocr_vi(cl("Thông gió 5 phút", ost="Thông gió 5 phút"), "Thông gió 5 phút").status == "verified"
    item = cl("Đổ vào hộp đựng 2 lít", ost="Hộp đựng 2 lít")
    assert ocr_vi(item, "Hộp đựng 2 lít").status == "quote_matched"  # ruling P2a: the claim adds words
    assert ocr_vi(cl("Hộp đựng 2 lít", ost="Hộp đựng 2 lít"), "Hộp đựng 2 lít").status == "verified"
    assert ocr_vi(cl("Không nấu 5 phút", ost="Không nấu 5 phút"), "Không nấu 5 phút").status == "verified"


def test_r16_recall_cost_frame_word_the_claim_text_leaves_out():
    # 'đúng' on screen may be a misread 'đừng'; a claim text without it cannot rule that out
    assert ocr_vi(cl("Nấu 5 phút", ost="Đúng 5 phút"), "Đúng 5 phút").status == "unverified"


# R16b: the R13 gate needs speech, not only a detected language (Whisper names one for silent audio)
SILENT = [
    lambda: mat("2", "컵", ost="물 2 컵 또는 서너 컵", name="물"),
    lambda: mat("2", "컵", ost="물 2~서너 컵", name="물"),
    lambda: mat("2", "cuillères", ost="Farine 2 ou zéro cuillères", name="Farine"),
    lambda: mat("2", "cucharas", ost="Harina 2 o cero cucharas", name="Harina"),
    lambda: mat("2", "Löffel", ost="Mehl 2 oder null Löffel", name="Mehl"),
    lambda: mat("1", "Löffel", ost="Mehl 1 oder eine Löffel", name="Mehl"),
]


def ocr_silent(item, screen, language):
    t = Transcript(language=language, words=[])
    return verify_item("p", item, t, [(11.0, screen)], SETTINGS, text_language="vi")


@pytest.mark.parametrize("case", SILENT)
def test_r16_silent_audio_with_a_language_does_not_open_the_gate(case):
    item = case()
    result = ocr_silent(item, item.on_screen_text, "en")
    assert (result.status, result.reason) == ("unverified", NO_LANGUAGE)


def test_r16_gate_needs_words_for_every_numeric_item():
    item = par("180", "°C", ost="Nướng ở 180°C", name="Nướng")
    for language in ("vi", "en"):
        assert ocr_silent(item, "Nướng ở 180°C", language).reason == NO_LANGUAGE
        assert ocr_lang(item, "Nướng ở 180°C", language).status == "verified"
    # text without numbers still matches on a silent video; with no words the screen's language is
    # unknown, so by ruling P2 the claim is only quote_matched
    assert ocr_silent(cl("Bấm nút Lưu", ost="Bấm nút Lưu"), "Bấm nút Lưu", "en").status == "quote_matched"
    assert (
        ocr_silent(exact("git status", on_screen_text="git status"), "git status", "en").status == "verified"
    )


# R16c: the symbol-only tokens (and a standalone x) within 3 tokens before each number must agree
R16_SYMBOL_SCREENS = [
    ("Bake ≤ about 5 min", "5", "min", "Bake about 5 min"),
    ("Bake ≤ approx. 5 min", "5", "min", "Bake approx. 5 min"),
    ("Scale x about 2 cups", "2", "cups", "Scale about 2 cups"),
    ("Freezer - about 18 °C", "18", "°C", "Freezer about 18 °C"),
    ("Price $ about 5", "5", None, "Price about 5"),
    # siblings: the symbol glued to a word two tokens back, or to the front of the hedge word
    ("Bake≤ about 5 min", "5", "min", "Bake about 5 min"),
    ("Bake ≤about 5 min", "5", "min", "Bake about 5 min"),
    ("Bake ≤ for about 5 min", "5", "min", "Bake for about 5 min"),
]
R16_SYMBOL_CASES = [
    *[
        lambda s=s, v=v, u=u: ocr_vi(par(v, u, ost=s, name=s.split()[0].rstrip("≤")), s)
        for s, v, u, _ in R16_SYMBOL_SCREENS
    ],
    *[lambda s=s, c=c: ocr_vi(cl(c, ost=s), s) for s, _, _, c in R16_SYMBOL_SCREENS],
    *[lambda s=s, c=c: ocr_vi(cl(c, ost=c), s) for s, _, _, c in R16_SYMBOL_SCREENS],
    *[
        lambda s=s, v=v, u=u: say(
            par(v, u, s.lower(), name=s.split()[0].rstrip("≤").lower()), f"ok {s.lower()} ok", "en", "en"
        )
        for s, v, u, _ in R16_SYMBOL_SCREENS
    ],
]


@pytest.mark.parametrize("case", R16_SYMBOL_CASES)
def test_r16_symbols_a_few_words_before_a_number_never_verify(case):
    assert case().status == "unverified"


def test_r16_symbol_positives():
    for screen in ("Bake ≤ about 5 min", "Price $ about 5", "Scale x about 2 cups", "Bake about 5 min"):
        assert ocr_vi(cl(screen, ost=screen), screen).status == "verified", screen
    assert ocr_vi(cl("Giá $5", ost="Giá $ 5"), "Giá $ 5").status == "verified"
    assert ocr_vi(cl("Bột (200 g)", ost="Bột (200 g)"), "Bột (200 g)").status == "verified"
    # ruling P2d: brackets inside the sequence stay, so the unbracketed claim only paraphrases
    assert ocr_vi(cl("Bột 200 g", ost="Bột (200 g)"), "Bột (200 g)").status == "quote_matched"
    assert ocr_vi(cl("Lưu ý: nướng 5 phút", ost="Lưu ý: nướng 5 phút"), "Lưu ý: nướng 5 phút").status == (
        "verified"
    )
    item = par("5", "phút", ost="Nướng (khoảng) 5 phút", name="Nướng")
    assert ocr_vi(item, "Nướng (khoảng) 5 phút").status == "verified"
