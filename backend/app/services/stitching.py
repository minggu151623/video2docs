from copy import deepcopy
from difflib import SequenceMatcher


METADATA = {
    "local_id", "start_sec", "end_sec", "evidence_spans", "screenshot_candidates_sec",
    "needs_review", "review_reason",
}


def content(node):
    if isinstance(node, dict):
        return {k: content(v) for k, v in node.items() if k not in METADATA}
    if isinstance(node, list):
        return [content(v) for v in node]
    return node


def unique(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def merge_identical(left, right):
    """Keep every source span and frame; if the schema cannot hold them, keep both steps."""
    if content(left) != content(right):
        return None
    merged = deepcopy(left)

    def combine(target, extra):
        if isinstance(target, dict):
            if "evidence_spans" in target:
                spans = unique(target["evidence_spans"] + extra["evidence_spans"])
                if len(spans) > 5:
                    raise OverflowError
                target["evidence_spans"] = deepcopy(spans)
            for key in target:
                if key not in METADATA:
                    combine(target[key], extra[key])
        elif isinstance(target, list):
            for a, b in zip(target, extra):
                combine(a, b)

    try:
        combine(merged, right)
    except OverflowError:
        return None
    frames = unique(left["screenshot_candidates_sec"] + right["screenshot_candidates_sec"])
    reasons = unique([s["review_reason"] for s in (left, right) if s["review_reason"]])
    reason = "\n".join(reasons) or None
    if len(frames) > 2 or (reason and len(reason) > 2000):
        return None
    merged.update(
        start_sec=min(left["start_sec"], right["start_sec"]),
        end_sec=max(left["end_sec"], right["end_sec"]),
        screenshot_candidates_sec=frames,
        needs_review=left["needs_review"] or right["needs_review"],
        review_reason=reason,
    )
    return merged


def possible_repeat(left, right):
    def normalized(text):
        return " ".join(text.casefold().split())

    if normalized(left["title"]) == normalized(right["title"]):
        return True
    texts = [normalized(s["title"] + " " + " ".join(s["actions"])) for s in (left, right)]
    return SequenceMatcher(None, *texts).ratio() > 0.8


def append_step(steps, origins, step, chunk_index, language):
    for index, previous in enumerate(steps):
        if origins[previous["local_id"]] != chunk_index - 1:
            continue
        if max(previous["start_sec"], step["start_sec"]) >= min(previous["end_sec"], step["end_sec"]):
            continue
        merged = merge_identical(previous, step)
        if merged is not None:
            steps[index] = merged
            origins[merged["local_id"]] = chunk_index
            return
        if possible_repeat(previous, step):
            for current, other in ((previous, step), (step, previous)):
                note = (
                    f"Có thể trùng hoặc tiếp tục bước {other['local_id']} ở ranh giới đoạn; "
                    "giữ cả hai để kiểm tra chi tiết khác nhau."
                    if language == "vi" else
                    f"May repeat or continue step {other['local_id']} across clips; "
                    "both retained to review differing details."
                )
                old = current["review_reason"] or ""
                # Existing model concerns must remain intact even at the schema's length limit.
                if len(old) + len(note) + 1 <= 2000:
                    current["review_reason"] = "\n".join(filter(None, (old, note)))
                current["needs_review"] = True
    steps.append(step)
    origins[step["local_id"]] = chunk_index
