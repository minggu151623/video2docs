"""Spelled-out Vietnamese and English numbers to digits (spec 3.3), so '200' meets 'hai trăm'."""

import re
import unicodedata

TOKEN = re.compile(r"\d+|[^\W\d_]+")
NUMBER = re.compile(r"(?:(?<!\w)[-–−])?(?:(?<![\d.,/:])[.,]\d+|\d+)(?:[.,/:\-–−]\d+)*")
SEPARATORS = (".", ",", "/", ":")


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
DECIMAL_MARKS = {"phẩy": ("một",), "chấm": ("một",), "point": ("one",)}  # active with that table


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


def _marks(vocab: dict) -> set[str]:
    """Words that make a decimal point in speech ('không phẩy năm', 'point five'), per language."""
    return {m for m, lang in DECIMAL_MARKS.items() if any(w in vocab for w in lang)}


def _tokens(text: str, vocab: dict) -> list:
    tokens = [(m, vocab.get(m.group())) for m in TOKEN.finditer(text)]
    marks = _marks(vocab)

    def number_at(k: int, after, digits: bool) -> bool:  # a number word (or digits) at k, joined to `after`
        if k >= len(tokens) or not _joined(text, after, tokens[k][0]):
            return False
        m, entry = tokens[k]
        return bool(entry and entry[0] != "l") or digits and m.group()[0].isdigit()

    for i, (m, entry) in enumerate(tokens):  # 'không' is 0 only before a number word or a built decimal
        nxt = tokens[i + 1][0] if i + 1 < len(tokens) else None
        number_next = number_at(i + 1, m, False)
        decimal = nxt is not None and nxt.group() in marks and _joined(text, m, nxt)
        decimal = decimal and number_at(i + 2, nxt, True)  # R9: 'không chấm nước mắm' stays a negation
        if m.group() == "không" and not (number_next or decimal):
            tokens[i] = (m, None)
        prev = tokens[i - 1][0] if i else None
        if m.group() == "trăm" and prev is not None and prev.group() == "phần" and _joined(text, prev, m):
            tokens[i] = (m, None)  # 'mười phần trăm' is 10 percent, not a hundred
    return tokens


def _runs(text: str, tokens: list) -> list[tuple[int, int, int, int, list[int] | None, list]]:
    """(begin, end, first token, last token, values, entries) per run of number words; values is None
    when the run is not read."""
    runs, group = [], []
    for k, (m, entry) in enumerate(tokens + [(None, None)]):
        if entry and (not group or _joined(text, group[-1][1], m)):
            group.append((k, m, entry))
            continue
        while group and group[-1][2][0] == "l":
            group.pop()
        while group and group[0][2][0] == "l":
            group.pop(0)
        if group:
            begin, entries = group[0][1].start(), [e for _, _, e in group]
            article = entries[0][0] in "hkm" and re.search(r"(?<!\w)an?\s+$", text[:begin]) is not None
            run = (begin, group[-1][1].end(), group[0][0], group[-1][0], _evaluate(entries, article), entries)
            runs.append(run)
        group = [(k, m, entry)] if entry else []
    return runs


def _operand(text: str, tokens: list, runs: dict, k: int, side: int):
    """The number on one side of a decimal point: (begin, end, run or digit match) or None."""
    if not 0 <= k < len(tokens):
        return None
    m = tokens[k][0]
    run = runs.get((k, side))
    if run:
        return run[0], run[1], run
    if m.group()[0].isdigit():
        return m.start(), m.end(), m
    return None


def _fraction_digits(operand) -> str | None:
    """Digits after a spoken decimal point: 'năm' 5, 'hai lăm' 25, 'one four' 14, 'không năm' 05."""
    if isinstance(operand, re.Match):
        return _ascii(operand.group())
    *_, values, entries = operand
    if all(kind.lower() in "un" and value < 10 for kind, value in entries):
        return "".join(str(value) for _, value in entries)
    return str(values[0]) if values and len(values) == 1 else None


def _decimals(text: str, tokens: list, runs: list, marks: set[str]) -> list[tuple[int, int, str | None]]:
    """(begin, end, 'X.Y') per spoken decimal; None for a decimal phrase that cannot be read."""
    out = []
    ends, starts = {(r[3], -1): r for r in runs}, {(r[2], 1): r for r in runs}
    for k, (m, _) in enumerate(tokens):
        if m.group() not in marks:
            continue
        right = _operand(text, tokens, starts, k + 1, 1)
        if right is None or not _joined(text, m, tokens[k + 1][0]):
            continue
        left = _operand(text, tokens, ends, k - 1, -1)
        if left is not None and not _joined(text, tokens[k - 1][0], m):
            left = None
        begin = left[0] if left else m.start()
        whole = "0"
        if left and isinstance(left[2], re.Match):
            whole = None if text[left[0] - 1 : left[0]] in SEPARATORS else _digits(left[2].group())
        elif left:
            values = left[2][4]
            whole = str(values[0]) if values and len(values) == 1 else None
        digits = _fraction_digits(right[2])
        if isinstance(right[2], re.Match) and text[right[1] : right[1] + 1] in SEPARATORS:
            digits = None  # 'phẩy 5,3'
        readable = whole is not None and digits is not None and 1 <= len(digits) <= 2
        out.append((begin, right[1], f"{whole}.{digits}" if readable else None))
    return out


