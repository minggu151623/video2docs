"""Spelled-out Vietnamese and English numbers to digits (spec 3.3), so '200' meets 'hai trăm'."""

import re
import unicodedata

TOKEN = re.compile(r"\d+|[^\W\d_]+")


def _table(spec):
    return {unicodedata.normalize("NFKC", w): kv for w, kv in spec.items()}


# kinds: u unit 0-9, t tens or teens, x "mươi" (times ten), h hundred, k thousand, l filler
VI = _table(
    {"không": ("u", 0), "một": ("u", 1), "mốt": ("u", 1), "hai": ("u", 2), "ba": ("u", 3), "bốn": ("u", 4)}
    | {"tư": ("u", 4), "năm": ("u", 5), "lăm": ("u", 5), "sáu": ("u", 6), "bảy": ("u", 7), "tám": ("u", 8)}
    | {"chín": ("u", 9), "mười": ("t", 10), "mươi": ("x", 10), "trăm": ("h", 100), "nghìn": ("k", 1000)}
    | {"ngàn": ("k", 1000), "linh": ("l", 0), "lẻ": ("l", 0)}
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


def _evaluate(tokens: list[tuple[str, int]]) -> list[int]:
    out, total, cur, small = [], 0, 0, None

    def flush():
        nonlocal total, cur, small
        out.append(total + cur + (small or 0))
        total, cur, small = 0, 0, None

    for kind, value in tokens:
        if kind == "u":
            if small is not None and not (small >= 10 and small % 10 == 0 and value):
                flush()
            small = value if small is None else small + value
        elif kind == "t":
            if small is not None:
                flush()
            small = value
        elif kind == "x":
            small = (small if small is not None and small < 10 else 1) * 10
        elif kind == "h":
            if cur >= 100:
                flush()
            cur += (small or 1) * 100
            small = None
        elif kind == "k":
            total, cur, small = total + (cur + (small or 0) or 1) * 1000, 0, None
    flush()
    return out


def spell_digits(text: str, language: str | None) -> tuple[str, list[int], list[int]]:
    """Rewrite number words as digits in already-normalized text.

    Returns the new text plus, per new character, the start and end of the source span it came from."""
    vocab, pieces, group = vocabulary(language), [], []
    tokens = [(m, vocab.get(m.group())) for m in TOKEN.finditer(text)]
    for m, entry in tokens + [(None, None)]:
        if entry and (not group or not text[group[-1][0].end() : m.start()].strip()):
            group.append((m, entry))
            continue
        while group and group[-1][1][0] == "l":
            group.pop()
        while group and group[0][1][0] == "l":
            group.pop(0)
        if group:
            pieces.append((group[0][0].start(), group[-1][0].end(), [e for _, e in group]))
        group = [(m, entry)] if entry else []
    out, starts, ends, pos = [], [], [], 0
    for begin, end, entries in pieces:
        new = " ".join(str(v) for v in _evaluate(entries))
        chunk = text[pos:begin]
        out.append(chunk), starts.extend(range(pos, begin)), ends.extend(range(pos + 1, begin + 1))
        out.append(new), starts.extend([begin] * len(new)), ends.extend([end] * len(new))
        pos = end
    out.append(text[pos:]), starts.extend(range(pos, len(text))), ends.extend(range(pos + 1, len(text) + 1))
    return "".join(out), starts, ends


def digit_runs(text: str, language: str | None) -> list[str]:
    """Consecutive-digit runs after number words become digits; leading zeros dropped ('007' -> '7')."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    spelled = spell_digits(folded, language)[0]
    runs = ("".join(str(unicodedata.digit(c)) for c in run) for run in re.findall(r"\d+", spelled))
    return [run.lstrip("0") or "0" for run in runs]
