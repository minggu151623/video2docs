"""What sits around a number: the symbol before it and the unit after it (rulings C2, R4b, R4c).

Each check only ever turns a match into `unverified`; none of them can make a match succeed."""

import re
import unicodedata

from app.services.verification.lexicon import clean
from app.services.verification.numbers import NUMBER, number_shape, spell_digits

PUNCT = ".,;:!?()[]{}\"'"
OPENERS = "([{\"'“‘«‹「"  # brackets and quotes before a number do not change it ('(200 g)')
SENTENCE = ".,;:!?)]}\"'”’»›」…"  # a token ending in these ends a sentence or clause, not a symbol
POSTFIX = "%°‰′″"  # unit marks written after a number ('10% 5')
BRACKETS = OPENERS + ")]}”’»›」"
LOOKBACK = 3  # R16c: tokens before a number whose symbols must agree ('Bake ≤ about 5')
# canonical unit -> spellings, '|' between spellings. Only unambiguous ones: 'cân' (also 'scale'),
# 'lạng' (100 g), 'phân' (cm or manure), 'ly' and 'in' are left out, so they compare only as written.
_TABLE = {
    "sec": "giây|second|seconds|sec|secs|s",
    "min": "phút|minute|minutes|min|mins",
    "hour": "giờ|tiếng|hour|hours|hr|hrs|h",
    "day": "ngày|day|days",
    "week": "tuần|week|weeks",
    "g": "g|gram|grams|gam|gr",
    "kg": "kg|kilogram|kilograms|kilo|kilos|ký|kí",
    "ml": "ml|milliliter|milliliters|millilitre|millilitres|mililít",
    "l": "l|lít|liter|liters|litre|litres",
    "tbsp": "muỗng canh|thìa canh|tablespoon|tablespoons|tbsp|tbs",
    "tsp": "muỗng cà phê|thìa cà phê|teaspoon|teaspoons|tsp",
    "cup": "chén|cốc|cup|cups",
    "deg": "độ|degree|degrees|°",
    "degC": "°c|độ c|degree c|degrees c|degree celsius|degrees celsius|celsius",
    "degF": "°f|độ f|degree f|degrees f|degree fahrenheit|degrees fahrenheit|fahrenheit",
    "mm": "mm|millimeter|millimeters|millimetre|millimetres",
    "cm": "cm|centimeter|centimeters|centimetre|centimetres",
    "m": "m|mét|meter|meters|metre|metres",
    "inch": "inch|inches",
    "pct": "%|phần trăm|percent|per cent",
}


def fold(text: str) -> str:
    """Without Vietnamese marks, as OCR text is compared."""
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


UNITS = {fold(s) if f else s: unit for unit, spec in _TABLE.items() for s in spec.split("|") for f in (0, 1)}
LONGEST = max(len(s.split()) for s in UNITS)


def prefix_at(text: str, start: int) -> str:
    """R12c + R14: the symbols right before a number.

    The run of characters that are neither letters, digits nor spaces glued to it ('$5', '<=5', '≤(5)'),
    brackets and quotes left out; else a glued 'x' ('x2'); else, past spaces and opening brackets/quotes,
    the previous token's trailing symbols ('Bake≤ 5', '$ 5', '≤ (5)', '- 18') or a standalone 'x'
    ('x 2'). Sentence punctuation ('cups, 5', 'đợi... 5') and unit marks ('10% 5') are not symbols."""
    i = start
    while i > 0 and not text[i - 1].isalnum() and not text[i - 1].isspace():
        i -= 1
    run = "".join(c for c in text[i:start] if c not in OPENERS)
    if run:
        return run
    if text[i - 1 : i] == "x" and (i == 1 or not text[i - 2].isalnum()):
        return "x"
    j = i
    while j > 0 and (text[j - 1].isspace() or text[j - 1] in OPENERS):
        j -= 1
    if j == i:
        return ""  # nothing between the previous word and the number
    word = text[:j].split()[-1:]
    word = word[0].lstrip(OPENERS) if word else ""
    if word in ("x", "×"):
        return word
    k = len(word)
    while k > 0 and not word[k - 1].isalnum():
        k -= 1
    return "".join(c for c in word[k:] if c not in SENTENCE + OPENERS + POSTFIX)


def _edges(word: str) -> list[str]:
    """The non-empty runs of symbols at the front and at the end of a word with a letter or digit."""
    k, n = 0, len(word)
    while not word[k].isalnum():
        k += 1
    while not word[n - 1].isalnum():
        n -= 1
    return [run for run in (word[:k], word[n:]) if run]


