"""Ruling X6: a material or parameter name only counts as proven when it is written next to the item's
own number ('Milk 4tsp', 'add 200 grams of sugar', 'Đường 200 g', '200 g đường').

Between the number and the name only units (the table's or the item's own: 'quả', 'giọt'), 'of'/'của',
articles, brackets, ':' or '-', setting words ('ở'/'at', approximators) and, before a range, 'từ'/'from'
may stand, at most GAP tokens of them. A conjunction ('and', 'và', 'plus', 'then', 'rồi'...), a separator
(',', ';', '+', '&', a line break), another number or any other word ends the search, so 'Sugar 200g, salt',
'add 200 grams of sugar and a pinch of salt' and the rows 'Sugar 200g' / 'Salt' prove sugar, not salt.
One exception, the caption layout of the live cooking video: a number alone on its OCR row (with its unit)
belongs to the label row right above it when that row has no number ('Milk' / '4tsp').
Each check only ever turns a match into `unverified` or `quote_matched`; none can make a match succeed."""

import re
from collections.abc import Callable

from app.services.verification import lexicon, units
from app.services.verification.numbers import join_ranges, number_shape, spell_digits

GLUED = "+±~≈<>≤≥$€£¥₫"  # symbols glued to a number belong to it ('+5', '$5'); spaced, they separate
TOKEN = re.compile(rf"\n|\.{{2,}}|…|°[cf]?|[{GLUED}]*-?\d+(?:[.,/:\-]\d+)*|[^\W\d_]+|[^\w\s]")
GAP = 3  # tokens allowed between the number and the name: 'add 200 grams of the sugar'
BETWEEN = {"of", "của", "cua", "a", "an", "the", ":", "-", "°", "°c", "°f", "%"}
BETWEEN |= set("()[]\"'“”‘’") | {"...", "…"}  # brackets, quotes, a spoken pause ('đợi... 5 phút')
# where/when a setting applies ('Nướng ở 180°C') and approximators ('Sugar about 200 g') add no item
SETTING = {"ở", "o", "at", "khoảng", "khoang", "about", "around", "approximately", "tầm", "tam", "chừng"}
RANGE_START = {"từ", "tu", "from"}  # 'nấu từ 7 đến 10 phút', only before a range
BREAK = "\n"


def _line(line: str, folded: bool, language: str | None, spoken: bool, ranges: bool) -> str:
    text = " ".join(lexicon.clean(line).casefold().split())
    if spoken:
        text = spell_digits(text, language)[0]
    if folded:
        text = units.fold(text)
    return join_ranges(text)[0] if ranges else text


def tokens(text: str, folded: bool, language: str | None = None, spoken: bool = False, ranges=False):
    """Normalized tokens (folded on screen, number words read in speech), a line break kept as a token."""
    lines = [_line(r, folded, language, spoken, ranges) for r in text.split("\n")]
    return TOKEN.findall(re.sub(r"\.{2,}", "...", f" {BREAK} ".join(lines)))


def _word(token: str) -> bool:
    return bool(re.fullmatch(r"[^\W\d_]+", token))


def _unit(words: list[str], i: int, step: int, table: dict) -> int:
    """Length of the longest unit spelling that ends (step -1) or starts (step 1) at index i, else 0."""
    for size in range(units.LONGEST, 0, -1):
        lo, hi = (i - size + 1, i + 1) if step < 0 else (i, i + size)
        if lo >= 0 and hi <= len(words) and " ".join(words[lo:hi]) in table:
            return size
    return 0


def _row(words: list[str], k: int) -> tuple[int, int]:
    """(start, end) of the OCR row holding index k."""
    lo, hi = k, k
    while lo > 0 and words[lo - 1] != BREAK:
        lo -= 1
    while hi < len(words) and words[hi] != BREAK:
        hi += 1
    return lo, hi


