import importlib.util
import json
from pathlib import Path
import pytest
from app.schemas.tutorial_v2 import load_draft

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "evaluate.py"


def load_script():
    spec = importlib.util.spec_from_file_location("evaluate_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluate = load_script()


def span(start=0, end=10):
    return {"start_sec": start, "end_sec": end, "source": "both", "description": "Source"}


def material(name, quantity, unit="g"):
    return {
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "note": None,
        "evidence_spans": [span()],
        "basis": "stated",
        "quote": f"{quantity} {unit} {name}",
        "on_screen_text": None,
    }


def parameter(name, value, unit="°C"):
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "evidence_spans": [span()],
        "basis": "stated",
        "quote": f"{name} {value} {unit}",
        "on_screen_text": None,
    }


def warning(text):
    return {
        "text": text,
        "evidence_spans": [span()],
        "basis": "stated",
        "scope": "clip",
        "quote": text,
        "on_screen_text": None,
    }


def step(title, start, parameters=(), warnings=(), tips=(), exact_inputs=()):
    return {
        "local_id": f"s{start}",
        "title": title,
        "start_sec": start,
        "end_sec": start + 20,
        "actions": [title],
        "expected_result": None,
        "parameters": list(parameters),
        "exact_inputs": list(exact_inputs),
        "warnings": list(warnings),
        "tips": list(tips),
        "evidence_spans": [span(start, start + 20)],
        "screenshot_candidates_sec": [],
        "needs_review": False,
        "review_reason": None,
    }


def make_draft(materials=(), steps=(), is_tutorial=True, language="vi"):
    if is_tutorial and not steps:
        steps = [step("Chuẩn bị", 500)]
    return {
        "schema_version": "2.0",
        "is_tutorial": is_tutorial,
        "not_tutorial_reason": None if is_tutorial else "Vlog",
        "domain": "cooking",
        "yield": None,
        "title": "Bánh",
        "summary": "",
        "language": language,
        "objectives": [],
        "prerequisites": [],
        "safety": [],
        "materials": list(materials),
        "equipment": [],
        "steps": list(steps),
        "troubleshooting": [],
        "uncertainties": [],
    }


def make_report(**statuses):
    return {
        "items": {
            path: {"status": status, "method": "asr" if status == "verified" else "none"}
            for path, status in statuses.items()
        },
        "asr_status": "ok",
        "ocr_status": "skipped",
    }


def run(draft, report, truth):
    return evaluate.evaluate(load_draft(json.dumps(draft), float("inf")), report, truth)


def annotation(**rest):
    return {"is_tutorial": True, "steps": [], "materials": [], "parameters": [], "warnings": []} | rest


def test_two_correct_and_one_wrong_verified_quantity():
    draft = make_draft([material("Bột", "200"), material("Đường", "50"), material("Muối", "5")])
    report = make_report(**{"materials/0": "verified", "materials/1": "verified", "materials/2": "verified"})
    truth = annotation(
        materials=[
            {"name": "bột", "quantity": "200", "unit": "g"},
            {"name": "Đường", "quantity": "50", "unit": "g"},
            {"name": "Muối", "quantity": "3", "unit": "g"},
        ]
    )
    result = run(draft, report, truth)
    assert result["verified_precision"] == pytest.approx(2 / 3)
    assert result["wrong_verified_quantities"] == 1
    assert result["verified_false_negative_rate"] == 0.0


def test_not_tutorial_matches_annotation():
    draft = make_draft(is_tutorial=False)
    result = run(draft, make_report(), annotation(is_tutorial=False))
    assert result["not_tutorial_correct"] is True
    assert run(draft, make_report(), annotation())["not_tutorial_correct"] is False


def test_nothing_verified_has_no_precision():
    draft = make_draft([material("Bột", "200")])
    truth = annotation(materials=[{"name": "Bột", "quantity": "200", "unit": "g"}])
    result = run(draft, make_report(**{"materials/0": "unverified"}), truth)
    assert result["verified_precision"] is None
    assert result["wrong_verified_quantities"] == 0
    assert result["verified_false_negative_rate"] == 1.0


