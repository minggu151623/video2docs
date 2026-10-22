"""Deterministic matcher: model-quoted text against ASR words and OCR text (spec 3.3). No LLM involved.

Safety rules: a number must match exactly (a spelled number is converted first, a number cut by the
alignment edge never counts), whole quotes are compared inside each evidence window separately, and
every doubt ends as `unverified`."""

import unicodedata
from bisect import bisect_right
from collections import Counter
from itertools import accumulate
from collections.abc import Iterator
from typing import Any
from rapidfuzz import fuzz
from app.schemas.tutorial_v2 import ExactInput, Material, Parameter, TutorialDraftV2
from app.schemas.verification import ItemVerification, Transcript, Word
from app.services.verification.numbers import digit_runs, spell_digits

NO_VALUE = "giá trị không có trong nguyên văn"
DIGITS_ONLY = "und"
JOINERS = ".,/"


def normalize(text: str) -> str:
    """NFKC, casefold and single spaces; diacritics and every script are kept."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def transcript_window(t: Transcript, start: float, end: float, pad: float) -> str:
    return " ".join(w.text for w in _window_words(t, start, end, pad))


def _window_words(t: Transcript, start: float, end: float, pad: float) -> list[Word]:
    low, high = start - pad, end + pad
    return [w for w in t.words if w.end >= low and w.start <= high]


def contains_numbers(needle: str, haystack: str, language: str | None) -> bool:
    """Every digit run of the needle is in the haystack, counting multiplicity."""
    return not Counter(digit_runs(needle, language)) - Counter(digit_runs(haystack, language))


def _align(needle: str, haystack: str, threshold: int) -> tuple[int, int] | None:
    if not needle or not haystack:
        return None
    if len(haystack) < len(needle):  # a window shorter than the quote must resemble all of it
        return (0, len(haystack)) if fuzz.ratio(needle, haystack) >= threshold else None
    found = fuzz.partial_ratio_alignment(needle, haystack, score_cutoff=threshold)
    return (found.dest_start, found.dest_end) if found else None


def fuzzy_contains(needle: str, haystack: str, threshold: int) -> str | None:
    found = _align(needle, haystack, threshold)
    return haystack[found[0] : found[1]] if found else None


def _cuts_number(needle: str, haystack: str, start: int, end: int) -> bool:
    """True when the segment edge falls inside a longer number: '200' in '1200', '5' in '1,5'."""

    def joined(at: int, step: int) -> bool:
        if not 0 <= at < len(haystack):
            return False
        far = at + step
        return haystack[at].isdigit() or (
            haystack[at] in JOINERS and 0 <= far < len(haystack) and haystack[far].isdigit()
        )

    return (needle[0].isdigit() and joined(start - 1, -1)) or (needle[-1].isdigit() and joined(end, 1))


def _locate(needle: str, haystack: str, threshold: int, language: str | None) -> tuple[int, int, bool] | None:
    """(start, end, numbers_ok) of the best alignment on canonical text, None when the words differ."""
    found = _align(needle, haystack, threshold)
    if not found:
        return None
    ok = not _cuts_number(needle, haystack, *found) and contains_numbers(
        needle, haystack[found[0] : found[1]], language
    )
    return (*found, ok)


def _strip_blanks(text: str) -> tuple[str, list[int]]:
    keep = [i for i, c in enumerate(text) if not c.isspace()]
    return "".join(text[i] for i in keep), keep


def exact_input_matches(text: str, ocr_text: str, threshold: int = 95) -> str | None:
    """Code and commands compare as written; only whitespace differences are ignored."""
    needle, _ = _strip_blanks(text)
    haystack, keep = _strip_blanks(ocr_text)
    found = _locate(needle, haystack, threshold, DIGITS_ONLY)
    if not found or not found[2]:
        return None
    return ocr_text[keep[found[0]] : keep[found[1] - 1] + 1]


def _fold(text: str) -> str:
    """Normalized text without Vietnamese marks, one output character per input character."""
    out = []
    for ch in normalize(text).replace("đ", "d"):
        base = "".join(c for c in unicodedata.normalize("NFD", ch) if unicodedata.category(c) != "Mn")
        out.append(base if len(base) == 1 else ch)
    return "".join(out)


def _match_screen(
    expected: str, ocr_text: str, threshold: int, required: tuple[str, ...] = ()
) -> tuple[str | None, bool]:
    """PaddleOCR drops stacked Vietnamese diacritics, so both sides lose them; numbers stay exact."""
    needle, haystack = _fold(expected), _fold(ocr_text)
    found = _locate(needle, haystack, threshold, DIGITS_ONLY)
    ok = bool(found and found[2] and all(_fold(r) in haystack for r in required))
    return (normalize(ocr_text)[found[0] : found[1]] if found else None), ok


def _match_speech(quote: str, words: list[Word], language: str | None, threshold: int, required=()):
    """(matched text, first matched word start, values_ok) or None; diacritics stay significant."""
    spoken = [(w, normalize(w.text)) for w in words]
    spoken = [(w, t) for w, t in spoken if t]
    base = " ".join(t for _, t in spoken)
    word_starts = [0, *accumulate(len(t) + 1 for _, t in spoken)][:-1]
    needle = spell_digits(normalize(quote), language)[0]
    haystack, starts, ends = spell_digits(base, language)
    found = _locate(needle, haystack, threshold, language)
    if not found:
        return None
    begin, end = starts[found[0]], ends[found[1] - 1]
    exact = all(spell_digits(normalize(r), language)[0] in haystack for r in required)
    return base[begin:end], spoken[bisect_right(word_starts, begin) - 1][0].start, found[2] and exact


def _value(item) -> str | None:
    return {Material: lambda: item.quantity, Parameter: lambda: item.value}.get(
        type(item), lambda: item.text
    )()


def _consistent(item, source_text: str, language: str | None, threshold: int) -> bool:
    """Spec 3.3 tier 1: the item's own value must be in the verbatim text it was extracted from."""
    if isinstance(item, ExactInput):
        return exact_input_matches(item.text, source_text, threshold) is not None
    value = _value(item)
    return value is None or contains_numbers(value, source_text, language)