def _pieces(text: str, vocab: dict) -> list[tuple[int, int, str | None]]:
    """Spans to rewrite, in order: (begin, end, digits) or (begin, end, None) for an unread phrase."""
    tokens = _tokens(text, vocab)
    runs = _runs(text, tokens)
    decimals = _decimals(text, tokens, runs, _marks(vocab))
    covered = [(b, e) for b, e, _ in decimals]
    pieces = list(decimals)
    for begin, end, _, _, values, _ in runs:
        if not any(b <= begin and end <= e for b, e in covered):
            pieces.append((begin, end, None if values is None else " ".join(map(str, values))))
    return sorted(pieces)


def _spell(text: str, language: str | None):
    """Number words rewritten as digits, the source span per new character, and unread phrases as
    (begin, end, words) in the new text."""
    out, starts, ends, unread, pos, size = [], [], [], [], 0, 0
    for begin, end, new in _pieces(text, vocabulary(language)):
        out.append(text[pos:begin]), starts.extend(range(pos, begin)), ends.extend(range(pos + 1, begin + 1))
        size += begin - pos
        if new is None:
            new = text[begin:end]
            unread.append((size, size + len(new), new))
            starts.extend(range(begin, end)), ends.extend(range(begin + 1, end + 1))
        else:
            starts.extend([begin] * len(new)), ends.extend([end] * len(new))
        out.append(new)
        size += len(new)
        pos = end
    out.append(text[pos:]), starts.extend(range(pos, len(text))), ends.extend(range(pos + 1, len(text) + 1))
    return "".join(out), starts, ends, unread


def spell_digits(text: str, language: str | None) -> tuple[str, list[int], list[int]]:
    """Rewrite number words as digits in already-normalized text ('không phẩy năm' becomes '0.5').

    Returns the new text plus, per new character, the start and end of the source span it came from."""
    return _spell(text, language)[:3]


def _ascii(run: str) -> str:
    return "".join(str(unicodedata.digit(c)) for c in run)


def _digits(run: str) -> str:
    return _ascii(run).lstrip("0") or "0"


def digit_runs(text: str, language: str | None) -> list[str]:
    """Consecutive-digit runs after number words become digits; leading zeros dropped ('007' -> '7')."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return [_digits(run) for run in re.findall(r"\d+", spell_digits(folded, language)[0])]


def number_shape(token: str) -> str:
    """One written number in canonical form: '007' -> '7', '.5' and ',5' -> '0.5', '1,5' -> '1.5'.

    A comma or point before one or two digits is a decimal point; before three or more digits it is kept
    as written, so '1,500' (thousands in English) and '1.500' (thousands in Vietnamese) stay distinct."""
    token = token.replace("–", "-").replace("−", "-")
    body = token.lstrip("-")
    parts = re.split(r"([.,/:-])", body)
    # only the leading zeros of the whole part go: '007' is 7 but '0,05' and '1.05' keep theirs
    out = ["0" if parts[0] == "" else _digits(parts[0])]
    for sep, group in zip(parts[1::2], parts[2::2]):
        digits = _ascii(group)
        out += ["." if sep in ".," and len(digits) <= 2 else sep, digits]
    return token[: len(token) - len(body)] + "".join(out)


def number_tokens(text: str, language: str | None) -> list[str]:
    """Whole numbers with their shape: '1,5' -> '1.5', '1/2', '2-3' (range), '1:30', '-18' stay distinct.

    A run of number words that is not read ('hai ba', 'hai ba phẩy năm') becomes one opaque token
    '~hai ba', so two texts only agree when they hold the same unread words."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    spelled, _, _, unread = _spell(folded, language)
    out = ["~" + " ".join(words.split()) for _, _, words in unread]
    for m in NUMBER.finditer(spelled):
        if any(b <= m.start() < e for b, e, _ in unread):
            continue
        out.append("~" + _glued(spelled, m) if _glued(spelled, m) else number_shape(m.group()))
    return out


def _glued(text: str, m) -> str:
    """R8: a sign or separator glued between a letter and the number ('freezer-18', 'dùng.05') cannot be
    read as signed or unsigned; returns that sign plus the number, else ''."""
    at = m.start()
    if m.group()[0] in "-–−.,":
        lead = ""
    elif at and text[at - 1] in "-–−.,/:":
        at, lead = at - 1, text[at - 1]
    else:
        return ""
    return lead + m.group() if at and text[at - 1].isalpha() else ""
