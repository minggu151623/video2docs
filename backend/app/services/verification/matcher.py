"""Deterministic matcher: model-quoted text against ASR words and OCR text (spec 3.3). No LLM involved.

Safety rules, every doubt ends as `unverified`:
- numbers match as whole tokens ('1,5', '1/2', '2-3' and '-18' are different from '15', '1 2', '3', '18');
  spelled numbers are read first and ambiguous colloquial ones are not read at all;
- a fuzzy hit is snapped to whole words, must not sit inside a longer number or next to a modifier
  ('rưỡi', 'âm', 'half'), and the quote must be at least two words or six characters;
- quantities, parameter values and their units must appear as whole tokens in the model's own
  quote and in the aligned segment, never merely somewhere in the window;
- exact inputs (code, commands) are never fuzzy: equal after removing whitespace, a whole OCR row (after
  one prompt token) or a stretch of speech with no word right before or after it;
- final-review guards (guards.py): a quote with a range or a fraction never verifies, numbers in the
  value or claim text equal the quote's, each number keeps its unit word, negations agree, a material
  or parameter name is in its own quote, and languages without number words need an exact segment;
- follow-up rulings R1-R5: ordinal fractions, spoken decimals ('không phẩy năm' is 0.5), '1:30' as one
  token, the symbol before a number ($, €, x, ÷...), claim units against their quote (units.py), digits
  in a language without number words never verify, OCR text without numbers must match word for word;
- ruling R13: an on-screen number is only checked while a Vietnamese or English transcript with words
  exists (R16b);
- rulings P2-P2e: a claim whose quote passed every check is `verified` only when its text is in the
  quote's language and says the same words in the same order; otherwise it is `quote_matched`;
- rulings X1-X5: across languages a material/parameter whose values match is `verified` only when its
  name is proven (word for word, or a material through the ingredient dictionary), else `quote_matched`;
  units are the word right after the value's number, as written in one language and through the unit
  table across languages; a range value ('7-10') meets 'A to B' / 'A đến B' with the same two ends; a
  negation in the quote, the spoken clause or the OCR rows never verifies a quantity (X5a); a name only
  proves an item next to the item's own number, with no competing name across it (X6, X7, names.py)."""

import re
import unicodedata
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterator
from functools import lru_cache
from itertools import accumulate
from typing import Any
from rapidfuzz import fuzz
from app.schemas.tutorial_v2 import ExactInput, GroundedClaim, Material, Parameter, TutorialDraftV2
from app.schemas.verification import ItemVerification, Transcript, Word
from app.services.verification import guards, lexicon, names, units
from app.services.verification.numbers import (
    NUMBER,
    is_range,
    join_ranges,
    number_tokens,
    number_words,
    spell_digits,
)

NO_VALUE = "giá trị không có trong nguyên văn"
NO_NAME = "tên mục không có trong nguyên văn"
NEGATED = "nguyên văn có phủ định"
RANGE = "nguyên văn có khoảng giá trị hoặc phân số"
NO_DIGITS = "ngôn ngữ chưa hỗ trợ kiểm chứng số"
NO_LANGUAGE = "chưa xác định ngôn ngữ video để kiểm chứng số"
DIGITS_ONLY = "und"
VI_EN = ("vi", "en")  # ruling R13: the transcript languages whose videos get on-screen numbers checked
SIGNS, SEPARATORS = "-–−+", ".,/:"
MODIFIERS = {"rưỡi", "phẩy", "chấm", "nửa", "âm", "trừ", "half", "point", "minus", "negative", "½", "¼", "¾"}
MODIFIERS |= guards.FRACTION_WORDS | {"ruoi", "phay"}  # 'rưỡi', 'phẩy' as OCR reads them
DASHES = {"-", "–", "−", "~"}
NEIGHBOURHOOD = 8
MIN_QUOTE_CHARS = 6


def normalize(text: str) -> str:
    """NFKC, every dash as '-', casefold and single spaces; diacritics and every script are kept."""
    return " ".join(lexicon.clean(text).casefold().split())


def _word_char(c: str) -> bool:
    return c.isalnum() or unicodedata.category(c).startswith("M")


def _window_words(t: Transcript, start: float, end: float, pad: float) -> list[Word]:
    low, high = start - pad, end + pad
    return [w for w in t.words if w.end >= low and w.start <= high]


def transcript_window(t: Transcript, start: float, end: float, pad: float) -> str:
    return " ".join(w.text for w in _window_words(t, start, end, pad))


def contains_numbers(needle: str, haystack: str, language: str | None) -> bool:
    """Every whole number of the needle is in the haystack, counting multiplicity."""
    return not Counter(number_tokens(needle, language)) - Counter(number_tokens(haystack, language))


def _snap(text: str, start: int, end: int) -> tuple[int, int]:
    """Grow a segment to whole words and trim blanks, so matches begin and end on a word."""
    while 0 < start < len(text) and _word_char(text[start - 1]) and _word_char(text[start]):
        start -= 1
    while 0 < end < len(text) and _word_char(text[end - 1]) and _word_char(text[end]):
        end += 1
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _align(needle: str, haystack: str, threshold: int) -> tuple[int, int] | None:
    if not needle or not haystack:
        return None
    if len(haystack) < len(needle):  # a window shorter than the quote must resemble all of it
        start, end = 0, len(haystack)
    else:
        found = fuzz.partial_ratio_alignment(needle, haystack, score_cutoff=threshold)
        if not found:
            return None
        start, end = _snap(haystack, found.dest_start, found.dest_end)
    return (start, end) if start < end and fuzz.ratio(needle, haystack[start:end]) >= threshold else None


