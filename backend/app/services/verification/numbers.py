"""Spelled-out Vietnamese and English numbers to digits (spec 3.3), so '200' meets 'hai trăm'."""

import re
import unicodedata

TOKEN = re.compile(r"\d+|[^\W\d_]+")
NUMBER = re.compile(r"(?:(?<!\w)[-–−])?\d+(?:[.,/\-–−]\d+)*")


def _table(spec):
    return {unicodedata.normalize("NFKC", w): kv for w, kv in spec.items()}


# kinds: u unit 0-9, n the word "năm" (5, or "year"), t tens or teens, x "mươi" (times ten),
# h/k hundred/thousand (upper case for Vietnamese, whose short forms are ambiguous), l filler
VI = _table(
    {"không": ("u", 0), "một": ("u", 1), "mốt": ("u", 1), "hai": ("u", 2), "ba": ("u", 3), "bốn": ("u", 4)}
    | {"tư": ("u", 4), "năm": ("n", 5), "lăm": ("u", 5), "sáu": ("u", 6), "bảy": ("u", 7), "tám": ("u", 8)}
    | {"chín": ("u", 9), "mười": ("t", 10), "mươi": ("x", 10), "trăm": ("H", 100), "nghìn": ("K", 1000)}
    | {"ngàn": ("K", 1000), "linh": ("l", 0), "lẻ": ("l", 0)}
)
_UNITS = "zero one two three four five six seven eight nine".split()
_TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
EN = {w: ("u", i) for i, w in enumerate(_UNITS)} | {w: ("t", 10 + i) for i, w in enumerate(_TEENS)}
EN |= {w: ("t", 20 + 10 * i) for i, w in enumerate(_TENS)}
EN |= {"hundred": ("h", 100), "thousand": ("k", 1000), "and": ("l", 0)}


def vocabulary(language: str | None) -> dict:
    """None means unknown spoken language (both tables); any other language only has digits."""
    code = (language or "").lower().split("-")[0].split("_")[0]
    return {"vi": VI, "en": EN}.get(code, {} if code else VI | EN)


def _evaluate(tokens: list[tuple[str, int]]) -> list[int] | None:
    """Numbers in a run of number words; None when a colloquial Vietnamese form is ambiguous.

    'một trăm năm mươi' is 150, but 'một trăm năm' (105 or 150), 'hai trăm tư', 'một nghìn hai' and
    'hai mươi năm' are left unread so that nothing can match them by accident."""
    out, total, cur, small = [], 0, 0, None
    scaled = linked = loose = bad = False

    def flush():
        nonlocal total, cur, small, scaled, linked, loose, bad
        out.append(None if loose or bad else total + cur + (small or 0))
        total, cur, small, scaled, linked, loose, bad = 0, 0, None, False, False, False, False

    for kind, value in tokens:
        low = kind.lower()
        if low in "un":
            if small is not None and small >= 10 and small % 10 == 0 and value:
                bad, small = bad or kind == "n", small + value
            else:
                if small is not None:
                    flush()
                small, loose = value, scaled and not linked
        elif low == "t":
            if small is not None:
                flush()
            small = value
        elif low == "x":
            small, loose = (small if small is not None and small < 10 else 1) * 10, False
        elif low in "hk":
            if low == "h" and cur >= 100:
                flush()
            amount = (small or 1) if low == "h" else (cur + (small or 0) or 1)
            if low == "h":
                cur += amount * 100
            else:
                total, cur = total + amount * 1000, 0
            small, loose, linked, scaled = None, False, False, scaled or kind.isupper()
        elif low == "l":
            linked = True
    flush()
    return None if None in out else out


def spell_digits(text: str, language: str | None) -> tuple[str, list[int], list[int]]:
    """Rewrite number words as digits in already-normalized text.

    Returns the new text plus, per new character, the start and end of the source span it came from."""
    vocab, pieces, group = vocabulary(language), [], []
    tokens = [(m, vocab.get(m.group())) for m in TOKEN.finditer(text)]
    for m, entry in tokens + [(None, None)]:
        if entry and (not group or not text[group[-1][0].end() : m.start()].strip(" -")):
            group.append((m, entry))
            continue
        while group and group[-1][1][0] == "l":
            group.pop()
        while group and group[0][1][0] == "l":
            group.pop(0)
        values = _evaluate([e for _, e in group]) if group else None
        if values is not None and group:
            pieces.append((group[0][0].start(), group[-1][0].end(), values))
        group = [(m, entry)] if entry else []
    out, starts, ends, pos = [], [], [], 0
    for begin, end, values in pieces:
        new = " ".join(map(str, values))
        out.append(text[pos:begin]), starts.extend(range(pos, begin)), ends.extend(range(pos + 1, begin + 1))
        out.append(new), starts.extend([begin] * len(new)), ends.extend([end] * len(new))
        pos = end
    out.append(text[pos:]), starts.extend(range(pos, len(text))), ends.extend(range(pos + 1, len(text) + 1))
    return "".join(out), starts, ends


def _digits(run: str) -> str:
    return "".join(str(unicodedata.digit(c)) for c in run).lstrip("0") or "0"


def digit_runs(text: str, language: str | None) -> list[str]:
    """Consecutive-digit runs after number words become digits; leading zeros dropped ('007' -> '7')."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return [_digits(run) for run in re.findall(r"\d+", spell_digits(folded, language)[0])]


def number_tokens(text: str, language: str | None) -> list[str]:
    """Whole numbers with their shape: '1,5' -> '1.5', '1/2', '2-3' (range) and '-18' stay distinct."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    out = []
    for m in NUMBER.finditer(spell_digits(folded, language)[0]):
        token = m.group().replace("–", "-").replace("−", "-")
        body = token.lstrip("-")
        parts = re.split(r"([.,/-])", body)
        shaped = "".join(_digits(p) if p[:1].isdigit() else p.replace(",", ".") for p in parts)
        out.append(token[: len(token) - len(body)] + shaped)
    return out
