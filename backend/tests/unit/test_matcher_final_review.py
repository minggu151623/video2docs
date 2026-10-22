"""Regression tests for the final whole-branch review: inputs that used to verify a wrong value."""

import pytest
from app.schemas.tutorial_v2 import GroundedClaim, Material, Parameter
from app.schemas.verification import Transcript, Word
from app.services.verification.matcher import NO_VALUE, verify_item
from app.services.verification.numbers import number_tokens
from app.services.verification.ocr import reading_order
from test_matcher import SETTINGS, exact, span, stated_exact, transcript


def mat(quantity, unit, quote=None, ost=None, name="Bột"):
    basis = "stated" if quote else "observed"
    spans = [span(source="both")]
    return Material(
        name=name,
        quantity=quantity,
        unit=unit,
        note=None,
        evidence_spans=spans,
        basis=basis,
        quote=quote,
        on_screen_text=ost,
    )


def par(value, unit, quote=None, ost=None, name="Thời gian"):
    basis = "stated" if quote else "observed"
    return Parameter(
        name=name,
        value=value,
        unit=unit,
        evidence_spans=[span(source="both")],
        basis=basis,
        quote=quote,
        on_screen_text=ost,
    )


def cl(text, quote=None, ost=None):
    basis = "stated" if quote else "observed"
    return GroundedClaim(
        text=text, evidence_spans=[span(source="both")], basis=basis, quote=quote, on_screen_text=ost
    )


def say(item, spoken, lang="vi", text_language=None):
    return verify_item(
        "p", item, transcript(spoken, language=lang), None, SETTINGS, text_language=text_language
    )


def show(item, *screens, text_language=None):
    frames = [(11.0, s) for s in screens]
    return verify_item("p", item, None, frames, SETTINGS, text_language=text_language)


# ---- C1: ranges, fractions and second numbers inside the quote -----------------------------------

C1_CASES = [
    lambda: say(par("3", "phút", "nấu 2 hoặc 3 phút"), "bây giờ nấu 2 hoặc 3 phút nhé"),
    lambda: say(par("3", "phút", "nấu 2 - 3 phút"), "bây giờ nấu 2 - 3 phút nhé"),
    lambda: say(par("1", "tiếng", "hầm một tiếng rưỡi"), "rồi hầm một tiếng rưỡi cho mềm"),
    lambda: say(
        mat("2", "cups", "two and a half cups of flour"), "add two and a half cups of flour now", "en"
    ),
    lambda: say(par("2", "minutes", "between 2 and 3 minutes"), "cook it between 2 and 3 minutes ok", "en"),
    lambda: say(par("1000000", "", "half a million views"), "we got half a million views", "en"),
    lambda: say(mat("1", "cup", "1 and 1/3 cup sugar"), "use 1 and 1/3 cup sugar", "en"),
    lambda: say(mat("1", "cup", "one and a third cup sugar"), "use one and a third cup sugar", "en"),
    lambda: say(
        mat("1", "cup", "one cup and a quarter of sugar"), "use one cup and a quarter of sugar", "en"
    ),
    lambda: say(
        mat("2", "cups", "2 cups plus 2 tablespoons flour"), "use 2 cups plus 2 tablespoons flour", "en"
    ),
    lambda: show(mat("1", "cup", ost="1 1/2 cup sugar", name="sugar"), "1 1/2 cup sugar"),
    lambda: show(par("3", "phút", ost="Nấu 2 đến 3 phút", name="Nấu"), "Nấu 2 đến 3 phút"),
    lambda: say(
        mat("200", "gram", "200 gram bột và 2000 gram nước", name="Nước"),
        "cho 200 gram bột và 2000 gram nước vào",
    ),
    lambda: say(mat("1", "cup", "½ cup of milk"), "add ½ cup of milk", "en"),
    lambda: say(par("3", "phút", "nấu ba phút hoặc là bốn phút"), "nấu ba phút hoặc là bốn phút", "vi"),
    lambda: say(cl("Nấu 2 hoặc 3 phút", "nấu 2 hoặc 3 phút"), "bây giờ nấu 2 hoặc 3 phút nhé"),
    lambda: say(cl("Nấu 3 phút", "nấu 3 phút rồi thêm 5 phút nữa"), "nấu 3 phút rồi thêm 5 phút nữa nhé"),
]


@pytest.mark.parametrize("case", C1_CASES)
def test_c1_quotes_with_ranges_fractions_or_extra_numbers_never_verify(case):
    assert case().status == "unverified"


def test_c1_recall_cost_two_numbers_in_one_quote():
    # accepted by ruling C1: the quote holds 3 and 12, the value only 3, so it is unverified
    out = say(par("3", "hiệp", "làm 3 hiệp mỗi hiệp 12 lần"), "các bạn làm 3 hiệp mỗi hiệp 12 lần")
    assert (out.status, out.reason) == ("unverified", NO_VALUE)