def fuzzy_contains(needle: str, haystack: str, threshold: int) -> str | None:
    found = _align(needle, haystack, threshold)
    return haystack[found[0] : found[1]] if found else None


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+|[½¼¾]", text)


@lru_cache
def _number_words(folded: bool) -> frozenset[str]:
    return frozenset({_fold(w) for w in number_words()} if folded else number_words())


def _has_number(token: str, folded: bool = False) -> bool:
    """A digit or a Vietnamese / English number word, read or not ('2', 'hai', 'Two,')."""
    word = token.strip(".,;:!?()[]\"'").casefold()
    return any(c.isdigit() for c in word) or word in _number_words(folded)


def _spelled_number(token: str, folded: bool) -> bool:
    """`_has_number`, and on OCR text also a number word of another listed language ('trois', '두'),
    so on-screen numbers written as words get the neighbour check too."""
    return _has_number(token, folded) or folded and lexicon.foreign_number_word(token)


def _beside_number(haystack: str, start: int, end: int, folded: bool) -> bool:
    """Another number, or a dash, near the first or last number of the segment: ranges and alternatives.

    Distance is counted in whitespace tokens from that edge number, so words between it and the segment
    edge use up the window: any number or number word (read or not) within NEIGHBOURHOOD tokens of it
    outside the segment, a half/quarter word in any listed language (ruling R6: 'et demie', 'y media',
    '반'), or a bare dash right next to the segment within reach, ends the match
    ('2 - 3 phút', 'nấu 2 hay khoảng tầm 3 phút', 'two, or if you like, three')."""
    tokens = haystack[start:end].split()
    marks = [i for i, w in enumerate(tokens) if _spelled_number(w, folded)]
    if not marks:
        return False

    def near(words: list[str], gap: int) -> bool:  # words nearest the segment first
        reach = words[: max(0, NEIGHBOURHOOD - gap)]
        # R6 'et demie'; R12d a number word of another language ('2 tazas, o tres')
        number = any(
            _has_number(w, folded) or guards.half_word(w, folded) or lexicon.foreign_number_word(w)
            for w in reach
        )
        return number or (bool(reach) and reach[0] in DASHES)

    before, after = haystack[:start].split()[::-1], haystack[end:].split()
    return near(before, marks[0]) or near(after, len(tokens) - 1 - marks[-1])


def _edges_ok(needle: str, haystack: str, start: int, end: int, language: str | None, folded: bool) -> bool:
    """False when the segment is cut out of a longer number or sits next to a modifier."""
    segment = haystack[start:end]
    if segment[:1].isdigit() and start > 0 and haystack[start - 1] in SIGNS + SEPARATORS:
        return False  # '-18', '2-3', '1,5', '1/2' seen from their second half
    if segment[-1:].isdigit() and end < len(haystack):
        after = haystack[end : end + 2]
        if after[0].isdigit() or (after[0] in SIGNS + SEPARATORS and after[1:].isdigit()):
            return False
    spelled = folded and any(_spelled_number(w, folded) for w in needle.split())  # OCR reads no number words
    if not number_tokens(needle, language) and not spelled:
        return True
    if _beside_number(haystack, start, end, folded):
        return False
    ours = needle.split()
    if any(guards.half_word(w, folded) for w in segment.split() if w not in ours):
        return False  # R6: '2 杯半' on screen for '2 杯'
    around = _words(haystack[:start])[-1:] + _words(segment) + _words(haystack[end:])[:1]
    return all(w not in MODIFIERS or w in _words(needle) for w in around)


def _locate(
    needle: str,
    haystack: str,
    threshold: int,
    language: str | None,
    folded: bool = False,
    exact: bool = False,
    plain: tuple[str, str] | None = None,
    written: frozenset[str] = frozenset(),
) -> tuple[int, int, bool] | None:
    """(start, end, numbers_ok) of the best alignment on canonical text, None when the words differ.

    `exact`: the segment holds exactly the needle's words (no number words to compare, rulings C3c, R2).
    `plain`: the same two texts with diacritics, index for index, for the negation check on OCR text.
    `written` (R16a): words the model wrote that a frame word may equal without being read as a misread
    negation."""
    found = _align(needle, haystack, threshold)
    if not found or exact and not guards.same_words(haystack[found[0] : found[1]], needle):
        return None
    start, end = found
    segment = haystack[start:end]
    words = _number_words(folded)
    ok = (
        Counter(number_tokens(needle, language)) == Counter(number_tokens(segment, language))
        and _edges_ok(needle, haystack, start, end, language, folded)
        and guards.units_agree(needle, haystack, start, end, words if folded else frozenset())
        and guards.negations_agree(
            *(plain or (needle, haystack)),
            start,
            end,
            _number_words(False),
            frame=written if folded else None,
        )
        and (not folded or guards.spelled_agree(needle, segment, words))
        and not lexicon.digits_with_foreign_words(segment)  # R12d
    )
    return start, end, ok