class _Walk:
    """Tokens next to one number, outward in one direction."""

    def __init__(self, words: list[str], k: int, step: int, table: dict, skip: set, label: bool):
        self.words, self.step, self.table, self.skip, self.label = words, step, table, skip, label
        self.i = k + step

    def _skip(self) -> int:
        """Tokens at the current index that may stand between the number and the name, else 0."""
        return _unit(self.words, self.i, self.step, self.table) or (
            1 if self.words[self.i] in self.skip else 0
        )

    def _cross(self) -> bool:
        """One line break, going left, onto a label row without numbers ('Milk' / '4tsp')."""
        if not (self.label and self.step < 0 and self.i > 0 and self.words[self.i] == BREAK):
            return False
        lo, _ = _row(self.words, self.i - 1)
        if any(any(c.isdigit() for c in w) for w in self.words[lo : self.i]):
            return False
        self.label, self.i = False, self.i - 1
        return True

    def first(self) -> int | None:
        """Index of the first token past at most GAP skippable ones, None when the text ends first."""
        gap = 0
        while 0 <= self.i < len(self.words):
            if self._cross():
                continue
            size = self._skip()
            if not size:
                return self.i if gap <= GAP else None
            gap, self.i = gap + size, self.i + self.step * size
        return None


def _bare(words: list[str], k: int, table: dict, skip: set) -> bool:
    """The OCR row of index k holds only that number, units and words that may stand between."""
    lo, hi = _row(words, k)
    i = lo
    while i < hi:
        size = 1 if i == k or words[i] in skip else _unit(words, i, 1, table)
        if not size:
            return False
        i += size
    return True


def _spots(words: list[str], shape: str, folded: bool, unit: list[str]):
    table = units.UNITS if folded else units.WRITTEN
    skip = BETWEEN | SETTING | set(unit) | (RANGE_START if "-" in shape else set())
    for k, word in enumerate(words):
        bare = word.lstrip(GLUED)
        if bare[-1:].isdigit() and number_shape(bare) == shape:
            label = _bare(words, k, table, skip)
            yield _Walk(words, k, -1, table, skip, label), _Walk(words, k, 1, table, skip, False)


def regions(words: list[str], shape: str, size: int, folded: bool, unit=()) -> list[tuple[int, int]]:
    """X6: (start, end) of the `size` words right before and right after each number shaped `shape`,
    past what may stand between; regions with anything but words are left out."""
    out = []
    for left, right in _spots(words, shape, folded, unit):
        a, b = left.first(), right.first()
        if a is not None and a - size + 1 >= 0:
            out.append((a - size + 1, a + 1))
        if b is not None and b + size <= len(words):
            out.append((b, b + size))
    return [(a, b) for a, b in out if all(_word(w) for w in words[a:b])]


def zones(words: list[str], shape: str, count: int, folded: bool, unit=()) -> list[str]:
    """X6 for the fuzzy name check (I2): the text beside each number shaped `shape`, outward, holding
    what may stand between (kept: 'nướng ở' for 'Nướng ở 180°C') and then `count` other words; it stops at
    a conjunction, separator, line break or another number."""
    out = []
    for walk in (w for pair in _spots(words, shape, folded, unit) for w in pair):
        picked, found, gap = [], 0, 0
        while 0 <= walk.i < len(words) and found < count:
            if walk._cross():
                continue
            size = walk._skip()
            if size:
                lo = walk.i if walk.step > 0 else walk.i - size + 1
                span = words[lo : lo + size]
                picked += span if walk.step > 0 else span[::-1]
                gap += 0 if found else size
                walk.i += walk.step * size
                continue
            word = words[walk.i]
            if not _word(word) or word in lexicon.CONJUNCTIONS:
                break
            picked.append(word)
            found, walk.i = found + 1, walk.i + walk.step
        if found and gap <= GAP:
            out.append(" ".join(picked if walk.step > 0 else picked[::-1]))
    return out


def by_number(words: list[str], shape: str, size: int, folded: bool, accept: Callable, unit=()) -> bool:
    """Some region next to a number shaped `shape` satisfies accept(words, start, end)."""
    return any(accept(words, a, b) for a, b in regions(words, shape, size, folded, unit))


def plain(word: str | None, folded: bool) -> bool:
    """X1a: a word that cannot turn the ingredient beside it into another one."""
    table = units.UNITS if folded else units.WRITTEN
    if word is None or word == BREAK or any(c.isdigit() for c in word):
        return True
    return word in lexicon.NEIGHBOURS or word in BETWEEN or word in SETTING or word in table


def phrase_at(phrase: list[str], neighbours: bool, folded: bool) -> Callable:
    """accept() for a word-for-word phrase; `neighbours`: the words around it must be `plain` (X1a)."""

    def accept(words: list[str], a: int, b: int) -> bool:
        if words[a:b] != phrase:
            return False
        if not neighbours:
            return True
        before = words[a - 1] if a else None
        after = words[b] if b < len(words) else None
        return plain(before, folded) and plain(after, folded)

    return accept