def test_c1_equal_numbers_still_verify():
    assert say(par("3", "phút", "nấu 3 phút nhé"), "bây giờ nấu 3 phút nhé").status == "verified"
    assert say(cl("Nấu 3 phút", "nấu 3 phút nhé"), "bây giờ nấu 3 phút nhé").status == "verified"
    assert say(par("2-3", "phút", "nấu khoảng 2-3 phút"), "nấu khoảng 2-3 phút nhé").status == "verified"


# ---- C2: the word after each number must be the same --------------------------------------------

C2_CASES = [
    lambda: say(
        cl("Add 2 tablespoons of salt", "add 2 tablespoons of salt"),
        "now add 2 teaspoons of salt to it",
        "en",
    ),
    lambda: say(
        cl("Rest dough 30 minutes", "let the dough rest for 30 minutes"),
        "let the dough rest for 30 hours",
        "en",
    ),
    lambda: say(
        cl("Để ngoài tối đa 2 giờ", "đừng để thức ăn ngoài quá 2 giờ"),
        "nhớ là đừng để thức ăn ngoài quá 2 ngày nhé",
    ),
    lambda: show(cl("Add 2 tbsp salt", ost="Add 2 tbsp salt"), "Add 2 tsp salt"),
    lambda: say(par("2", None, "add 2 tablespoons of salt"), "now add 2 teaspoons of salt to it", "en"),
    lambda: say(
        mat("2", None, "add 2 tablespoons of salt", name="salt"), "now add 2 teaspoons of salt to it", "en"
    ),
]


@pytest.mark.parametrize("case", C2_CASES)
def test_c2_unit_word_after_a_number_must_match(case):
    assert case().status == "unverified"


def test_c2_same_unit_word_verifies():
    item = cl("Add 2 tablespoons of salt", "add 2 tablespoons of salt")
    assert say(item, "now add 2 tablespoons of salt to it", "en").status == "verified"
    assert show(cl("Add 2 tbsp salt", ost="Add 2 tbsp salt"), "Add 2 tbsp salt").status == "verified"
    assert show(par("200", "g", ost="Bột 200 g", name="Bột"), "Nguyên liệu: Bột 200 g").status == "verified"


# ---- C3: claim text language, spelled numbers on screen, languages without number words ----------


def test_c3a_claim_text_is_read_in_the_draft_language():
    item = cl("Nấu trong năm phút", "cook for three minutes")
    assert say(item, "now cook for three minutes and stir", "en", "vi").status == "unverified"
    item = cl("Nấu ba phút", "faites cuire pendant trois minutes")
    assert say(item, "faites cuire pendant quatre minutes", "fr", "vi").status == "unverified"
    item = cl("Nấu trong ba phút", "cook for three minutes")
    assert say(item, "now cook for three minutes and stir", "en", "vi").status == "verified"


@pytest.mark.parametrize(
    "text,ost,screen",
    [
        ("Nấu ba phút rồi tắt bếp", "Nấu ba phút rồi tắt bếp đi nhé", "Nấu bốn phút rồi tắt bếp đi nhé"),
        (
            "Cook three minutes",
            "Cook for three minutes then stir well",
            "Cook for four minutes then stir well",
        ),
    ],
)
def test_c3b_spelled_numbers_on_screen_must_match(text, ost, screen):
    assert show(cl(text, ost=ost), screen).status == "unverified"
    assert show(cl(text, ost=ost), ost).status == "verified"


C3C_CASES = [
    lambda: say(cl("Thêm đường", "설탕 두 큰술 넣어요"), "이제 설탕 세 큰술 넣어요", "ko"),
    lambda: say(cl("Thêm đường", "砂糖を大さじ二杯入れます"), "砂糖を大さじ三杯入れます", "ja"),
    lambda: say(
        cl("Cuire", "faites cuire pendant trois minutes"), "faites cuire pendant quatre minutes", "fr"
    ),
    lambda: say(cl("Thêm 2 thìa đường", "설탕 두 큰술 넣어요"), "설탕 두 큰술 넣어요", "ko", "vi"),
    lambda: say(cl("Thêm hai thìa đường", "설탕 두 큰술 넣어요"), "이제 설탕 세 큰술 넣어요", "ko", "vi"),
    lambda: show(cl("Thêm đường", ost="설탕 두 큰술 넣어요"), "설탕 세 큰술 넣어요"),
]


@pytest.mark.parametrize("case", C3C_CASES)
def test_c3c_languages_without_number_words_need_an_exact_segment(case):
    assert case().status == "unverified"


def test_c3c_exact_segment_still_verifies():
    assert say(cl("Thêm đường", "설탕 두 큰술 넣어요"), "이제 설탕 두 큰술 넣어요", "ko").status == "verified"
    item = cl("Cuire", "faites cuire pendant trois minutes")
    assert say(item, "alors faites cuire pendant trois minutes", "fr").status == "verified"