def _bounded(value: str, text: str) -> bool:
    """`value` occurs in `text` as a whole token ('g' in '200g' counts, '두' in '모두' does not)."""
    if not value:
        return True
    if NUMBER.fullmatch(value.strip()):  # a bare number: the same whole number token ('0,5' is '0.5')
        return number_tokens(value, DIGITS_ONLY)[0] in number_tokens(text, DIGITS_ONLY)
    at = text.find(value)
    while at >= 0:
        prev, nxt = text[at - 1 : at] if at else "", text[at + len(value) : at + len(value) + 2]
        if value[0].isdigit():
            left = not prev or not (_word_char(prev) or prev in SIGNS + SEPARATORS)
        else:
            left = not prev or not _word_char(prev) or prev.isdigit()  # '200g': the unit follows a digit
        if not nxt:
            right = True
        elif value[-1].isdigit():
            right = not nxt[0].isdigit() and not (nxt[0] in SIGNS + SEPARATORS and nxt[1:].isdigit())
        else:
            right = not _word_char(nxt[0])
        if left and right:
            return True
        at = text.find(value, at + 1)
    return False


def _squash(text: str) -> str:
    return "".join(text.split())


def _exact_span(text: str, source: str) -> tuple[int, int] | None:
    """Span of `source` where `text` occurs ignoring whitespace, between whitespace or string edges."""
    needle = _squash(text)
    keep = [i for i, c in enumerate(source) if not c.isspace()]
    squashed = "".join(source[i] for i in keep)
    at = squashed.find(needle) if needle else -1
    while at >= 0:
        first, last = keep[at], keep[at + len(needle) - 1]
        if (first == 0 or source[first - 1].isspace()) and (
            last == len(source) - 1 or source[last + 1].isspace()
        ):
            return first, last + 1
        at = squashed.find(needle, at + 1)
    return None


def exact_input_matches(text: str, source: str) -> str | None:
    """Code and commands compare as written; only whitespace differences are ignored."""
    found = _exact_span(text, source)
    return source[found[0] : found[1]] if found else None


def _fold(text: str) -> str:
    """Normalized text without Vietnamese marks, one output character per input character."""
    out = []
    for ch in normalize(text).replace("đ", "d"):
        base = "".join(c for c in unicodedata.normalize("NFD", ch) if unicodedata.category(c) != "Mn")
        out.append(base if len(base) == 1 else ch)
    return "".join(out)


def _canonical(text: str, spoken: bool, language: str | None) -> str:
    """Speech keeps diacritics and reads number words; OCR text loses diacritics, digits only."""
    return spell_digits(normalize(text), language)[0] if spoken else _fold(text)


def _match_screen(
    expected: str,
    ocr_text: str,
    threshold: int,
    required: tuple[str, ...] = (),
    exact: bool = False,
    written: str | None = None,
    unit=None,
    ranges: bool = False,
) -> tuple[str, bool] | None:
    """PaddleOCR drops stacked Vietnamese diacritics, so both sides lose them; numbers stay exact.

    Ruling R7: the aligned segment holds the needle's words in order after folding; only a word written
    with a Vietnamese mark may be misread a little. R16a: a frame word that looks like a misread negation
    only reads as written when `written` (the claim text, else the needle) holds that exact word.
    `unit` (X2): checks the unit after the value in the folded frame text; `ranges` (X3): the frame's
    'A to B' reads as 'A-B', as the value's own range does."""
    shown = normalize(ocr_text)
    frame, starts, ends = join_ranges(shown) if ranges else (shown, None, None)
    needle, haystack = _fold(expected), _fold(frame)
    plain = normalize(expected), frame
    seen = lexicon.written_words(expected if written is None else written)
    found = _locate(needle, haystack, threshold, DIGITS_ONLY, True, exact, plain, seen)
    if not found:
        return None
    segment = haystack[found[0] : found[1]]
    if not guards.ocr_words_agree(plain[0], needle, segment, _number_words(True)):
        return None
    ok = found[2] and all(_bounded(_fold(r), segment) for r in required)
    ok = ok and (unit is None or unit(haystack, found[0], found[1], True))
    a, b = (found[0], found[1]) if starts is None else (starts[found[0]], ends[found[1] - 1])
    rows, proof, scope = _rows(ocr_text, shown, a, b)
    return shown[a:b], ok, ("\n".join(proof), "\n".join(scope), " ".join(rows))


def _rows(ocr_text: str, shown: str, start: int, end: int) -> tuple[list[str], list[str], list[str]]:
    """(shown, proof, scope) OCR rows as read, for the match [start, end) of `shown` (the normalized text).

    shown (X1a): every row the match touches, so a reader sees where the number came from ('Sugar 200g'
    for on_screen_text '200g', 'Cook 7 to' + '10 min' for a range over two rows); proof (X6, X7d): those
    rows and one row above and below, where a stack of labels or a modifier on its own row shows
    ('Sugar' / 'Salt' / '200g', 'Coconut' / 'Milk 200ml'); scope (X5a, X7c): two rows above, one below,
    where a negation also counts ('Do not' / 'add' / 'Sugar 200g')."""
    rows = [(r.strip(), normalize(r)) for r in ocr_text.split("\n")]
    rows = [(raw, norm) for raw, norm in rows if norm]
    if " ".join(norm for _, norm in rows) != shown:
        return [shown[start:end]], [ocr_text], [ocr_text]
    touched, at = [], 0
    for k, (_, norm) in enumerate(rows):
        if at < end and start < at + len(norm):
            touched.append(k)
        at += len(norm) + 1
    raw = [r for r, _ in rows]
    shown_rows = [raw[k] for k in touched]
    proof = raw[max(0, touched[0] - 1) : touched[-1] + 2]  # X7d: label stacks, 'Coconut' / 'Milk 200ml'
    scope = raw[max(0, touched[0] - 2) : touched[-1] + 2]  # X7c: two rows above, one below
    return shown_rows, proof, scope


