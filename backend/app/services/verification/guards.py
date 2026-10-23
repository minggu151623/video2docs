"""Extra checks the matcher runs before it may say `verified` (final review rulings C1-C4, I1, I2).

Each check only ever turns a match into `unverified`; none of them can make a match succeed."""

import re
import unicodedata
from collections import Counter

from rapidfuzz import fuzz

from app.services.verification import units
from app.services.verification.numbers import NUMBER, number_tokens, number_words, spell_digits, vocabulary

ORDINALS = "fourth fifth sixth seventh eighth ninth tenth".split()
FRACTION_WORDS = {"rưỡi", "rưởi", "nửa", "half", "halves", "third", "thirds", "quarter", "quarters"}
FRACTION_WORDS |= set(ORDINALS) | {w + "s" for w in ORDINALS}  # 'one fourth', 'three eighths'
FRACTION_PAIRS = {("phần", "tư"), ("phần", "ba")}
DECIMAL_WORDS = {"phẩy", "chấm"}
FRACTION_SYMBOLS = "½¼¾⅓⅔⁄"  # NFKC turns '½' into '1⁄2', so the fraction slash counts too
RANGE_WORDS = {"-", "–", "−", "~", "đến", "tới", "hoặc", "hay", "or", "to", "through", "till", "until"}
RANGE_WORDS |= {"den", "toi", "hoac"}  # the same words as OCR reads them without diacritics
RANGE_PAIR_WORDS = {"and", "và", "va", "&"}  # only directly between two numbers: 'between 2 and 3'
RANGE_GAP = 4  # words allowed between two numbers joined by a range word ('2 phút hoặc là 3')
NEGATIONS = {"not", "no", "never", "without", "cannot", "không", "đừng", "chớ", "chưa", "chẳng"}
NOT_FORMS = {"cannot", "dont", "doesnt", "didnt", "cant", "wont"}
STOP_WORDS = {"và", "của", "cho", "các", "những", "với", "loại", "the", "of", "and", "for", "to", "with"}
NAME_SCORE = 80
PROMPT = re.compile(r"^\s*(?:[$#>](?=\s)|PS\s[^>\n]*>)")
PUNCT = ".,;:!?()[]{}\"'"
SPEECH_GAP_SEC = 0.7  # Transcript has no segments: a pause this long between words is a boundary


def has_vocabulary(language: str | None) -> bool:
    """numbers.py can read spelled numbers in this language (vi, en, or unknown = both)."""
    return bool(vocabulary(language))


def non_latin(text: str) -> bool:
    """A letter outside the Latin script: OCR text in a language without number words."""
    return any(c.isalpha() and not unicodedata.name(c, "").startswith("LATIN") for c in text)


def _tokens(text: str) -> list[str]:
    return [w.strip(PUNCT) for w in text.replace("’", "'").split() if w.strip(PUNCT)]


def fraction_or_range(text: str, language: str | None) -> bool:
    """C1: the quote holds a fraction or a range of two numbers, so no single value can be read from it."""
    raw = unicodedata.normalize("NFC", text).casefold()
    if any(s in raw for s in FRACTION_SYMBOLS):
        return True
    norm = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    words = re.findall(r"[^\W\d_]+", norm)
    if FRACTION_WORDS & set(words) or FRACTION_PAIRS & set(zip(words, words[1:])):
        return True
    if _phan_fraction(re.findall(r"\d+|[^\W\d_]+", norm)):
        return True
    spelled = spell_digits(norm, language)[0]
    numbers = list(NUMBER.finditer(spelled))
    for left, right in zip(numbers, numbers[1:]):
        gap = _tokens(spelled[left.end() : right.start()])
        if gap and len(gap) <= RANGE_GAP and RANGE_WORDS & set(gap):  # '2 - 3', '2~3', '2 phút hoặc là 3'
            return True
        if len(gap) == 1 and gap[0] in RANGE_PAIR_WORDS:  # 'between 2 and 3'
            return True
    return False


