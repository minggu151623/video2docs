"""Score one generation against a hand-written annotation (see fixtures/eval/README.md).

    uv run python scripts/evaluate.py --generation-dir <dir> --annotation <json>
    uv run python scripts/evaluate.py --blocked-by-gate --annotation <json>

`<dir>` holds draft.json and, if the job got that far, verification.json. Metrics go to stdout as JSON.
The script reports; it never decides pass or fail, and it sends nothing anywhere."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from rapidfuzz import fuzz

from app.schemas.tutorial_v2 import load_draft
from app.schemas.verification import VerificationReport
from app.services.verification.matcher import iter_grounded_items, normalize
from app.services.verification.numbers import number_tokens

STEP_WINDOW_SEC = 10
TITLE_SCORE = 60
SCOPE = {"materials", "parameters", "warnings", "safety"}
EMPTY_REPORT = VerificationReport(items={}, asr_status="skipped", ocr_status="skipped")


def _ratio(a: str, b: str) -> float:
    return fuzz.token_set_ratio(normalize(a), normalize(b))


def _same_value(item_value, item_unit, truth_value, truth_unit, language) -> bool:
    """Numbers compare as whole tokens ('1/2' is not '1 2'); a unit is compared when the annotation has one."""
    ours, theirs = number_tokens(item_value or "", language), number_tokens(truth_value or "", language)
    if Counter(ours) != Counter(theirs):
        return False
    if not ours and normalize(item_value or "") != normalize(truth_value or ""):
        return False
    return not (truth_unit or "").strip() or normalize(item_unit or "") == normalize(truth_unit)


def match_steps(draft_steps, truth_steps) -> dict[int, int]:
    """Annotated step index -> draft step index. One draft step serves one annotated step."""
    used, matched = set(), {}
    for ti, truth in enumerate(truth_steps):
        best = None
        for di, step in enumerate(draft_steps):
            if di in used or abs(step.start_sec - truth["start_sec"]) > STEP_WINDOW_SEC:
                continue
            score = _ratio(step.title, truth["title"])
            if score >= TITLE_SCORE and (best is None or score > best[0]):
                best = (score, di)
        if best:
            used.add(best[1])
            matched[ti] = best[1]
    return matched


def _counterparts(collection, item, path, truth, steps, language):
    """(found, [annotation keys whose value the item matches]) for one in-scope item.

    `found` means the annotation has something of this name (or, for warnings, this wording)."""
    if collection == "materials":
        pool = [(("m", i), m) for i, m in enumerate(truth.get("materials", [])) if m.get("name")]
        named = [(k, m) for k, m in pool if normalize(m["name"]) == normalize(item.name)]
        right = [
            k
            for k, m in named
            if _same_value(item.quantity, item.unit, m.get("quantity"), m.get("unit"), language)
        ]
    elif collection == "parameters":
        si = int(path.split("/")[1])
        pool = [(("p", i), p) for i, p in enumerate(truth.get("parameters", []))]
        named = [
            (k, p)
            for k, p in pool
            if steps.get(p.get("step_index")) == si and normalize(p["name"]) == normalize(item.name)
        ]
        right = [
            k for k, p in named if _same_value(item.value, item.unit, p.get("value"), p.get("unit"), language)
        ]
    else:
        named = [
            (("w", i), w)
            for i, w in enumerate(truth.get("warnings", []))
            if _ratio(item.text, w) >= TITLE_SCORE
        ]
        right = [k for k, _ in named]
    return bool(named), right


def _ratio_or_none(num: int, den: int) -> float | None:
    return num / den if den else None


def evaluate(draft, report: VerificationReport | dict, truth: dict) -> dict:
    if not isinstance(report, VerificationReport):
        report = VerificationReport.model_validate(report)
    result = {
        "verified_precision": None,
        "wrong_verified_quantities": 0,
        "verified_false_negative_rate": None,
        "step_coverage": None,
        "not_tutorial_correct": draft.is_tutorial == truth["is_tutorial"],
    }
    truth_steps = truth.get("steps", [])
    matched = match_steps(draft.steps, truth_steps)
    result["step_coverage"] = _ratio_or_none(len(matched), len(truth_steps))

    verified_total = verified_correct = wrong = 0
    reached: dict[tuple, bool] = {}  # annotated quantity -> some matching draft item is verified
    for path, collection, item in iter_grounded_items(draft):
        if collection not in SCOPE:
            continue
        found, right = _counterparts(collection, item, path, truth, matched, draft.language)
        verified = path in report.items and report.items[path].status == "verified"
        for key in right:
            if key[0] != "w":
                reached[key] = reached.get(key, False) or verified
        if not verified:
            continue
        verified_total += 1
        verified_correct += bool(right)
        wrong += int(found and not right and collection in ("materials", "parameters"))
    result["verified_precision"] = _ratio_or_none(verified_correct, verified_total)
    result["wrong_verified_quantities"] = wrong
    expected = {("m", i) for i, m in enumerate(truth.get("materials", [])) if m.get("quantity")}
    expected |= {("p", i) for i in range(len(truth.get("parameters", [])))}
    present = [k for k in reached if k in expected]
    result["verified_false_negative_rate"] = _ratio_or_none(
        sum(not reached[k] for k in present), len(present)
    )
    result["counts"] = {
        "verified_items": verified_total,
        "verified_correct": verified_correct,
        "annotated_quantities": len(expected),
        "annotated_quantities_in_draft": len(present),
        "annotated_steps": len(truth_steps),
        "annotated_steps_matched": len(matched),
    }
    return result


def blocked_result(truth: dict) -> dict:
    """The job stopped at clip 1 and left no generation: only the gate decision can be scored."""
    return {
        "verified_precision": None,
        "wrong_verified_quantities": 0,
        "verified_false_negative_rate": None,
        "step_coverage": None,
        "not_tutorial_correct": truth["is_tutorial"] is False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--generation-dir", type=Path)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--blocked-by-gate", action="store_true", help="job ended as not_tutorial; no draft")
    args = parser.parse_args(argv)
    truth = json.loads(args.annotation.read_text())
    if args.blocked_by_gate:
        result = blocked_result(truth)
    else:
        if not args.generation_dir:
            parser.error("--generation-dir is required unless --blocked-by-gate is set")
        draft_file = args.generation_dir / "draft.json"
        if not draft_file.is_file():
            parser.error(f"{draft_file} not found")
        draft = load_draft(draft_file.read_bytes(), float("inf"))
        report_file = args.generation_dir / "verification.json"
        report = (
            VerificationReport.model_validate_json(report_file.read_bytes())
            if report_file.is_file()
            else EMPTY_REPORT
        )
        result = evaluate(draft, report, truth)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