def _speech_base(words: list[Word]) -> tuple[list[Word], str, list[int]]:
    spoken = [(w, normalize(w.text)) for w in words]
    spoken = [(w, t) for w, t in spoken if t]
    texts = [t for _, t in spoken]
    return [w for w, _ in spoken], " ".join(texts), [0, *accumulate(len(t) + 1 for t in texts)][:-1]


def _match_speech(
    quote: str,
    words: list[Word],
    language: str | None,
    threshold: int,
    required=(),
    exact: bool = False,
    quantity: bool = False,
    unit=None,
    ranges: bool = False,
):
    """(matched text, first matched word start, values_ok) or None; diacritics stay significant.

    `quantity` (Material/Parameter): 'không phẩy năm' is only a number, not also a negation (R12e).
    `unit` (X2): checks the unit after the value in the spoken text; `ranges` (X3): 'seven to ten'
    reads as '7-10', as the value's own range does."""
    spoken, base, word_starts = _speech_base(words)
    needle = spell_digits(normalize(quote), language)[0]
    haystack, starts, ends = spell_digits(base, language)
    if ranges:
        needle = join_ranges(needle)[0]
        haystack, inner_starts, inner_ends = join_ranges(haystack)
        starts = [starts[i] for i in inner_starts]
        ends = [ends[i - 1] for i in inner_ends]
    found = _locate(needle, haystack, threshold, language, exact=exact)
    if not found:
        return None
    begin, end = starts[found[0]], ends[found[1] - 1]
    segment = haystack[found[0] : found[1]]
    ok = found[2] and all(_bounded(_canonical(r, True, language), segment) for r in required)
    ok = ok and (unit is None or unit(haystack, found[0], found[1], False))
    # R12e: 'không chấm 2' reads as 0.2, but its 'không' still negates, so compare the words as spoken
    ok = ok and guards.negations_agree(normalize(quote), base, begin, end, _number_words(False), quantity)
    wider = " ".join(base[:begin].split()[-1:] + [base[begin:end]] + base[end:].split()[:1])
    context = (wider, _clause(base, begin, end), base[begin:end])
    return base[begin:end], spoken[bisect_right(word_starts, begin) - 1].start, ok, context


CLAUSE_END = ".!?;"
CLAUSE_WORDS = 6
# X7b: a dot that does not end a clause: a pause ('ever...'), an initial ('A.') or an abbreviation
ABBREVIATIONS = {"approx.", "e.g.", "i.e.", "mr.", "mrs.", "ms.", "dr.", "vs.", "etc.", "st.", "jr.", "sr."}


def _ends_clause(word: str) -> bool:
    """X7b: the word closes a sentence or clause (. ! ? ;), not a pause, an initial or an abbreviation."""
    if word[-1] not in CLAUSE_END or word.endswith(("...", "…")):
        return False
    return not re.fullmatch(r"[^\W\d_]\.", word) and word.casefold() not in ABBREVIATIONS


def _clause(base: str, begin: int, end: int) -> str:
    """X5a: the spoken clause around base[begin:end]: words before and after it up to a sentence or clause
    end (. ! ? ;) or CLAUSE_WORDS words on each side, whichever is nearer."""
    left = []
    for word in reversed(base[:begin].split()[-CLAUSE_WORDS:]):
        if _ends_clause(word):
            break
        left.insert(0, word)
    right = []
    last = (base[:end].split() or [""])[-1] + base[end : end + 1].strip()
    if not (last and _ends_clause(last)):
        for word in base[end:].split()[:CLAUSE_WORDS]:
            right.append(word)
            if _ends_clause(word):
                break
    return " ".join([*left, base[begin:end], *right])


def _match_speech_exact(source: str, words: list[Word], all_words: list[Word]):
    """Exact input said aloud: whole words equal to it as written (case included), with no word right
    before or after it in the same stretch of speech (ruling C4)."""
    want, index, hit = _squash(source), {id(w): k for k, w in enumerate(all_words)}, None
    for i in range(len(words)):
        got, j = "", i
        while j < len(words) and len(got) < len(want):
            got, j = got + _squash(words[j].text), j + 1
        if not want or got != want:
            continue
        alone = guards.isolated_in_speech(all_words, index[id(words[i])], index[id(words[j - 1])])
        said = " ".join(w.text.strip() for w in words[i:j])
        hit = (said, words[i].start, alone, (said, said, said))
        if alone:
            return hit
    return hit


def _value(item) -> str | None:
    return {Material: lambda: item.quantity, Parameter: lambda: item.value}.get(
        type(item), lambda: item.text
    )()


def _required(item) -> tuple[str, ...]:
    """Quantities and parameter values must appear as whole tokens in the source text (units: `_unit_ok`)."""
    value = _value(item) if isinstance(item, (Material, Parameter)) else None
    return (value,) if value and value.strip() else ()


def _unit_ok(item, cross: bool, language: str | None):
    """X2: a check of the item's unit against the source text, or None for an item without one.

    The returned function takes (text, start, end, folded): canonical text (digit-spelled speech, or
    folded OCR text) and the span holding the value. When the value has a number, the unit is the word
    after that number in the span ('5 minutes', '4 tsp', '180°c') and both must map to the same table
    unit; a unit outside the table on either side must be written the same and only in one language
    (`cross` False). A value without a number keeps the old check: the unit as a whole token."""
    unit = (item.unit or "").strip() if isinstance(item, (Material, Parameter)) else ""
    if not unit:
        return None
    shapes = number_tokens(_value(item) or "", None)

    def check(text: str, start: int, end: int, folded: bool) -> bool:
        field = _fold(unit) if folded else _canonical(unit, True, language)
        if not shapes:
            return _bounded(field, text[start:end])
        return units.unit_follows(field, shapes[-1], text, start, end, cross, folded)

    return check


