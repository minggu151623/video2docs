"""Spelled-out Vietnamese and English numbers to digits (spec 3.3), so '200' meets 'hai trăm'."""

import re
import unicodedata

TOKEN = re.compile(r"\d+|[^\W\d_]+")
NUMBER = re.compile(r"(?:(?<!\w)[-–−])?(?:(?<![\d.,/])[.,]\d+|\d+)(?:[.,/\-–−]\d+)*")


def _table(spec):
    return {unicodedata.normalize("NFKC", w): kv for w, kv in spec.items()}


# kinds: u unit 0-9, n the word "năm" (5, or "year"), t tens or teens, x "mươi" (times ten),
# h/k/m hundred/thousand/million (upper case for Vietnamese, whose short forms are ambiguous), l filler
VI = _table(
    {"không": ("u", 0), "một": ("u", 1), "mốt": ("u", 1), "hai": ("u", 2), "ba": ("u", 3), "bốn": ("u", 4)}
    | {"tư": ("u", 4), "năm": ("n", 5), "lăm": ("u", 5), "sáu": ("u", 6), "bảy": ("u", 7), "tám": ("u", 8)}
    | {"chín": ("u", 9), "mười": ("t", 10), "mươi": ("x", 10), "trăm": ("H", 100), "nghìn": ("K", 1000)}
    | {"ngàn": ("K", 1000), "triệu": ("M", 10**6), "chục": ("x", 10), "linh": ("l", 0), "lẻ": ("l", 0)}
)
_UNITS = "zero one two three four five six seven eight nine".split()
_TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
EN = {w: ("u", i) for i, w in enumerate(_UNITS)} | {w: ("t", 10 + i) for i, w in enumerate(_TEENS)}
EN |= {w: ("t", 20 + 10 * i) for i, w in enumerate(_TENS)}
EN |= {"hundred": ("h", 100), "thousand": ("k", 1000), "million": ("m", 10**6), "and": ("l", 0)}
SCALES = {"x": 10, "h": 100, "k": 1000, "m": 10**6}


def number_words() -> set[str]:
    """Every Vietnamese and English number word except fillers and 'không', which is mostly 'not'."""
    return {w for table in (VI, EN) for w, (kind, _) in table.items() if kind != "l"} - {"không"}


def vocabulary(language: str | None) -> dict:
    """None means unknown spoken language (both tables); any other language only has digits."""
    code = (language or "").lower().split("-")[0].split("_")[0]
    return {"vi": VI, "en": EN}.get(code, {} if code else VI | EN)


def _evaluate(tokens: list[tuple[str, int]], article: bool = False) -> list[int] | None:
    """Numbers in a run of number words; None when the reading is ambiguous.

    'một trăm năm mươi' is 150, but 'một trăm năm' (105 or 150), 'hai trăm tư', 'một nghìn hai',
    'hai mươi năm', neighbours like 'hai ba' or 'four five' (25? 2-3?), a scale repeated at the
    same magnitude without a higher one between ('hai mươi ba mươi', 'hai nghìn ba nghìn') and a
    scale with nothing to multiply ('vài chục', 'mấy trăm', 'a few million') are left unread, so
    nothing can match them by accident. `article`: English 'a'/'an' right before is the multiplier 1."""
    out, total, cur, small, seen = [], 0, 0, 1 if article else None, set()
    scaled = linked = loose = bad = False

    def finish(clean=True):
        nonlocal total, cur, small, seen, scaled, linked, loose, bad
        out.append(None if loose or bad or not clean else total + cur + (small or 0))
        total, cur, small, seen = 0, 0, None, set()
        scaled = linked = loose = bad = False

    def scale(low):
        nonlocal seen, bad
        bad = bad or SCALES[low] in seen
        seen = {m for m in seen if m > SCALES[low]} | {SCALES[low]}

    for kind, value in tokens:
        low = kind.lower()
        if low in "un":
            if small is not None and small >= 10 and small % 10 == 0 and value:
                bad, small = bad or kind == "n", small + value
            else:
                if small is not None:
                    finish(False)
                small, loose = value, scaled and not linked
        elif low == "t":
            if small is not None:
                finish(False)
            small = value
            if value % 10 == 0:
                scale("x")
        elif low == "x":
            scale("x")
            bad = bad or small is None or small >= 10  # bare 'chục', 'mươi'
            small, loose = (small if small is not None and small < 10 else 1) * 10, False
        elif low in "hkm":
            scale(low)
            bad = bad or small is None and (low == "h" or not cur)  # bare 'trăm', 'thousand'
            bad = bad or loose and low != "h"  # 'ba trăm hai nghìn': 302 or 320 thousand
            if low == "h":
                cur += (small or 0) * 100
            else:
                total, cur = total + (cur + (small or 0)) * SCALES[low], 0
            small, loose, linked, scaled = None, False, False, scaled or kind.isupper()
        elif total or cur:  # filler inside a number: 'một trăm linh năm', 'one hundred and five'
            linked = True
        elif small is not None:  # filler between two numbers: 'twenty five and one hundred'
            finish()
    finish()
    return None if None in out else out