# ---- C4: commands must be a whole OCR row or an isolated stretch of speech -----------------------


@pytest.mark.parametrize(
    "text,screen",
    [
        ("npm install", "npm install foo --force"),
        ("apt install x", "$ sudo apt install x"),
        ("rm -rf /", "rm -rf / tmp/build"),
    ],
)
def test_c4_command_must_be_a_whole_ocr_row(text, screen):
    assert show(exact(text=text, on_screen_text=text), screen).status == "unverified"


def test_c4_boxes_on_one_row_form_one_line():
    rows = reading_order(["$ npm run build", "--prod"], [(0, 0, 150, 20), (160, 2, 220, 21)])
    assert rows == ["$ npm run build --prod"]
    item = exact(text="npm run build", on_screen_text="npm run build")
    assert show(item, "\n".join(rows)).status == "unverified"


@pytest.mark.parametrize(
    "screen", ["$ npm run build", "# npm run build", "> npm run build", "PS C:\\Users\\me> npm run build"]
)
def test_c4_one_prompt_token_is_ignored(screen):
    item = exact(text="npm run build", on_screen_text="npm run build")
    out = show(item, "Terminal\n" + screen + "\nok")
    assert out.status == "verified"


def test_c4_spoken_command_with_more_words_around_it_is_unverified():
    out = say(stated_exact("git push origin main"), "git push origin main --force", "en")
    assert out.status == "unverified"


def paused(*chunks, at=10.0):
    """Words 0.3 s long, 0.1 s apart inside a chunk and 1 s apart between chunks."""
    words, t = [], at
    for chunk in chunks:
        for w in chunk.split():
            words.append(Word(start=t, end=t + 0.3, text=w))
            t += 0.4
        t += 0.9
    return Transcript(language="en", words=words)


def test_c4_spoken_command_between_pauses_verifies():
    item = stated_exact("git push origin main")
    ok = verify_item("p", item, paused("now type", "git push origin main", "and wait"), None, SETTINGS)
    assert ok.status == "verified"
    bad = verify_item("p", item, paused("now type", "git push origin main --force"), None, SETTINGS)
    assert bad.status == "unverified"


# ---- I1: negation must agree ---------------------------------------------------------------------

I1_CASES = [
    lambda: say(
        cl("You do not need to unplug", "you don't need to unplug it before opening"),
        "you do need to unplug it before opening",
        "en",
    ),
    lambda: say(
        cl("Unplug before opening", "you need to unplug it before opening the case"),
        "you don't need to unplug it before opening the case",
        "en",
    ),
    lambda: say(
        cl("Rút điện trước khi tháo", "nhớ rút điện trước khi tháo máy"),
        "không cần rút điện trước khi tháo máy",
    ),
]


@pytest.mark.parametrize("case", I1_CASES)
def test_i1_negation_flips_never_verify(case):
    assert case().status == "unverified"


def test_i1_khong_is_negation_unless_a_number_word_follows():
    item = cl("Không chạm vào chảo nóng", "đừng chạm vào chảo đang nóng")
    assert say(item, "các bạn đừng chạm vào chảo đang nóng nhé", text_language="vi").status == "verified"
    assert number_tokens("không chạm vào chảo", "vi") == []
    assert number_tokens("một nghìn không trăm hai mươi", "vi") == ["1020"]
    item = cl("You do not need to unplug", "you don't need to unplug it before opening")
    assert say(item, "you don't need to unplug it before opening", "en").status == "verified"


# ---- I2: the item's name must be in its own quote ------------------------------------------------


def test_i2_material_name_must_be_in_the_quote_when_languages_agree():
    wrong = mat("200", "gram", "cho 200 gram đường vào", name="Muối")
    assert say(wrong, "bây giờ cho 200 gram đường vào tô", text_language="vi").status == "unverified"
    right = mat("200", "gram", "cho 200 gram đường vào", name="Đường")
    assert say(right, "bây giờ cho 200 gram đường vào tô", text_language="vi").status == "verified"
    translated = mat("200", "gram", "cho 200 gram đường vào", name="Sugar")
    assert say(translated, "bây giờ cho 200 gram đường vào tô", text_language="en").status == "verified"


def test_i2_ocr_always_checks_the_name():
    assert show(mat("200", "g", ost="Đường 200 g", name="Muối"), "Đường 200 g").status == "unverified"
    assert show(mat("200", "g", ost="Đường 200 g", name="Đường"), "Đường 200 g").status == "verified"


def test_c3b_spelled_numbers_on_screen_also_get_the_neighbour_check():
    # probe7: a spelled range on screen used to verify its second endpoint
    item = cl("Nấu ba phút cho chín", ost="Nấu ba phút cho chín")
    assert show(item, "Nấu hai đến ba phút cho chín").status == "unverified"
    assert show(item, "Nấu ba phút cho chín").status == "verified"