def test_fraction_is_not_two_numbers():
    draft = make_draft([material("Bơ", "1 2", "chén")])
    truth = annotation(materials=[{"name": "Bơ", "quantity": "1/2", "unit": "chén"}])
    result = run(draft, make_report(**{"materials/0": "verified"}), truth)
    assert result["wrong_verified_quantities"] == 1
    assert result["verified_precision"] == 0.0


def test_number_words_and_decimal_comma_match():
    draft = make_draft([material("Sữa", "hai trăm", "ml"), material("Bột", "1,5", "kg")])
    truth = annotation(
        materials=[
            {"name": "Sữa", "quantity": "200", "unit": "ml"},
            {"name": "Bột", "quantity": "1.5", "unit": "kg"},
        ]
    )
    result = run(draft, make_report(**{"materials/0": "verified", "materials/1": "verified"}), truth)
    assert result["wrong_verified_quantities"] == 0
    assert result["verified_precision"] == 1.0


def test_unit_mismatch_is_wrong():
    draft = make_draft([material("Sữa", "200", "g")])
    truth = annotation(materials=[{"name": "Sữa", "quantity": "200", "unit": "ml"}])
    result = run(draft, make_report(**{"materials/0": "verified"}), truth)
    assert result["wrong_verified_quantities"] == 1


def test_parameters_follow_the_matched_step():
    steps = [
        step("Nướng bánh", 100, [parameter("Nhiệt độ", "180")]),
        step("Để nguội", 200, [parameter("Nhiệt độ", "25")]),
    ]
    truth = annotation(
        steps=[{"title": "Nướng bánh", "start_sec": 100}, {"title": "Để nguội", "start_sec": 200}],
        parameters=[
            {"step_index": 0, "name": "Nhiệt độ", "value": "180", "unit": "°C"},
            {"step_index": 1, "name": "Nhiệt độ", "value": "30", "unit": "°C"},
        ],
    )
    report = make_report(**{"steps/0/parameters/0": "verified", "steps/1/parameters/0": "verified"})
    result = run(make_draft(steps=steps), report, truth)
    assert result["wrong_verified_quantities"] == 1
    assert result["verified_precision"] == 0.5
    assert result["step_coverage"] == 1.0


def test_false_negative_counts_correct_items_left_unverified():
    draft = make_draft([material("Bột", "200"), material("Đường", "50"), material("Muối", "3")])
    report = make_report(
        **{"materials/0": "verified", "materials/1": "unverified", "materials/2": "not_checked"}
    )
    truth = annotation(
        materials=[
            {"name": "Bột", "quantity": "200", "unit": "g"},
            {"name": "Đường", "quantity": "50", "unit": "g"},
            {"name": "Muối", "quantity": "3", "unit": "g"},
            {"name": "Trứng", "quantity": "2", "unit": None},
        ]
    )
    result = run(draft, report, truth)
    assert result["verified_false_negative_rate"] == pytest.approx(2 / 3)


def test_step_coverage_needs_time_and_title():
    steps = [
        step("Trộn bột với đường", 40),
        step("Nướng bánh trong lò", 300),
        step("Trang trí", 500),
    ]
    truth = annotation(
        steps=[
            {"title": "Trộn đường với bột", "start_sec": 48},  # within 10 s, same words
            {"title": "Nướng bánh trong lò", "start_sec": 330},  # right title, 30 s off
            {"title": "Phết kem", "start_sec": 500},  # right time, different title
            {"title": "Dọn dẹp", "start_sec": 900},  # missing
        ]
    )
    result = run(make_draft(steps=steps), make_report(), truth)
    assert result["step_coverage"] == 0.25