def _code(language: str | None) -> str:
    return (language or "").lower().split("-")[0].split("_")[0]


def _same_language(a: str | None, b: str | None) -> bool:
    return bool(_code(a)) and _code(a) == _code(b)


def _unit_mode(spoken: bool, language: str | None, text_language: str | None) -> str:
    """R4c: how the claim's units meet its quote's: as written (one language), through the unit table
    (two languages), or either way when a language is unknown (OCR text, no draft language)."""
    if not spoken or not _code(language) or not _code(text_language):
        return "any"
    return "same" if _same_language(text_language, language) else "cross"


def _inconsistent(
    item,
    source: str,
    spoken: bool,
    language: str | None,
    text_language: str | None,
    screen_language: str | None = None,
    others=(),
):
    """Spec 3.3 tier 1: the item's own values must be in the verbatim text it was extracted from.

    Returns the reason when they are not, else None. OCR text is read with both vi and en number words.
    `screen_language` (X1, X2): the transcript's language, standing in for the on-screen text's."""
    if guards.fraction_or_range(source, language if spoken else None, folded=not spoken):
        return RANGE
    if isinstance(item, ExactInput):
        return None if _squash(item.text) == _squash(source) else NO_VALUE
    if lexicon.digits_with_foreign_words(source):
        return NO_VALUE  # R12d: a second number spelled in a language we cannot read ('2 ou trois')
    source_language = language if spoken else None
    found = Counter(number_tokens(source, source_language))
    if isinstance(item, (Material, Parameter)):
        claimed = Counter(number_tokens(_value(item) or "", None))  # ruling R5: vi and en number words
        if claimed != found:
            return NO_VALUE
        if not units.value_prefixes_agree(_value(item) or "", source, source_language):
            return NO_VALUE  # R12c: 'Freezer - 18°C' or '<=5' for a bare value
        if lexicon.negation_pairs(source, _number_words(False), True):
            return NEGATED  # X5: 'đừng cho 2 chén đường', "don't cook 7 to 10 minutes"
        mode = _name_mode(spoken, language, text_language, screen_language)
        if mode == "check" and not _name_in_quote(item, source, spoken, language, others):
            return NO_NAME
    else:
        claimed, mode = Counter(number_tokens(item.text, None)), _unit_mode(spoken, language, text_language)
        if claimed and claimed != found:
            return NO_VALUE
        if claimed and not units.claim_units_agree(item.text, source, source_language, mode, not spoken):
            return NO_VALUE
        if not guards.claim_negations_agree(item.text, source, mode, _number_words(False)):
            return NO_VALUE  # R12f: 'Chấm nước mắm' from 'không chấm nước mắm'

    numeric = number_tokens(_value(item) or "", None)
    if not guards.has_vocabulary(source_language) and numeric and not any(t[:1].isdigit() for t in found):
        return NO_VALUE  # ruling C3c: a number the quote can only hold as a word we cannot read
    text = _canonical(source, spoken, language)
    if not all(_bounded(_canonical(r, spoken, language), text) for r in _required(item)):
        return NO_VALUE
    unit = _unit_ok(item, _cross(text_language, language if spoken else screen_language), language)
    if unit is not None and not unit(text, 0, len(text), not spoken):
        return NO_VALUE
    return None


def _cross(text_language: str | None, source_language: str | None) -> bool:
    """X2: the draft and the video are both known and in different languages."""
    return (
        bool(_code(text_language))
        and bool(_code(source_language))
        and not _same_language(text_language, source_language)
    )


def _name_mode(spoken: bool, language, text_language, screen_language) -> str:
    """I2 + X1: 'check' the name against its quote when draft and source share a language; 'cross' when
    they differ (or the source language is unknown): the name is not looked for, and the item can only be
    `verified` through the ingredient dictionary (X1a). On screen the name is also checked when the draft
    language is unknown; spoken items without a draft language keep the old rule ('skip': not checked)."""
    source_language = language if spoken else screen_language
    if _same_language(text_language, source_language):
        return "check"
    if not _code(text_language):
        return "skip" if spoken else "check"
    return "cross"


def _shape(item) -> str | None:
    """X6: the shape of the value's last number ('200', '1/2', '7-10' for a joined range), else None."""
    shapes = number_tokens(_value(item) or "", None)
    return shapes[-1] if shapes else None


def _unit_words(item, spoken: bool) -> list[str]:
    """X6: the item's own unit words may stand between its number and its name ('2 quả trứng')."""
    return [w for w in names.tokens(item.unit or "", not spoken) if w.isalpha()]


def _words_of(item, text: str, spoken: bool, language: str | None) -> list[str]:
    ranges = isinstance(item, (Material, Parameter)) and is_range(_value(item) or "")
    return names.tokens(text, not spoken, language, spoken, ranges)