def _joined(text: str, left, right) -> bool:
    return not text[left.end() : right.start()].strip(" -")


def _runs(text: str, vocab: dict) -> list[tuple[int, int, list[int] | None]]:
    """(begin, end, values) per run of number words; values is None when the run is not read."""
    runs, group = [], []
    tokens = [(m, vocab.get(m.group())) for m in TOKEN.finditer(text)]
    for i, (m, entry) in enumerate(tokens):  # 'không' is 0 only before a number word ('không trăm')
        nxt = tokens[i + 1] if i + 1 < len(tokens) else (None, None)
        if m.group() == "không" and not (nxt[1] and nxt[1][0] != "l" and _joined(text, m, nxt[0])):
            tokens[i] = (m, None)
    for m, entry in tokens + [(None, None)]:
        if entry and (not group or _joined(text, group[-1][0], m)):
            group.append((m, entry))
            continue
        while group and group[-1][1][0] == "l":
            group.pop()
        while group and group[0][1][0] == "l":
            group.pop(0)
        if group:
            begin = group[0][0].start()
            article = group[0][1][0] in "hkm" and re.search(r"(?<!\w)an?\s+$", text[:begin]) is not None
            runs.append((begin, group[-1][0].end(), _evaluate([e for _, e in group], article)))
        group = [(m, entry)] if entry else []
    return runs


def spell_digits(text: str, language: str | None) -> tuple[str, list[int], list[int]]:
    """Rewrite number words as digits in already-normalized text.

    Returns the new text plus, per new character, the start and end of the source span it came from."""
    pieces = [(b, e, v) for b, e, v in _runs(text, vocabulary(language)) if v is not None]
    out, starts, ends, pos = [], [], [], 0
    for begin, end, values in pieces:
        new = " ".join(map(str, values))
        out.append(text[pos:begin]), starts.extend(range(pos, begin)), ends.extend(range(pos + 1, begin + 1))
        out.append(new), starts.extend([begin] * len(new)), ends.extend([end] * len(new))
        pos = end
    out.append(text[pos:]), starts.extend(range(pos, len(text))), ends.extend(range(pos + 1, len(text) + 1))
    return "".join(out), starts, ends


def _ascii(run: str) -> str:
    return "".join(str(unicodedata.digit(c)) for c in run)


def _digits(run: str) -> str:
    return _ascii(run).lstrip("0") or "0"


def digit_runs(text: str, language: str | None) -> list[str]:
    """Consecutive-digit runs after number words become digits; leading zeros dropped ('007' -> '7')."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return [_digits(run) for run in re.findall(r"\d+", spell_digits(folded, language)[0])]


def number_tokens(text: str, language: str | None) -> list[str]:
    """Whole numbers with their shape: '1,5' -> '1.5', '1/2', '2-3' (range), '-18' and '.05' stay distinct.

    A run of number words that is not read ('hai ba') becomes one opaque token '~hai ba', so two texts
    only agree when they hold the same unread words."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    out = [
        "~" + " ".join(folded[b:e].split()) for b, e, v in _runs(folded, vocabulary(language)) if v is None
    ]
    for m in NUMBER.finditer(spell_digits(folded, language)[0]):
        token = m.group().replace("–", "-").replace("−", "-")
        body = token.lstrip("-")
        parts = re.split(r"([.,/-])", body)
        sign = token[: len(token) - len(body)]
        # only the leading zeros of the whole part go: '007' is 7 but '0,05', '1.05' and '.05' keep theirs
        first = "" if parts[0] == "" else _digits(parts[0])
        rest = "".join(_ascii(p) if p[:1].isdigit() else p.replace(",", ".") for p in parts[1:])
        out.append(sign + first + rest)
    return out