def _symbols(token: str) -> list[str]:
    """R16c: the symbols one token before a number holds, brackets and quotes left out: the whole token
    when it has no letter or digit ('≤', '$', '-', '<='), a standalone 'x'/'×', else the symbols glued to
    its front ('≤about') or its end ('Bake≤'). Sentence punctuation and unit marks are not symbols."""
    word = "".join(c for c in token if c not in BRACKETS)
    if word in ("x", "×"):
        return [word]
    runs = [word] if not any(c.isalnum() for c in word) else _edges(word)
    runs = ["".join(c for c in run if c not in SENTENCE + POSTFIX) for run in runs]
    return [run for run in runs if run]


def symbols_before(text: str, start: int) -> tuple[str, ...]:
    """R16c: the symbols before a number, sorted (a multiset): those glued to it in its own token ('$' of
    '$5', '≤' of '≤(5)', 'x' of 'x2') and those of the LOOKBACK tokens before it, so a word in between
    ('Bake ≤ about 5', 'Price $ approx. 5') does not hide one."""
    head = text[:start]
    cut = len(head) if not head[-1:] or head[-1].isspace() else len(head) - len(head.split()[-1])
    own = "".join(c for c in head[cut:] if c not in BRACKETS)
    if own in ("x", "×") or not any(c.isalnum() for c in own):
        found = [own] if own else []
    else:
        found = _edges(own)  # '≤about5', 'giá$5'
    for token in head[:cut].split()[-LOOKBACK:]:
        found += _symbols(token)
    return tuple(sorted(found))


def value_prefixes_agree(value: str, source: str, language: str | None) -> bool:
    """R12c for a Material/Parameter: a symbol before a number in the quote ('- 18', '<=5', '~5', '+5')
    must be before the number in the value itself; R16c: so must one a few words before it
    ('≤ about 5')."""

    def symbols(raw: str, lang):
        spelled = spell_digits(" ".join(clean(raw).casefold().split()), lang)[0]
        return [
            (prefix_at(spelled, m.start()), symbols_before(spelled, m.start()))
            for m in NUMBER.finditer(spelled)
        ]

    ours = set(symbols(value, None))
    return all(p == ("", ()) or p in ours for p in symbols(source, language))


def unit_at(text: str, end: int) -> tuple[str, str | None]:
    """(unit as written, canonical unit or None) right after a number.

    A unit written on the number ('200g', '3분', '180°c') is that whole word; otherwise the longest
    table spelling of up to three words ('muỗng cà phê', 'độ c'), else the next word."""
    rest = text[end:]
    if rest[:1] and not rest[:1].isspace():
        word = rest.split()[0].strip(PUNCT)
        return word, UNITS.get(word)
    words = [w.strip(PUNCT) for w in rest.split()[:LONGEST]]
    for n in range(len(words), 1, -1):
        phrase = " ".join(words[:n])
        if phrase in UNITS:
            return phrase, UNITS[phrase]
    word = words[0] if words else ""
    return word, UNITS.get(word)


def around(text: str, spans: list[tuple[int, int]], shape) -> list[tuple]:
    """((symbol right before, symbols a few tokens before), number shape, unit after) per number span."""
    return [
        ((prefix_at(text, a), symbols_before(text, a)), shape(text[a:b]), unit_at(text, b)) for a, b in spans
    ]


def _same(ours: tuple[str, str | None], theirs: tuple[str, str | None], mode: str) -> bool:
    written = ours[0] == theirs[0]
    canonical = ours[1] is not None and ours[1] == theirs[1]
    return {"same": written, "cross": canonical}.get(mode, written or canonical)


def claim_units_agree(text: str, source: str, source_language: str | None, mode: str) -> bool:
    """R4c: each number of the claim text has the same symbol and unit as the same number in its quote.

    `mode` 'same' (claim and quote in one language): units equal as written; 'cross': both units in the
    canonical table and equal; 'any' (OCR, or a language unknown): either of the two."""

    def keyed(raw: str, language: str | None):
        spelled = spell_digits(" ".join(clean(raw).casefold().split()), language)[0]
        return around(spelled, [m.span() for m in NUMBER.finditer(spelled)], number_shape)

    ours, theirs = keyed(text, None), keyed(source, source_language)
    if len(ours) != len(theirs):
        return False
    for symbol, shape, unit in ours:
        pick = next(
            (k for k, (s, n, u) in enumerate(theirs) if (s, n) == (symbol, shape) and _same(unit, u, mode)),
            None,
        )
        if pick is None:
            return False
        theirs.pop(pick)
    return True


def numbers_line_up(needle, haystack, needle_spans, haystack_spans, shape) -> bool:
    """C2 + R4b: numbers pair up in order with the same symbol before and the same unit after."""
    ours = [(p, n, u[0]) for p, n, u in around(needle, needle_spans, shape)]
    theirs = [(p, n, u[0]) for p, n, u in around(haystack, haystack_spans, shape)]
    return ours == theirs


def has_digit(*texts: str | None) -> bool:
    return any(re.search(r"\d", t or "") for t in texts)