def _competitors(item, spoken: bool, others=()) -> list[list[str]]:
    """X7d: names that would compete with the item's own on the other side of its number: every
    dictionary ingredient in both languages and the draft's other material names (`others`), as tokens
    (folded on screen); the item's own name and dictionary words are left out."""
    folded = not spoken

    def words(text: str) -> list[str]:
        return [w for w in names.tokens(text, folded) if w.isalpha()]

    own = [words(item.name)] + [words(" ".join(p)) for p in lexicon.ingredient_words(item.name)]
    pool = [n for vi, en in lexicon.INGREDIENTS.items() for n in (vi, *en.split("|"))] + list(others)
    found = [words(n) for n in pool]
    return [p for p in found if p and p not in own]


def _name_in_quote(item, source: str, spoken: bool, language: str | None, others=()) -> bool:
    """I2 + X6: every content word of the name in its own quote (fuzzily, as before), and, when the value
    has a number and the name has words other than numbers and units, in the words right next to that
    number ('Đường 200 g', '200 g đường', 'Nướng ở 180°C'), so 'cho 200 g đường và muối' does not prove
    'Muối'."""
    fold = normalize if spoken else _fold
    shape = _shape(item)
    table = units.UNITS if not spoken else units.WRITTEN
    content = [
        w
        for w in re.findall(r"[^\W\d_]+", fold(item.name))
        if len(w) >= 2 and w not in guards.STOP_WORDS and w not in table
    ]
    if shape is None or not content:
        return guards.name_in_source(item.name, source, fold)
    words = _words_of(item, source, spoken, language)
    rivals = _competitors(item, spoken, others)
    zones = names.zones(words, shape, len(content), not spoken, _unit_words(item, spoken), rivals)
    return any(all(fuzz.partial_ratio(w, fold(zone)) >= guards.NAME_SCORE for w in content) for zone in zones)


def _phrase_in(
    item, phrase: list[str], text: str, spoken: bool, language, neighbours: bool, others=()
) -> bool:
    """X1a + X6 + X7d: `phrase` as whole words of `text`, next to the value's number when it has one, with
    no competing name on the other side of that number."""
    words = _words_of(item, text, spoken, language)
    accept = names.phrase_at(phrase, neighbours, not spoken)
    shape = _shape(item)
    if shape is not None:
        rivals = _competitors(item, spoken, others)
        return names.by_number(
            words, shape, len(phrase), not spoken, accept, _unit_words(item, spoken), rivals
        )
    return any(accept(words, i, i + len(phrase)) for i in range(len(words) - len(phrase) + 1))


def _known_name(item, source: str, context: str, spoken: bool, language: str | None, others=()) -> bool:
    """X1a + X6: across languages the name is only proven when it is written in its quote/on-screen text and
    in the matched source (OCR rows, or the spoken segment with one word on each side), next to the item's
    number: word for word (a Vietnamese caption in an English video), or, for a material, as the
    ingredient dictionary's word with plain words around it."""
    texts = (source, context)
    own = [w for w in names.tokens(item.name, not spoken) if w.isalpha()]
    if own and all(_phrase_in(item, own, t, spoken, language, False, others) for t in texts):
        return True
    if not isinstance(item, Material):
        return False
    for phrase in lexicon.ingredient_words(item.name):
        phrase = [units.fold(w) for w in phrase] if not spoken else phrase
        if all(_phrase_in(item, phrase, t, spoken, language, True, others) for t in texts):
            return True
    return False


def _spells_number(text: str | None) -> bool:
    """A Vietnamese/English number word, or one of another listed language (lexicon), in the text."""
    words = re.findall(r"[^\W_]+", normalize(text or ""))
    return any(w in _number_words(False) for w in words) or any(
        lexicon.foreign_number_word(t) for t in (text or "").split()
    )


def _states_number(item) -> bool:
    """R13: an item whose on-screen check would compare a number: a material quantity or parameter
    value, a claim with a digit or a number word, a command with a digit."""
    if isinstance(item, ExactInput):
        return units.has_digit(item.text, item.on_screen_text)
    if isinstance(item, (Material, Parameter)) and (_value(item) or "").strip():
        return True
    texts = (_value(item), item.on_screen_text)
    return units.has_digit(*texts) or any(_spells_number(t) for t in texts)


SENTENCE_END = ".,;:!?…"  # ruling P2b: trimmed from the end of a word only
PAIRS = {"(": ")", "[": "]", "{": "}", "“": "”", "‘": "’", "«": "»", '"': '"', "'": "'"}
CLOSERS = {close: open_ for open_, close in PAIRS.items()}
NUMBER_SYMBOLS = set("$€£¥₫≤≥<>≈")  # ruling P2e: the only symbols joined to a following number


def _symbol_only(token: str) -> bool:
    return not any(_word_char(c) for c in token)


def _paired(mark: str, text: str) -> bool:
    """True when the quote/bracket `mark` has a partner anywhere in `text` ('"' and "'" pair with
    themselves, so they need a second one)."""
    partner = PAIRS.get(mark) or CLOSERS[mark]
    return text.count(mark) > 1 if partner == mark else partner in text


def _trim(word: str, text: str, first: bool, last: bool) -> str:
    """Rulings P2b-P2d: drop sentence-end marks at the end of a word ('Install.' -> 'install'). A
    quote/bracket without a partner anywhere in the whole `text` is dropped only at the start of the
    first word and at the end of the last word ('“nhấn nút install', 'Bột 200 g)'); everywhere else
    marks stay, so 'main()', 'f(x, y)', '(cd a && make)' and 'grep "a b" f' keep theirs. A quote
    right after a digit is a unit (5" is five inches) and stays."""
    while word:
        if word[-1] in SENTENCE_END:
            word = word[:-1]
        elif last and word[-1] in CLOSERS and not _paired(word[-1], text) and not word[-2:-1].isdigit():
            word = word[:-1]
        elif first and word[0] in PAIRS and not _paired(word[0], text):
            word = word[1:]
        else:
            break
    return word


