"""What sits around a number: the symbol before it and the unit after it (rulings C2, R4b, R4c).

Each check only ever turns a match into `unverified`; none of them can make a match succeed."""

import re
import unicodedata

from app.services.verification.numbers import NUMBER, number_shape, spell_digits

PUNCT = ".,;:!?()[]{}\"'"
SYMBOLS = "$€£¥₫×÷+~<>≤≥"  # 'x' counts too when it stands alone or is glued to the number ('x2')
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
    """The symbol right before a number ('$5', '€ 5', 'x2', '÷2', '~5'), else ''."""
    i = start
    while i > 0 and text[i - 1] == " ":
        i -= 1
    c = text[i - 1 : i]
    if c and c in SYMBOLS:
        return c
    if c == "x" and (i == 1 or not text[i - 2].isalnum()):
        return "x"
    return ""


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


def around(text: str, spans: list[tuple[int, int]], shape) -> list[tuple[str, str, tuple[str, str | None]]]:
    """(symbol before, number shape, unit after) per number span."""
    return [(prefix_at(text, a), shape(text[a:b]), unit_at(text, b)) for a, b in spans]


def _same(ours: tuple[str, str | None], theirs: tuple[str, str | None], mode: str) -> bool:
    written = ours[0] == theirs[0]
    canonical = ours[1] is not None and ours[1] == theirs[1]
    return {"same": written, "cross": canonical}.get(mode, written or canonical)


def claim_units_agree(text: str, source: str, source_language: str | None, mode: str) -> bool:
    """R4c: each number of the claim text has the same symbol and unit as the same number in its quote.

    `mode` 'same' (claim and quote in one language): units equal as written; 'cross': both units in the
    canonical table and equal; 'any' (OCR, or a language unknown): either of the two."""

    def keyed(raw: str, language: str | None):
        spelled = spell_digits(" ".join(unicodedata.normalize("NFKC", raw).casefold().split()), language)[0]
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