def _phan_fraction(words: list[str]) -> bool:
    """R1: 'phần' next to a number ('ba phần tư', '1 phần 3'); 'phần trăm' is percent, not a fraction."""
    numbers = number_words() | {"không"}
    for i, word in enumerate(words):
        if word != "phần" or words[i + 1 : i + 2] == ["trăm"]:
            continue
        near = words[max(0, i - 1) : i] + words[i + 1 : i + 2]
        if any(w[:1].isdigit() or w in numbers for w in near):
            return True
    return False


def _number_spans(text: str, number_words: frozenset[str]) -> list[tuple[int, int]]:
    spans = [m.span() for m in NUMBER.finditer(text)]
    if number_words:
        spans += [m.span() for m in re.finditer(r"[^\W_]+", text) if m.group() in number_words]
    return sorted(spans)


def _shape(text: str) -> str:
    shape = number_tokens(text, "und")
    return shape[0] if shape else text  # a number word on folded OCR text stays a word


def units_agree(needle: str, haystack: str, start: int, end: int, number_words=frozenset()) -> bool:
    """C2 + R4b: the symbol before and the unit after each number of the needle are those of the same
    number in the source.

    Numbers pair up in order; the source's unit may lie just past the segment ('30' then 'hours')."""
    ours = _number_spans(needle, number_words)
    theirs = [s for s in _number_spans(haystack, number_words) if start <= s[0] and s[1] <= end]
    return units.numbers_line_up(needle, haystack, ours, theirs, _shape)


def same_words(segment: str, needle: str) -> bool:
    """R2: without number words to compare, the segment must hold exactly the needle's words."""
    return _tokens(segment) == _tokens(needle)


def spelled_agree(needle: str, segment: str, number_words: frozenset[str]) -> bool:
    """C3b: OCR compares number words as words; the folded vi/en number words must be the same multiset."""

    def count(text):
        return Counter(w for w in re.findall(r"[^\W_]+", text) if w in number_words)

    return count(needle) == count(segment)


def _negations(text: str, number_words: frozenset[str]) -> Counter:
    words = _tokens(text)
    out = []
    for i, word in enumerate(words):
        if word == "khong":  # OCR without diacritics; 'khong' has no other reading
            word = "không"
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if word == "không" and (nxt in number_words or nxt[:1].isdigit() or nxt in DECIMAL_WORDS):
            continue  # 'không trăm', 'không phẩy năm': a digit, not a negation
        if word.endswith("n't") or word in NOT_FORMS:
            out.append("not")
        elif word in NEGATIONS:
            out.append(word)
    return Counter(out)


def negations_agree(needle: str, haystack: str, start: int, end: int, number_words: frozenset[str]) -> bool:
    """I1: the same negations in the needle as in the matched segment plus one word on each side."""
    before, after = haystack[:start].split()[-1:], haystack[end:].split()[:1]
    wider = " ".join(before + [haystack[start:end]] + after)
    return _negations(needle, number_words) == _negations(wider, number_words)


def name_in_source(name: str, source: str, fold) -> bool:
    """I2: every content word of the item's name appears (fuzzily) in its own quote or screen text."""
    text = fold(source)
    words = [w for w in re.findall(r"[^\W_]+", fold(name)) if len(w) >= 2 and w not in STOP_WORDS]
    return all(fuzz.partial_ratio(w, text) >= NAME_SCORE for w in words)


def _squash(text: str) -> str:
    return "".join(text.split())


def exact_rows(text: str, ocr_text: str) -> str | None:
    """C4: a command on screen is one or more whole OCR rows, after at most one leading prompt token."""
    want = _squash(text)
    rows = [r for r in ocr_text.split("\n") if r.strip()]
    for i, row in enumerate(rows):
        for head in dict.fromkeys((row, PROMPT.sub("", row, count=1))):
            got, j = _squash(head), i + 1
            while len(got) < len(want) and j < len(rows):
                got, j = got + _squash(rows[j]), j + 1
            if want and got == want:
                return "\n".join([head.strip(), *rows[i + 1 : j]])
    return None


def isolated_in_speech(all_words, first: int, last: int) -> bool:
    """C4: a spoken command has no word right before or after it within the same stretch of speech."""
    before = first > 0 and all_words[first].start - all_words[first - 1].end < SPEECH_GAP_SEC
    after = last + 1 < len(all_words) and all_words[last + 1].start - all_words[last].end < SPEECH_GAP_SEC
    return not before and not after