def _word_sequence(text: str) -> list[str]:
    """Rulings P2b-P2e: normalized words compared as a list. Words keep a leading '-', '.', '/', '%',
    '#', '&', punctuation inside them ('-rf', '.env', '/etc', 'C#', '1,5', 'main()') and diacritics;
    only sentence-end marks at their end and unpaired quotes/brackets at the two edges of the whole
    sequence are trimmed (`_trim`). A token without word characters ('.', '..', '-', '&', '$', '{}',
    '""') always stays. It is joined to the next token only when it is made of currency or comparison
    symbols (NUMBER_SYMBOLS) and that token starts with a digit: 'Giá $ 5' reads 'Giá $5' and '≤ 5'
    reads '≤5', while 'cd / 5', 'ls ~ 1', 'chmod + 7', '- 18°C' keep the symbol apart, 'rm -rf . /tmp'
    is not 'rm -rf ./tmp', 'rm - rf' is not 'rm -rf', 'git add .' is not 'git add' and 'a part' stays
    two words."""
    clean = normalize(text)
    tokens = clean.split()
    words = []
    for i, token in enumerate(tokens):
        word = token if _symbol_only(token) else _trim(token, clean, i == 0, i == len(tokens) - 1)
        if not word:
            continue
        if words and set(words[-1]) <= NUMBER_SYMBOLS and word[0].isdigit():
            words[-1] += word
        else:
            words.append(word)
    return words


def _own_words(item, source: str, source_language: str | None, text_language: str | None) -> bool:
    """Rulings P2, P2a-P2c: a matched quote proves a claim only when the claim says it in the quote's
    own words: the same language and the same words in the same order (only case, whitespace and
    sentence-level marks at word ends may differ; see `_word_sequence`). Anything else is a paraphrase
    (`quote_matched`): a subset, a superset, one changed word or mark.
    Materials, parameters and exact inputs carry their own checked values and are not affected."""
    if not isinstance(item, GroundedClaim):
        return True
    if not _same_language(text_language, source_language):
        return False
    return _word_sequence(item.text) == _word_sequence(source)


def _joined(item, source: str, spoken: bool, language: str | None):
    """X3: the item with its range value as 'A-B' and its quote or on-screen text with every range of two
    plain numbers joined the same way (speech read with its number words first: 'seven to ten')."""
    text = spell_digits(normalize(source), language)[0] if spoken else normalize(source)
    source = join_ranges(text)[0]
    value = join_ranges(spell_digits(normalize(_value(item) or ""), None)[0])[0]
    field = "quantity" if isinstance(item, Material) else "value"
    update = {field: value, "quote" if spoken else "on_screen_text": source}
    return item.model_copy(update=update), source


def _negated(scope: str, source: str, spoken: bool) -> bool:
    """X5a: a negation anywhere in the OCR rows of the match, or in the spoken clause around it ('Do NOT
    add Salt 5g', 'không nên cho 2 chén đường', "don't ever add 2 cups"); OCR frame words may be misread
    negations (R15/R16a), unless the model wrote that word itself."""
    if lexicon.khong_before_digit(scope):
        return True  # 'Không 2 chén đường': for a quantity, 'không' before a digit is 'not', not zero
    if spoken:
        return bool(lexicon.negation_pairs(scope, _number_words(False), True))
    seen = lexicon.written_words(source)
    return bool(lexicon.negation_pairs(scope, _number_words(False), True, True, seen))


def _result(status, method, reason=None, **rest) -> ItemVerification:
    return ItemVerification(status=status, method=method, reason=reason, **rest)


def _frame_hit(item, source: str, sec: float, ocr_text: str, settings, exact: bool, unit=None, ranges=False):
    """(matched text, frame second, values_ok) when this frame's text matches the on-screen text."""
    if isinstance(item, ExactInput):
        found = guards.exact_rows(source, ocr_text)
        return (found, sec, True, (found, found, found)) if found else None
    # R16a: a claim's own text decides which frame words are as the model meant them; on_screen_text
    # may copy a misread 'Kh0ng' that the claim text then leaves out
    written = None if isinstance(item, (Material, Parameter)) else item.text
    threshold = settings.verify_text_threshold
    found = _match_screen(source, ocr_text, threshold, _required(item), exact, written, unit, ranges)
    return (found[0], sec, found[1], found[2]) if found else None


