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
  in a language without number words never verify, OCR text without numbers must match word for word."""

import re
import unicodedata
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterator
from functools import lru_cache
from itertools import accumulate
from typing import Any
from rapidfuzz import fuzz
from app.schemas.tutorial_v2 import ExactInput, Material, Parameter, TutorialDraftV2
from app.schemas.verification import ItemVerification, Transcript, Word
from app.services.verification import guards, units
from app.services.verification.numbers import NUMBER, number_tokens, number_words, spell_digits

NO_VALUE = "giá trị không có trong nguyên văn"
NO_NAME = "tên mục không có trong nguyên văn"
RANGE = "nguyên văn có khoảng giá trị hoặc phân số"
NO_DIGITS = "ngôn ngữ chưa hỗ trợ kiểm chứng số"
DIGITS_ONLY = "und"
SIGNS, SEPARATORS = "-–−+", ".,/:"
MODIFIERS = {"rưỡi", "phẩy", "chấm", "nửa", "âm", "trừ", "half", "point", "minus", "negative", "½", "¼", "¾"}
MODIFIERS |= guards.FRACTION_WORDS | {"ruoi", "phay"}  # 'rưỡi', 'phẩy' as OCR reads them
DASHES = {"-", "–", "−", "~"}
NEIGHBOURHOOD = 8
MIN_QUOTE_CHARS = 6


def normalize(text: str) -> str:
    """NFKC, casefold and single spaces; diacritics and every script are kept."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


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


def _beside_number(haystack: str, start: int, end: int, folded: bool) -> bool:
    """Another number, or a dash, near the first or last number of the segment: ranges and alternatives.

    Distance is counted in whitespace tokens from that edge number, so words between it and the segment
    edge use up the window: any number or number word (read or not) within NEIGHBOURHOOD tokens of it
    outside the segment, or a bare dash right next to the segment within reach, ends the match
    ('2 - 3 phút', 'nấu 2 hay khoảng tầm 3 phút', 'two, or if you like, three')."""
    tokens = haystack[start:end].split()
    marks = [i for i, w in enumerate(tokens) if _has_number(w, folded)]
    if not marks:
        return False

    def near(words: list[str], gap: int) -> bool:  # words nearest the segment first
        reach = words[: max(0, NEIGHBOURHOOD - gap)]
        return any(_has_number(w, folded) for w in reach) or (bool(reach) and reach[0] in DASHES)

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
    spelled = folded and any(_has_number(w, folded) for w in needle.split())  # OCR reads no number words
    if not number_tokens(needle, language) and not spelled:
        return True
    if _beside_number(haystack, start, end, folded):
        return False
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
) -> tuple[int, int, bool] | None:
    """(start, end, numbers_ok) of the best alignment on canonical text, None when the words differ.

    `exact`: the segment holds exactly the needle's words (no number words to compare, rulings C3c, R2).
    `plain`: the same two texts with diacritics, index for index, for the negation check on OCR text."""
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
        and guards.negations_agree(*(plain or (needle, haystack)), start, end, _number_words(False))
        and (not folded or guards.spelled_agree(needle, segment, words))
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
    expected: str, ocr_text: str, threshold: int, required: tuple[str, ...] = (), exact: bool = False
) -> tuple[str, bool] | None:
    """PaddleOCR drops stacked Vietnamese diacritics, so both sides lose them; numbers stay exact.

    Ruling R2b: text with no digit and no vi/en number word must be the segment word for word."""
    needle, haystack = _fold(expected), _fold(ocr_text)
    exact = exact or not any(_has_number(w, folded=True) for w in needle.split())
    plain = normalize(expected), normalize(ocr_text)
    found = _locate(needle, haystack, threshold, DIGITS_ONLY, folded=True, exact=exact, plain=plain)
    if not found:
        return None
    segment = haystack[found[0] : found[1]]
    ok = found[2] and all(_bounded(_fold(r), segment) for r in required)
    return normalize(ocr_text)[found[0] : found[1]], ok


def _speech_base(words: list[Word]) -> tuple[list[Word], str, list[int]]:
    spoken = [(w, normalize(w.text)) for w in words]
    spoken = [(w, t) for w, t in spoken if t]
    texts = [t for _, t in spoken]
    return [w for w, _ in spoken], " ".join(texts), [0, *accumulate(len(t) + 1 for t in texts)][:-1]


def _match_speech(
    quote: str, words: list[Word], language: str | None, threshold: int, required=(), exact: bool = False
):
    """(matched text, first matched word start, values_ok) or None; diacritics stay significant."""
    spoken, base, word_starts = _speech_base(words)
    needle = spell_digits(normalize(quote), language)[0]
    haystack, starts, ends = spell_digits(base, language)
    found = _locate(needle, haystack, threshold, language, exact=exact)
    if not found:
        return None
    begin, end = starts[found[0]], ends[found[1] - 1]
    segment = haystack[found[0] : found[1]]
    ok = found[2] and all(_bounded(_canonical(r, True, language), segment) for r in required)
    return base[begin:end], spoken[bisect_right(word_starts, begin) - 1].start, ok


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
        hit = (" ".join(w.text.strip() for w in words[i:j]), words[i].start, alone)
        if alone:
            return hit
    return hit