def _required(item) -> tuple[str, ...]:
    """Quantities and parameters must appear verbatim (not just similarly) in the source text."""
    if isinstance(item, Material):
        values = (item.quantity, item.unit)
    elif isinstance(item, Parameter):
        values = (item.value, item.unit)
    else:
        return ()
    return tuple(v for v in values if v and v.strip())


def _result(status, method, reason=None, **rest) -> ItemVerification:
    return ItemVerification(status=status, method=method, reason=reason, **rest)


def _match_frame(item, source_text: str, sec: float, ocr_text: str, settings):
    """(matched text, frame second, numbers_ok) when this frame's text resembles the on-screen text."""
    if isinstance(item, ExactInput):
        found = exact_input_matches(source_text, ocr_text, settings.verify_input_threshold)
        return (found, sec, True) if found else None
    found, numbers_ok = _match_screen(source_text, ocr_text, settings.verify_text_threshold, _required(item))
    return (found, sec, numbers_ok) if found is not None else None


def verify_item(
    path: str, item, transcript: Transcript | None, ocr_texts: list[tuple[float, str]] | None, settings
) -> ItemVerification:
    """Check one grounded item (spec 3.3). `path` is only for the caller's bookkeeping."""
    if item.basis in ("inferred", "unclear"):
        return _result("unverified", "none", f"basis {item.basis}")
    spoken = item.basis == "stated"
    source_text = item.quote if spoken else item.on_screen_text
    if not (source_text or "").strip():
        return _result("not_checkable", "none", "chỉ có hành động, không có lời nói hay chữ để đối chiếu")
    language = transcript.language if spoken and transcript else None
    input_threshold = settings.verify_input_threshold
    if not _consistent(item, source_text, language, input_threshold):
        return _result("unverified", "none", NO_VALUE)
    method = "asr" if spoken else "ocr"
    if spoken and transcript is None:
        return _result("not_checked", method, "không có bản ghi lời nói")
    if not spoken and ocr_texts is None:
        return _result("not_checked", method, "không có kết quả OCR")
    pad = settings.verify_window_seconds
    wanted = ("audio", "both") if spoken else ("visual", "both")
    spans = [s for s in item.evidence_spans if s.source in wanted]
    if not spans:
        return _result("unverified", method, "không có khoảng bằng chứng phù hợp")
    checked = (
        max(0.0, min(s.start_sec for s in spans) - pad),
        max(s.end_sec for s in spans) + pad,
    )
    numbers_differ, frames = False, 0
    for s in spans:
        if spoken:
            words = _window_words(transcript, s.start_sec, s.end_sec, pad)
            hit = _match_speech(source_text, words, language, settings.verify_text_threshold, _required(item))
            hits = [hit] if hit else []
        else:
            low, high = max(0.0, s.start_sec - pad), s.end_sec + pad
            in_window = sorted((sec, text) for sec, text in ocr_texts if low <= sec <= high)
            frames += len(in_window)
            hits = [
                h for sec, text in in_window if (h := _match_frame(item, source_text, sec, text, settings))
            ]
        for matched, sec, numbers_ok in hits:
            if numbers_ok:
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