def verify_item(
    path: str,
    item,
    transcript: Transcript | None,
    ocr_texts: list[tuple[float, str]] | None,
    settings,
    *,
    text_language: str | None = None,
    materials: tuple[str, ...] = (),
) -> ItemVerification:
    """Check one grounded item (spec 3.3). `path` is only for the caller's bookkeeping.

    `text_language` is the draft's language: claim text and values are read with its number words, and
    a material or parameter name is checked against its quote when the transcript has the same language."""
    if item.basis in ("inferred", "unclear"):
        return _result("unverified", "none", f"basis {item.basis}")
    spoken, exact = item.basis == "stated", isinstance(item, ExactInput)
    source = item.quote if spoken else item.on_screen_text
    if not (source or "").strip():
        return _result("not_checkable", "none", "chỉ có hành động, không có lời nói hay chữ để đối chiếu")
    language = transcript.language if spoken and transcript else None
    ranges = isinstance(item, (Material, Parameter)) and is_range(_value(item) or "")
    if ranges:  # X3: value, quote and the text they are matched in read 'A to B' as 'A-B'
        item, source = _joined(item, source, spoken, language)
    fields = (_value(item), getattr(item, "text", None), item.quote, item.on_screen_text)
    if transcript is not None and not guards.has_vocabulary(transcript.language) and units.has_digit(*fields):
        return _result("unverified", "none", NO_DIGITS)  # ruling R2a: digits we cannot tie to speech
    # rulings R13 + R16b: no vi/en speech to read the screen by (Whisper names a language for silence too)
    heard = transcript is not None and bool(transcript.words) and _code(transcript.language) in VI_EN
    if not spoken and _states_number(item) and not heard:
        return _result("unverified", "none", NO_LANGUAGE)
    screen_language = transcript.language if transcript else None
    # X7d: the draft's other material names compete with this item's name on the other side of its number
    own = normalize(getattr(item, "name", ""))
    others = tuple(n for n in materials if normalize(n) != own)
    reason = _inconsistent(item, source, spoken, language, text_language, screen_language, others)
    if reason:
        return _result("unverified", "none", reason)
    method = "asr" if spoken else "ocr"
    if spoken and transcript is None:
        return _result("not_checked", method, "không có bản ghi lời nói")
    if not spoken and ocr_texts is None:
        return _result("not_checked", method, "không có kết quả OCR")
    if spoken and not exact and len(source.split()) < 2 and len(normalize(source)) < MIN_QUOTE_CHARS:
        return _result("unverified", method, "nguyên văn quá ngắn")
    # ruling P2: the language the quote was heard or read in; on screen, only known from speech with words
    source_language = language if spoken else transcript.language if transcript and transcript.words else None
    pad = settings.verify_window_seconds
    wanted = ("audio", "both") if spoken else ("visual", "both")
    spans = [s for s in item.evidence_spans if s.source in wanted]
    if not spans:
        return _result("unverified", method, "không có khoảng bằng chứng phù hợp")
    checked = (max(0.0, min(s.start_sec for s in spans) - pad), max(s.end_sec for s in spans) + pad)
    if spoken:  # ruling C3c: no number words for this language, so nothing may be fuzzy
        exact_text = not guards.has_vocabulary(language)
    else:
        unread = transcript is not None and not guards.has_vocabulary(transcript.language)
        exact_text = unread or guards.non_latin(source)
    numbers_differ, frames, translated = False, 0, None
    unit = _unit_ok(item, _cross(text_language, language if spoken else screen_language), language)
    quantity = isinstance(item, (Material, Parameter))
    cross = quantity and _name_mode(spoken, language, text_language, screen_language) == "cross"
    for s in spans:
        if spoken:
            words = _window_words(transcript, s.start_sec, s.end_sec, pad)
            if exact:
                hit = _match_speech_exact(source, words, transcript.words)
            else:
                threshold, required = settings.verify_text_threshold, _required(item)
                hit = _match_speech(
                    source, words, language, threshold, required, exact_text, quantity, unit, ranges
                )
            hits = [hit] if hit else []
        else:
            low, high = max(0.0, s.start_sec - pad), s.end_sec + pad
            in_window = sorted((sec, text) for sec, text in ocr_texts if low <= sec <= high)
            frames += len(in_window)
            hits = [
                h
                for sec, text in in_window
                if (h := _frame_hit(item, source, sec, text, settings, exact_text, unit, ranges))
            ]
        for matched, sec, values_ok, (proof, scope, shown) in hits:
            if values_ok and quantity and _negated(scope, source, spoken):
                return _result("unverified", method, NEGATED, checked_range=checked)
            if values_ok and cross and not _known_name(item, source, proof, spoken, language, others):
                # X1a: the name is the model's translation; show the whole row / segment it came from,
                # unless another frame proves the name through the ingredient dictionary
                translated = translated or (shown, sec)
                continue
            if values_ok:
                status = (
                    "verified"
                    if _own_words(item, source, source_language, text_language)
                    else "quote_matched"
                )
                return _result(status, method, matched_text=matched, matched_sec=sec, checked_range=checked)
            numbers_differ = True
    if translated:
        return _result(
            "quote_matched",
            method,
            matched_text=translated[0],
            matched_sec=translated[1],
            checked_range=checked,
        )
    where = "bản ghi lời nói" if spoken else "chữ OCR"
    if numbers_differ:
        reason = f"con số hoặc giá trị không khớp {where}"
    elif not spoken and not frames:
        reason = "không có khung hình OCR trong khoảng bằng chứng"
    else:
        reason = f"không khớp {where} quanh khoảng bằng chứng"
    return _result("unverified", method, reason, checked_range=checked)


def iter_grounded_items(draft: TutorialDraftV2) -> Iterator[tuple[str, str, Any]]:
    """Every grounded item as (report path, collection name, item); the one definition of the path format."""
    for name in ("prerequisites", "safety", "materials", "troubleshooting"):
        for i, item in enumerate(getattr(draft, name)):
            yield f"{name}/{i}", name, item
    for si, step in enumerate(draft.steps):
        for name in ("parameters", "exact_inputs", "warnings", "tips"):
            for i, item in enumerate(getattr(step, name)):
                yield f"steps/{si}/{name}/{i}", name, item