def _value(item) -> str | None:
    return {Material: lambda: item.quantity, Parameter: lambda: item.value}.get(
        type(item), lambda: item.text
    )()


def _required(item) -> tuple[str, ...]:
    """Quantities, parameter values and units must appear as whole tokens in the source text."""
    if isinstance(item, Material):
        values = (item.quantity, item.unit)
    elif isinstance(item, Parameter):
        values = (item.value, item.unit)
    else:
        return ()
    return tuple(v for v in values if v and v.strip())


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


def _inconsistent(item, source: str, spoken: bool, language: str | None, text_language: str | None):
    """Spec 3.3 tier 1: the item's own values must be in the verbatim text it was extracted from.

    Returns the reason when they are not, else None. OCR text is read with both vi and en number words."""
    if guards.fraction_or_range(source, language if spoken else None):
        return RANGE
    if isinstance(item, ExactInput):
        return None if _squash(item.text) == _squash(source) else NO_VALUE
    source_language = language if spoken else None
    found = Counter(number_tokens(source, source_language))
    if isinstance(item, (Material, Parameter)):
        claimed = Counter(number_tokens(_value(item) or "", None))  # ruling R5: vi and en number words
        if claimed != found:
            return NO_VALUE
        check_name = not spoken or _same_language(text_language, language)
        if check_name and not guards.name_in_source(item.name, source, normalize if spoken else _fold):
            return NO_NAME
    else:
        claimed = Counter(number_tokens(item.text, None))
        if claimed and claimed != found:
            return NO_VALUE
        if claimed and not units.claim_units_agree(
            item.text, source, source_language, _unit_mode(spoken, language, text_language)
        ):
            return NO_VALUE
    numeric = number_tokens(_value(item) or "", None)
    if not guards.has_vocabulary(source_language) and numeric and not any(t[:1].isdigit() for t in found):
        return NO_VALUE  # ruling C3c: a number the quote can only hold as a word we cannot read
    text = _canonical(source, spoken, language)
    if not all(_bounded(_canonical(r, spoken, language), text) for r in _required(item)):
        return NO_VALUE
    return None


def _result(status, method, reason=None, **rest) -> ItemVerification:
    return ItemVerification(status=status, method=method, reason=reason, **rest)


def _frame_hit(item, source: str, sec: float, ocr_text: str, settings, exact: bool):
    """(matched text, frame second, values_ok) when this frame's text matches the on-screen text."""
    if isinstance(item, ExactInput):
        found = guards.exact_rows(source, ocr_text)
        return (found, sec, True) if found else None
    found = _match_screen(source, ocr_text, settings.verify_text_threshold, _required(item), exact)
    return (found[0], sec, found[1]) if found else None


def verify_item(
    path: str,
    item,
    transcript: Transcript | None,
    ocr_texts: list[tuple[float, str]] | None,
    settings,
    *,
    text_language: str | None = None,
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
    fields = (_value(item), getattr(item, "text", None), item.quote, item.on_screen_text)
    if transcript is not None and not guards.has_vocabulary(transcript.language) and units.has_digit(*fields):
        return _result("unverified", "none", NO_DIGITS)  # ruling R2a: digits we cannot tie to speech
    reason = _inconsistent(item, source, spoken, language, text_language)
    if reason:
        return _result("unverified", "none", reason)
    method = "asr" if spoken else "ocr"
    if spoken and transcript is None:
        return _result("not_checked", method, "không có bản ghi lời nói")
    if not spoken and ocr_texts is None:
        return _result("not_checked", method, "không có kết quả OCR")
    if spoken and not exact and len(source.split()) < 2 and len(normalize(source)) < MIN_QUOTE_CHARS:
        return _result("unverified", method, "nguyên văn quá ngắn")
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
    numbers_differ, frames = False, 0
    for s in spans:
        if spoken:
            words = _window_words(transcript, s.start_sec, s.end_sec, pad)
            if exact:
                hit = _match_speech_exact(source, words, transcript.words)
            else:
                threshold, required = settings.verify_text_threshold, _required(item)
                hit = _match_speech(source, words, language, threshold, required, exact_text)
            hits = [hit] if hit else []
        else:
            low, high = max(0.0, s.start_sec - pad), s.end_sec + pad
            in_window = sorted((sec, text) for sec, text in ocr_texts if low <= sec <= high)
            frames += len(in_window)
            hits = [
                h
                for sec, text in in_window
                if (h := _frame_hit(item, source, sec, text, settings, exact_text))
            ]
        for matched, sec, values_ok in hits:
            if values_ok:
                return _result(
                    "verified", method, matched_text=matched, matched_sec=sec, checked_range=checked
                )
            numbers_differ = True
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