def test_one_draft_step_is_not_used_twice():
    steps = [step("Trộn bột", 10)]
    truth = annotation(steps=[{"title": "Trộn bột", "start_sec": 10}, {"title": "Trộn bột", "start_sec": 12}])
    assert run(make_draft(steps=steps), make_report(), truth)["step_coverage"] == 0.5


def test_warnings_are_matched_by_words():
    steps = [step("Nướng", 0, warnings=[warning("Cẩn thận, khay rất nóng"), warning("Đeo kính bảo hộ")])]
    truth = annotation(warnings=["Cẩn thận khay rất nóng"])
    report = make_report(**{"steps/0/warnings/0": "verified", "steps/0/warnings/1": "verified"})
    result = run(make_draft(steps=steps), report, truth)
    assert result["verified_precision"] == 0.5


def test_empty_annotation_gives_null_metrics():
    result = run(make_draft(), make_report(), annotation())
    assert result["verified_precision"] is None
    assert result["verified_false_negative_rate"] is None
    assert result["step_coverage"] is None
    assert result["wrong_verified_quantities"] == 0
    assert result["not_tutorial_correct"] is True


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_main_prints_json_and_exits_zero(tmp_path, capsys):
    gen = tmp_path / "gen"
    gen.mkdir()
    write(gen, "draft.json", make_draft([material("Bột", "200")]))
    write(gen, "verification.json", make_report(**{"materials/0": "verified"}))
    truth = write(
        tmp_path, "truth.json", annotation(materials=[{"name": "Bột", "quantity": "200", "unit": "g"}])
    )
    assert evaluate.main(["--generation-dir", str(gen), "--annotation", str(truth)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verified_precision"] == 1.0
    assert set(out) >= {
        "verified_precision",
        "wrong_verified_quantities",
        "verified_false_negative_rate",
        "step_coverage",
        "not_tutorial_correct",
    }


def test_main_without_verification_file_treats_everything_unverified(tmp_path, capsys):
    gen = tmp_path / "gen"
    gen.mkdir()
    write(gen, "draft.json", make_draft([material("Bột", "200")]))
    truth = write(
        tmp_path, "truth.json", annotation(materials=[{"name": "Bột", "quantity": "200", "unit": "g"}])
    )
    assert evaluate.main(["--generation-dir", str(gen), "--annotation", str(truth)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verified_precision"] is None
    assert out["verified_false_negative_rate"] == 1.0


def test_main_blocked_by_gate_needs_no_generation(tmp_path, capsys):
    truth = write(tmp_path, "truth.json", annotation(is_tutorial=False))
    assert evaluate.main(["--blocked-by-gate", "--annotation", str(truth)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["not_tutorial_correct"] is True
    assert out["verified_precision"] is None
    truth = write(tmp_path, "truth2.json", annotation(is_tutorial=True))
    evaluate.main(["--blocked-by-gate", "--annotation", str(truth)])
    assert json.loads(capsys.readouterr().out)["not_tutorial_correct"] is False


def test_main_rejects_missing_draft(tmp_path):
    truth = write(tmp_path, "truth.json", annotation())
    with pytest.raises(SystemExit):
        evaluate.main(["--generation-dir", str(tmp_path), "--annotation", str(truth)])


def command(text):
    return {
        "kind": "command",
        "language": "bash",
        "text": text,
        "completeness": "complete",
        "evidence_spans": [span()],
        "basis": "stated",
        "quote": text,
        "on_screen_text": None,
    }


def test_names_match_fuzzily_so_a_wrong_value_counts():
    draft = make_draft([material("Bột mì", "300")])
    truth = annotation(materials=[{"name": "Bột mì đa dụng", "quantity": "200", "unit": "g"}])
    result = run(draft, make_report(**{"materials/0": "verified"}), truth)
    assert result["wrong_verified_quantities"] == 1
    assert result["verified_unmatched"] == {"count": 0, "paths": []}


def test_verified_items_without_an_annotation_are_listed():
    steps = [step("Nướng", 0, [parameter("Nhiệt độ", "180")])]
    draft = make_draft([material("Muối", "5")], steps=steps)
    report = make_report(**{"materials/0": "verified", "steps/0/parameters/0": "verified"})
    result = run(draft, report, annotation(materials=[{"name": "Bột", "quantity": "200", "unit": "g"}]))
    assert result["verified_unmatched"] == {"count": 2, "paths": ["materials/0", "steps/0/parameters/0"]}
    assert result["verified_precision"] == 0.0


def test_numeric_claims_are_scored_against_annotated_claims():
    tips = [warning("Nấu 3 phút cho mềm"), warning("Nghỉ 10 phút"), warning("Khuấy đều tay")]
    draft = make_draft(steps=[step("Nấu", 0, tips=tips)])
    report = make_report(
        **{"steps/0/tips/0": "verified", "steps/0/tips/1": "verified", "steps/0/tips/2": "verified"}
    )
    truth = annotation(claims=[{"text": "Nấu 5 phút cho mềm", "numbers": ["5"]}])
    result = run(draft, report, truth)
    assert result["wrong_verified_quantities"] == 1
    assert result["verified_unmatched"] == {"count": 1, "paths": ["steps/0/tips/1"]}
    truth = annotation(claims=[{"text": "Nấu 3 phút cho mềm", "numbers": ["3"]}])
    result = run(draft, report, truth)
    assert result["wrong_verified_quantities"] == 0
    assert result["verified_precision"] == 0.5


def test_numeric_warnings_compare_their_numbers():
    draft = make_draft(steps=[step("Nướng", 0, warnings=[warning("Không để ngoài quá 2 giờ")])])
    truth = annotation(warnings=["Không để thức ăn ngoài quá 2 giờ"])
    result = run(draft, make_report(**{"steps/0/warnings/0": "verified"}), truth)
    assert result["verified_precision"] == 1.0
    truth = annotation(warnings=["Không để ngoài quá 3 giờ"])
    result = run(draft, make_report(**{"steps/0/warnings/0": "verified"}), truth)
    assert result["wrong_verified_quantities"] == 1


def test_exact_inputs_are_scored_against_annotated_inputs():
    inputs = [command("npm run build"), command("npm install foo"), command("ls")]
    draft = make_draft(steps=[step("Build", 0, exact_inputs=inputs)])
    report = make_report(**{f"steps/0/exact_inputs/{i}": "verified" for i in range(3)})
    truth = annotation(exact_inputs=["npm  run build", "npm install bar"])
    result = run(draft, report, truth)
    assert result["wrong_verified_exact_inputs"] == 1
    assert result["verified_unmatched"] == {"count": 1, "paths": ["steps/0/exact_inputs/2"]}
    assert result["verified_precision"] == pytest.approx(1 / 3)


def test_quote_matched_is_not_verified_and_is_counted():
    """Ruling P2: a claim whose quote matched but whose paraphrase was not checked is not verified."""
    steps = [step("Nướng", 0, warnings=[warning("Cẩn thận, khay rất nóng"), warning("Đeo kính bảo hộ")])]
    truth = annotation(warnings=["Cẩn thận khay rất nóng"])
    report = make_report(**{"steps/0/warnings/0": "verified", "steps/0/warnings/1": "quote_matched"})
    result = run(make_draft(steps=steps), report, truth)
    assert result["verified_precision"] == 1.0
    assert result["verified_unmatched"]["count"] == 0
    assert result["counts"]["verified_items"] == 1
    assert result["quote_matched"] == {"count": 1, "paths": ["steps/0/warnings/1"]}
    only = run(make_draft(steps=steps), make_report(**{"steps/0/warnings/0": "quote_matched"}), truth)
    assert only["verified_precision"] is None and only["quote_matched"]["count"] == 1
    assert evaluate.blocked_result(truth)["quote_matched"] == {"count": 0, "paths": []}
