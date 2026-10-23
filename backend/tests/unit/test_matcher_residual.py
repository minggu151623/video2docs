"""Residual false-verified inputs after the final review (follow-up rulings R1-R5).

Every negative case here used to come back `verified`; each must now be `unverified`. The pipeline always
passes the draft language, so the cases pass `text_language` too."""

import pytest
from app.schemas.verification import Transcript, Word
from app.services.verification.matcher import NO_DIGITS, verify_item
from app.services.verification.numbers import number_tokens
from test_matcher import SETTINGS
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
    item = cl("Cuire", ost="Cuire pendant trois minutes")
    assert show(item, "Recette\nCuire pendant trois minutes").status == "verified"
    assert show(cl("Chạm vào chảo nóng", ost="Chạm vào chảo nóng"), "Cham vao chao nong").status == "verified"
    item = cl("Cuire", "faites cuire pendant trois minutes")
    assert say(item, "alors faites cuire pendant trois minutes", "fr", "vi").status == "verified"


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
    assert show(cl("Speed x2", ost="Playback speed x2"), "Playback speed x2").status == "verified"
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
        say(cl("Rest 30 minutes", "rest 30 minutes"), "now rest 30 minutes", "en", None).status == "verified"
    )
    # different languages, units from the table
    assert (
        say(cl("Nấu ba phút", "cook for three minutes"), "now cook for three minutes", "en", "vi").status
        == "verified"
    )
    assert say(cl("Cook for 3 minutes", "nấu 3 phút"), "giờ nấu 3 phút nhé", "vi", "en").status == "verified"
    item = cl("Add 2 tablespoons of salt", "cho 2 muỗng canh muối")
    assert say(item, "cho 2 muỗng canh muối", "vi", "en").status == "verified"
    assert (
        say(
            par("1:30", "giờ", "nướng bánh 1:30 giờ", name="nướng bánh"),
            "nướng bánh 1:30 giờ nhé",
            "vi",
            "vi",
        ).status
        == "verified"
    )
