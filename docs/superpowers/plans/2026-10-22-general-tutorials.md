# Tutorial mọi lĩnh vực có kiểm chứng độc lập — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Video2docs tạo tài liệu làm-theo-được cho video how-to ở mọi lĩnh vực, chặn video không phải tutorial, và gắn trạng thái kiểm chứng ASR/OCR cho từng định lượng, thông số, lệnh và cảnh báo.

**Architecture:** Schema v2 (Pydantic) thay v1 cho job mới; v1 được nâng cấp khi đọc. Gemini trả `domain`/`is_tutorial` trong cùng lần gọi; đoạn 1 có thể dừng job với trạng thái `not_tutorial`. Gói `app/services/verification/` chạy ASR (faster-whisper) trước phân tích, OCR có chọn lọc sau khi ghép, rồi khớp thuần thuật toán và ghi `verification.json` tách khỏi draft. Renderer mới đặt tên mục theo lĩnh vực và in huy hiệu kiểm chứng.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy/Alembic (SQLite), google-genai Interactions, FFmpeg, faster-whisper, rapidfuzz, OCR engine chọn ở Task 1, React + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-10-22-general-tutorials-design.md`

## Global Constraints

- Repo chưa có commit nào. Trước Task 1, hỏi người dùng rồi mới tạo commit baseline của toàn bộ trạng thái hiện tại; mọi bước "Commit" trong plan cũng chỉ chạy khi người dùng đã đồng ý commit trong phiên thực thi.
- Lệnh test: `uv run pytest -q`; lint: `uv run ruff check --select F backend scripts tests/e2e` và `uv run ruff format --check backend`; line length 110.
- Contract timestamp với Gemini giữ `MM:SS` (contract v8, `app/providers/timecodes.py`); Pydantic và mọi thứ sau adapter dùng giây float.
- `domain` ∈ `software, cooking, repair, craft, fitness, beauty, gardening, music, other`.
- Giới hạn: `materials` ≤ 60, `equipment` ≤ 30, `parameters` ≤ 10/bước, `warnings` ≤ 5/bước, `tips` ≤ 5/bước; giới hạn v1 khác giữ nguyên (80 bước, 40 ảnh, tối đa 1 repair/job).
- Trạng thái kiểm chứng: `verified`, `unverified`, `not_checkable`, `not_checked`; method: `asr`, `ocr`, `none`.
- Khớp: cửa sổ ± 5 giây quanh khoảng bằng chứng; chữ ngưỡng 85/100; `exact_inputs` ngưỡng 95/100 chỉ bỏ khác biệt khoảng trắng; con số khớp chính xác; tối đa 3 frame OCR/mục (đầu, giữa, cuối khoảng bằng chứng).
- ASR/OCR chạy trên server, không gửi dữ liệu người dùng ra ngoài. Bản ghi lời nói không được đưa vào prompt Gemini.
- Lỗi ASR/OCR không bao giờ chặn việc tạo tài liệu; mục liên quan thành `not_checked`, generation `needs_review`.
- Huy hiệu (vi): `✓ khớp lời nói [mốc]`, `✓ khớp chữ trên màn hình [mốc]`, `? chưa kiểm chứng`, `không có văn bản để đối chiếu`. Bản en: `✓ matches speech [t]`, `✓ matches on-screen text [t]`, `? not verified`, `no text to check against`.
- Mọi request Gemini thật (probe, live, bộ đánh giá) cần người dùng đồng ý và chấp nhận phí trước khi chạy.

## Review Focus

- Video không có track âm thanh (`Asset.has_audio = 0`): ASR bị bỏ qua, mục `stated` thành `not_checked`, tài liệu vẫn tạo — test ở Task 9.
- Video ngôn ngữ không phải Latin (tiếng Hàn): `quote` tiếng Hàn khớp được với transcript tiếng Hàn, chuẩn hóa không làm mất ký tự — test ở Task 6.
- Định lượng dạng phân số, khoảng, dấu thập phân kiểu Việt ("1/2", "2-3", "1,5"): so khớp theo dãy chữ số, không phụ thuộc locale — test ở Task 6.
- Video ngắn chỉ một đoạn mà không phải tutorial: vẫn bị chặn và dừng sau đúng một request — test ở Task 5.
- Chạy lại kiểm chứng trên generation v1 cũ: nâng cấp khi đọc, không lỗi, báo cáo rỗng — test ở Task 9.

---

### Task 1: Spike chọn OCR engine

Throwaway; chỉ giữ lại quyết định.

**Files:**
- Create: `tmp/ocr-spike/run.py` (không commit)
- Modify: `docs/decisions.md` (thêm mục "OCR engine")

**Interfaces:**
- Produces: tên engine và gói phụ thuộc mà Task 7 cài; ghi trong `docs/decisions.md`.

- [ ] **Step 1:** Gom khoảng 20 frame mẫu vào `tmp/ocr-spike/frames/` kèm `truth.json` (chữ đúng của từng frame): terminal/IDE (lấy từ `video_test/HowtoinstallPythonWindows11.mp4` các giây 151, 180, 85), chữ chèn trên video nấu ăn, nhãn bao bì, tiếng Việt có dấu, ít nhất một ngôn ngữ châu Á. Frame ngoài video thử phải là nguồn người dùng cung cấp hoặc tự chụp; không tải nội dung chưa rõ quyền.
- [ ] **Step 2:** Cài thử Tesseract (`brew install tesseract tesseract-lang`, `pytesseract`) và PaddleOCR (`paddleocr`, `paddlepaddle`) vào một venv riêng trong `tmp/ocr-spike/`, không đụng `uv.lock`.
- [ ] **Step 3:** `run.py` đo cho từng engine: tỉ lệ ký tự đúng (1 − CER) trên mỗi nhóm frame, thời gian/frame trên CPU, dung lượng cài đặt.
- [ ] **Step 4:** Ghi bảng kết quả và lựa chọn vào `docs/decisions.md`. Tiêu chí ưu tiên: độ chính xác nhóm terminal và tiếng Việt, rồi thời gian, rồi dung lượng.
- [ ] **Step 5:** Commit `docs/decisions.md` (`docs: choose OCR engine`).

### Task 2: Schema v2 và nâng cấp v1

**Files:**
- Create: `backend/app/schemas/tutorial_v2.py`
- Modify: `backend/app/providers/mock.py`, `scripts/generate_schema.py`, `frontend/src/types/tutorial.schema.json`, `frontend/src/types/tutorial.d.ts` (sinh lại)
- Test: `backend/tests/unit/test_schema_v2.py`

**Interfaces:**
- Consumes: `Strict`, `Span`, `Spans`, `Short`, `Seconds`, `Uncertainty`, `TutorialDraftV1` từ `app/schemas/tutorial.py` (giữ nguyên file đó).
- Produces:
  - `Domain = Literal[...]` (9 giá trị), `Basis = Literal["observed","stated","inferred","unclear"]`.
  - `GroundedClaim(Strict)`: `text`, `evidence_spans`, `basis`, `scope` (như `SourceClaim`) + `quote: str | None` (≤ 1000), `on_screen_text: str | None` (≤ 2000).
  - `Material`: `name` (≤ 200), `quantity: str | None` (≤ 100), `unit: str | None` (≤ 40), `note: str | None` (≤ 500), `evidence_spans`, `basis`, `quote`, `on_screen_text`.
  - `Equipment`: `name` (≤ 100), `spec: str | None` (≤ 100), `evidence_spans`.
  - `Parameter`: `name` (≤ 100), `value` (1–100), `unit: str | None` (≤ 40), `evidence_spans`, `basis`, `quote`, `on_screen_text`.
  - `ExactInput`: `kind: Literal["code","command","text"]`, `language: str | None` (≤ 40), `text` (1–12000), `completeness`, `evidence_spans`, `basis`, `quote`, `on_screen_text`.
  - `StepV2`: các trường của `Step` v1 trừ `commands`, thêm `parameters`, `exact_inputs`, `warnings: list[GroundedClaim]`, `tips: list[GroundedClaim]`. Giữ validator v1 (timeline, ảnh trong bước, `needs_review` khi `exact_inputs` không `complete`).
  - `TutorialDraftV2`: `schema_version: Literal["2.0"]`, `is_tutorial: bool`, `not_tutorial_reason: str | None` (≤ 1000), `domain: Domain`, `yield_: str | None = Field(alias="yield")` (≤ 200; `populate_by_name=True`, dump `by_alias=True`), `title`, `summary`, `language`, `objectives`, `prerequisites: list[GroundedClaim]`, `safety: list[GroundedClaim]`, `materials`, `equipment`, `steps: list[StepV2]`, `troubleshooting: list[GroundedClaim]`, `uncertainties`.
  - `upgrade_v1(data: dict) -> dict` và `load_draft(raw: str | bytes, duration: float) -> TutorialDraftV2`.

- [ ] **Step 1: Viết test thất bại** trong `test_schema_v2.py`:

```python
def test_stated_claim_requires_quote(): ...          # basis="stated", quote=None -> ValidationError "quote"
def test_observed_value_requires_on_screen_text():   # Parameter/Material(quantity!=None)/ExactInput basis="observed", on_screen_text=None -> ValidationError
def test_observed_action_claim_needs_no_text():      # GroundedClaim basis="observed", quote=None, on_screen_text=None -> ok
def test_not_tutorial_requires_reason_and_no_steps():
    # is_tutorial=False & not_tutorial_reason=None -> error; is_tutorial=False & steps non-empty -> error
def test_yield_round_trips_by_alias():               # model_dump(by_alias=True)["yield"] == "4 người ăn"
def test_limits():                                   # 61 materials -> error; 11 parameters in a step -> error
def test_load_draft_upgrades_v1():
    v1 = <MockProvider v1 JSON hiện tại, có 1 command và tool {"name":"Python","version":"3.13.0"}>
    draft = load_draft(v1, duration=10)
    assert draft.schema_version == "2.0" and draft.domain == "software" and draft.is_tutorial
    assert draft.equipment[0].spec == "3.13.0"
    assert draft.steps[0].exact_inputs[0].kind == "command"
    assert draft.materials == [] and draft.safety == []
```

  Claim v1 khi nâng cấp: `quote`/`on_screen_text` = null; nếu `basis` là `stated`/`observed` mà thiếu nguyên văn theo luật mới thì hạ xuống `unclear` để không vỡ validation (claim v1 chưa từng được kiểm chứng). Command v1 nâng cấp thành `basis="unclear"`.

- [ ] **Step 2:** Run `uv run pytest backend/tests/unit/test_schema_v2.py -q` — Expected: FAIL (module chưa có).
- [ ] **Step 3:** Implement `tutorial_v2.py` với các model, validator và `upgrade_v1`/`load_draft` ở trên. `load_draft` đọc JSON, nếu `schema_version == "1.0"` thì `upgrade_v1`, rồi `TutorialDraftV2.model_validate(..., context={"duration": duration})`.
- [ ] **Step 4:** Chuyển `MockProvider.analyze` sang trả v2 (`domain="other"`, `is_tutorial=True`, các danh sách mới rỗng). `scripts/generate_schema.py` dùng `TutorialDraftV2`; chạy `uv run python scripts/generate_schema.py && npm --prefix frontend run types`.
- [ ] **Step 5:** Run `uv run pytest -q` — Expected: test mới PASS. Test cũ dùng `TutorialDraftV1.model_validate_json(MockProvider…)` sẽ fail: đổi chúng sang `load_draft` hoặc `TutorialDraftV2`; không đổi assertion nghiệp vụ. Runner/documents chưa đổi nên integration có thể fail — chấp nhận tạm, ghi rõ trong commit message, Task 3–4 sửa tiếp. Nếu reviewer yêu cầu cây xanh mỗi commit, gộp Task 2–4 vào một commit.
- [ ] **Step 6:** Commit (`feat: tutorial schema v2 with v1 upgrade`).

### Task 3: Provider schema, prompt v2 và contract v9

**Files:**
- Create: `backend/app/prompts/tutorial_v2.txt`
- Modify: `backend/app/providers/structured_schema.py`, `backend/app/providers/gemini.py` (hằng `PROMPT`), `backend/app/services/analysis.py` (`clip_metadata`), `backend/app/api/routes.py` (snapshot `schema_version`), `backend/app/db/models.py` (default `schema_version="2.0"`, `prompt_version="tutorial_v2"`)
- Create: `tmp/live-test/schema_v2_probe.py` (không commit)
- Test: `backend/tests/unit/test_gemini_adapter.py`, `backend/tests/unit/test_quality.py`

**Interfaces:**
- Consumes: `TutorialDraftV2` (Task 2); `FIELDS`, `format_timecode` (contract v8).
- Produces: `tutorial_provider_schema()` sinh từ `TutorialDraftV2` (alias `yield` xuất hiện trong schema provider); tách `analysis_contract() -> dict` khỏi `analysis_contract_hash()` (hash = sha256 của `json.dumps(analysis_contract(), sort_keys=True)`), với `"adapter": "interactions-static-v9"`; `clip_metadata(original_name, index, chunks, video_duration, previous_parts) -> dict` thêm khóa `"domain"` (domain của đoạn 1, `None` cho đoạn 1).

- [ ] **Step 1: Test thất bại:**

```python
def test_provider_schema_v2_has_new_fields_and_no_sec_suffix():
    s = video_provider_schema(120)
    step = s["properties"]["steps"]["items"]["properties"]
    assert {"parameters", "exact_inputs", "warnings", "tips"} <= step.keys() and "commands" not in step
    assert s["properties"]["domain"]["enum"][-1] == "other" and "yield" in s["properties"]
    assert "_sec" not in json.dumps(s)

def test_contract_is_v9(): assert analysis_contract()["adapter"] == "interactions-static-v9"

def test_later_clips_receive_first_clip_domain(draft_v2):
    meta = clip_metadata("x.mp4", 1, [NS(start_sec=0), NS(start_sec=115)], 216, [(0, draft_v2_with_domain_cooking)])
    assert meta["domain"] == "cooking"
```

- [ ] **Step 2:** Run test — Expected FAIL.
- [ ] **Step 3:** Viết `tutorial_v2.txt`: bắt đầu từ `tutorial_v1.txt` hiện tại (giữ toàn bộ quy tắc chống bịa, `MM:SS`, scope theo đoạn, repair), đổi "video hướng dẫn phần mềm" thành "video hướng dẫn thực hành (how-to) ở mọi lĩnh vực", và thêm đúng các khối sau của spec mục 2.3 và 4.1: quy tắc `quote`/`on_screen_text` theo `basis` (quote giữ ngôn ngữ gốc, diễn giải theo output_language); `is_tutorial`/`not_tutorial_reason` (vlog, review, quảng cáo, bài giảng không có bước làm theo → `false`, `steps=[]`); khối gợi ý lĩnh vực (nấu ăn, sửa chữa, thể thao, làm đẹp, phần mềm) với câu "chỉ ghi khi video thể hiện, không suy đoán"; che secret, mật khẩu, địa chỉ, số điện thoại, giấy tờ tùy thân; metadata `domain` là ngữ cảnh từ đoạn đầu, không phải bằng chứng. Đổi `PROMPT` sang file v2. `structured_schema` sinh từ `TutorialDraftV2`, bump adapter v9, cập nhật các chuỗi `claim_policy`/`timestamp_policy` cho v2.
- [ ] **Step 4:** Run `uv run pytest -q` — Expected: PASS phần unit adapter/schema.
- [ ] **Step 5 (cần người dùng đồng ý phí):** `schema_v2_probe.py` gửi 3 request chỉ có text với `video_provider_schema(101.642)` và `system_instruction` v2 (như `schema_probe.py` lần chẩn đoán 503). Expected: 3/3 `completed`, output parse được bằng `to_seconds` + `TutorialDraftV2`. HTTP 400 → rút gọn mô tả schema (bỏ description dài, giữ enum/required), probe lại; không nới validation Pydantic.
- [ ] **Step 6:** Commit (`feat: provider contract v9 and how-to prompt v2`).

### Task 4: Ghép đoạn v2

**Files:**
- Modify: `backend/app/services/documents.py` (`assemble`, `has_review_claims`)
- Test: `backend/tests/unit/test_quality.py`

**Interfaces:**
- Consumes: `TutorialDraftV2`.
- Produces: `assemble(parts: list[tuple[float, TutorialDraftV2]], duration: float, max_steps: int = 80) -> TutorialDraftV2`; `has_review_claims(draft: TutorialDraftV2) -> bool` (xét `prerequisites`, `safety`, `troubleshooting`, `materials`, và `warnings`/`tips`/`parameters` của mọi bước).

- [ ] **Step 1: Test thất bại:**

```python
def test_assemble_takes_domain_and_gate_from_first_clip():  # đoạn 1 cooking/is_tutorial=True, đoạn 2 other -> merged.domain == "cooking", is_tutorial True
def test_materials_merge_by_name_and_quantity():             # "Bột mì" 200 g ở hai đoạn -> 1 mục, evidence nối (≤5); "Bột mì" 100 g -> 2 mục
def test_safety_from_later_clip_is_clip_scoped():            # như prerequisites hiện tại
def test_inferred_parameter_marks_review():                  # basis="inferred" trong step.parameters -> has_review_claims True
def test_yield_first_non_null_wins():
```

- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Mở rộng `assemble`: `domain`, `is_tutorial`, `not_tutorial_reason`, `yield` lấy từ đoạn đầu (yield: giá trị khác null đầu tiên); `safety` xử lý như `prerequisites` (scope `clip` từ đoạn 2); `materials` gộp theo khóa `(name.casefold().strip(), (quantity or "").strip(), (unit or "").casefold().strip())`; `equipment` gộp như `tools` hiện tại với `spec` thay `version`; dịch thời gian và đổi `local_id` như hiện có; `shift` cũng phải dịch spans bên trong `parameters`/`exact_inputs`/`warnings`/`tips` (nó đệ quy theo khóa nên chỉ cần test xác nhận).
- [ ] **Step 4:** Run `uv run pytest -q` — Expected PASS (trừ phần render, Task 8).
- [ ] **Step 5:** Commit (`feat: assemble schema v2 drafts`).

### Task 5: Chặn video không phải tutorial

**Files:**
- Modify: `backend/app/workers/runner.py` (`analyze`, `execute`), `backend/app/api/routes.py` (`AnalyzeInput`, `retry`)
- Test: `backend/tests/integration/test_workflow.py`

**Interfaces:**
- Consumes: `TutorialDraftV2.is_tutorial`, `not_tutorial_reason`.
- Produces: `AnalyzeInput.skip_tutorial_gate: bool = False` (lưu trong snapshot); job state/phase `not_tutorial`; warning `{"code": "NOT_TUTORIAL", "reason": <str>}`; `Worker.analyze` trả `"not_tutorial"` và `execute` ghi nguyên giá trị đó làm `state`/`phase`.

- [ ] **Step 1: Test thất bại** (mock trả `is_tutorial=False`, `steps=[]`, `not_tutorial_reason="Vlog"`):

```python
def test_not_tutorial_stops_after_first_clip(env, clip, monkeypatch):
    # clip fixture tạo >= 2 đoạn với cấu hình test hiện tại
    detail = <job sau worker.once()>
    assert detail["state"] == "not_tutorial" and len(detail["provider_calls"]) == 1
    assert {"code": "NOT_TUTORIAL", "reason": "Vlog"} in detail["warnings"]
    assert client.get(f"/api/v1/projects/{pid}/document").status_code == 404  # không tạo tài liệu

def test_single_clip_video_is_also_gated(env, clip, monkeypatch):  # cfg.chunk_seconds lớn hơn duration -> 1 đoạn, vẫn not_tutorial, 1 request

def test_later_clip_not_tutorial_is_only_recorded(env, clip, monkeypatch):
    # đoạn 1 is_tutorial=True, đoạn 2 False -> needs_review/succeeded, warning {"code": "LATER_CLIP_NOT_TUTORIAL", "clip_index": 2}

def test_skip_gate_analyzes_all_clips(env, clip, monkeypatch):
    # enqueue với skip_tutorial_gate=True -> state needs_review, provider_calls == số đoạn, có tài liệu
```

- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Trong `analyze`, ngay sau khi đoạn `index == 0` validate và lưu checkpoint: nếu `not draft.is_tutorial and not snapshot.get("skip_tutorial_gate")` thì cleanup remote, ghi warning, trả `"not_tutorial"`. Đoạn `index > 0` trả `is_tutorial = false` chỉ thêm warning `{"code": "LATER_CLIP_NOT_TUTORIAL", "clip_index": index + 1}` và chạy tiếp. `retry` giữ nguyên danh sách state cho phép (không thêm `not_tutorial`); nút "Vẫn phân tích toàn bộ" dùng `POST /projects/{id}/jobs` mới với `skip_tutorial_gate=True` và consent hiện có. `not_tutorial` không nằm trong danh sách state của partial unique index active-job, nên không chặn job mới.
- [ ] **Step 4:** Run `uv run pytest -q` — PASS.
- [ ] **Step 5:** Commit (`feat: stop non-tutorial videos after first clip`).

### Task 6: Bộ khớp kiểm chứng (thuần thuật toán)

**Files:**
- Create: `backend/app/schemas/verification.py`, `backend/app/services/verification/__init__.py`, `backend/app/services/verification/numbers.py`, `backend/app/services/verification/matcher.py`
- Modify: `pyproject.toml`, `uv.lock` (`rapidfuzz`)
- Test: `backend/tests/unit/test_matcher.py`

**Interfaces:**
- Produces:
  - `schemas/verification.py`: `Word(start: float, end: float, text: str)`, `Transcript(language: str | None, words: list[Word])`, `ItemVerification(status, method, matched_text: str | None, matched_sec: float | None, checked_range: tuple[float, float] | None, reason: str | None)` (`matched_sec`: giây bắt đầu của từ khớp đầu tiên trong transcript, hoặc giây của frame OCR khớp), `VerificationReport(items: dict[str, ItemVerification], asr_status: Literal["ok","skipped","failed"], ocr_status: Literal["ok","skipped","failed"])`.
  - `numbers.py`: `digit_runs(text: str, language: str | None) -> list[str]` — chuyển số đọc bằng chữ vi/en sang chữ số, rồi trả các dãy chữ số liên tiếp, bỏ số 0 đứng đầu ("1,5" → `["1","5"]`, "một trăm tám mươi" → `["180"]`, "1/2" → `["1","2"]`).
  - `matcher.py`: `normalize(text: str) -> str` (NFKC, casefold, gộp khoảng trắng, giữ dấu và mọi chữ viết); `transcript_window(t: Transcript, start: float, end: float, pad: float) -> str`; `contains_numbers(needle: str, haystack: str, language) -> bool` (mọi `digit_runs` của needle có trong haystack, tính bội số); `fuzzy_contains(needle, haystack, threshold: int) -> str | None` (rapidfuzz `fuzz.partial_ratio_alignment`, trả đoạn khớp hoặc None); `exact_input_matches(text, ocr_text, threshold=95) -> str | None` (so sau khi bỏ mọi khoảng trắng).
  - `matcher.verify_item(path: str, item, transcript: Transcript | None, ocr_texts: list[tuple[float, str]] | None, settings) -> ItemVerification` với luật của spec mục 3.3: inferred/unclear → `unverified` reason `"basis {basis}"`; nhất quán nội bộ (giá trị số của `quantity`/`value`/`text` phải nằm trong `quote` hoặc `on_screen_text`) → nếu sai `unverified` reason `"giá trị không có trong nguyên văn"`; `stated` → khớp `quote` với cửa sổ transcript (method `asr`; transcript None → `not_checked`); `observed` có `on_screen_text` → khớp với OCR (method `ocr`; OCR None → `not_checked`); `observed` không có text → `not_checkable`, method `none`. `checked_range` = khoảng bằng chứng hợp nhất ± pad.

- [ ] **Step 1: Test thất bại** (`test_matcher.py`):

```python
@pytest.mark.parametrize("text,lang,expected", [
    ("1,5 kg", "vi", ["1", "5"]), ("1/2 chén", "vi", ["1", "2"]), ("2-3 phút", "vi", ["2", "3"]),
    ("một trăm tám mươi độ", "vi", ["180"]), ("hai mươi lăm", "vi", ["25"]),
    ("one hundred eighty degrees", "en", ["180"]), ("180°C", None, ["180"]),
])
def test_digit_runs(text, lang, expected): assert digit_runs(text, lang) == expected

def test_korean_quote_matches_korean_transcript():   # transcript "설탕 두 큰술 넣어주세요" quote "설탕 두 큰술" -> verified asr
def test_number_mismatch_never_verifies():           # quote "200 gram bột", transcript "hai trăm năm mươi gram bột" -> unverified
def test_value_missing_from_own_quote():             # Material quantity "200", quote "một chén bột" -> unverified, reason "giá trị không có trong nguyên văn"
def test_quote_outside_window_is_unverified():       # từ khớp ở giây 40, bằng chứng 10-12 -> unverified
def test_exact_input_ignores_whitespace_only():      # "python --version" vs OCR "python  --version" -> verified; "python --versoin" -> unverified
def test_missing_sources_are_not_checked():           # transcript None với stated -> not_checked; ocr None với observed text -> not_checked
def test_action_only_is_not_checkable():
def test_vietnamese_diacritics_are_significant():    # quote "bột mì" vs transcript "bot mi" -> dưới ngưỡng -> unverified
```

- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** `uv add rapidfuzz`; implement theo Interfaces. Bảng số đọc bằng chữ vi (không, một/mốt, hai, ba, bốn/tư, năm/lăm, sáu, bảy, tám, chín, mười/mươi, trăm, nghìn/ngàn, linh/lẻ) và en (zero…nineteen, tens, hundred, thousand); chỉ ghép dãy từ số liên tiếp.
- [ ] **Step 4:** Run `uv run pytest backend/tests/unit/test_matcher.py -q` — PASS.
- [ ] **Step 5:** Commit (`feat: deterministic verification matcher`).

### Task 7: Adapter ASR/OCR và trích audio

**Files:**
- Create: `backend/app/services/verification/asr.py`, `backend/app/services/verification/ocr.py`
- Modify: `backend/app/services/media.py` (`extract_audio`), `backend/app/core/config.py`, `.env.example`, `pyproject.toml`, `uv.lock`
- Test: `backend/tests/unit/test_verification_adapters.py`

**Interfaces:**
- Consumes: `Transcript`, `Word` (Task 6); `run_process` trong `media.py`; engine OCR từ Task 1.
- Produces:
  - `Settings`: `asr_engine: Literal["faster-whisper","none"] = "faster-whisper"`, `asr_model: str = "small"`, `asr_timeout_seconds: int = 1200`, `ocr_engine: Literal["<engine Task 1>","none"]`, `ocr_timeout_seconds: int = 300`, `verify_window_seconds: float = 5`, `verify_text_threshold: int = 85`, `verify_input_threshold: int = 95`, `verify_max_ocr_frames: int = 3`. Tất cả nằm trong `snapshot()` (đổi cấu hình → retry cũ bị từ chối như hiện tại).
  - `media.extract_audio(source: Path, target: Path, check_cancel) -> None` (ffmpeg → WAV 16 kHz mono, timeout `asr_timeout_seconds`).
  - `asr.get_asr(settings) -> ASR | None` (None khi `asr_engine="none"`); `ASR.transcribe(audio: Path, check_cancel) -> Transcript` (faster-whisper `WhisperModel(settings.asr_model, device="auto", compute_type="int8")`, `word_timestamps=True`, `vad_filter=True`). Generator segment được duyệt từng phần: mỗi segment gọi `check_cancel()` và raise `AppError("ASR_TIMEOUT", ...)` khi vượt `asr_timeout_seconds`.
  - `ocr.get_ocr(settings) -> OCR | None`; `OCR.read(image: Path) -> str`.

- [ ] **Step 1: Test thất bại:** `get_asr(Settings(asr_engine="none")) is None`; `get_ocr(Settings(ocr_engine="none")) is None`; `extract_audio` trên `fixtures/synthetic_tutorial.mp4` tạo WAV 16000 Hz 1 kênh (đọc header bằng `wave`); `asr_engine` không hợp lệ → `ValidationError`; ASR giả có generator segment chậm với `asr_timeout_seconds=1` → `AppError` mã `ASR_TIMEOUT`. Không test model thật trong suite mặc định; thêm test đánh dấu `@pytest.mark.slow` chạy faster-whisper `tiny` trên một WAV TTS ngắn tự tạo bằng `say` (macOS) nếu có, skip nếu không.
- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** `uv add faster-whisper` và gói OCR theo Task 1; implement. Ghi vào `.env.example` các biến mới với giá trị mặc định. README ghi chú: lần đầu chạy, faster-whisper tải trọng số model từ Hugging Face (chỉ tải model, không gửi dữ liệu người dùng).
- [ ] **Step 4:** Run `uv run pytest -q` — PASS.
- [ ] **Step 5:** Commit (`feat: local ASR and OCR adapters`).

### Task 8: Renderer v2

**Files:**
- Create: `backend/app/services/rendering.py` (chuyển `render_markdown`, `stamp`, `escape` từ `documents.py`; `documents.py` re-export `render_markdown` để import cũ còn chạy)
- Test: `backend/tests/unit/test_rendering.py`

**Interfaces:**
- Consumes: `TutorialDraftV2`, `VerificationReport`, `ItemVerification`.
- Produces: `render_markdown(draft: TutorialDraftV2, asset, model: str, generation, evidence: dict, verification: VerificationReport | None = None) -> str`; `SECTION_LABELS: dict[str, dict[str, tuple[str, str]]]` (domain → language → (nhãn materials, nhãn equipment)) đúng bảng spec mục 4.3 kèm bản en (cooking: Ingredients/Utensils; repair, craft, gardening: Materials/Tools; beauty: Products/Tools; fitness: Materials/Equipment; software: Resources/Required software; music, other: Materials/Tools).

- [ ] **Step 1: Test thất bại:**

```python
def test_cooking_labels_and_section_order(): # headings theo thứ tự: Mục tiêu, Chuẩn bị, An toàn, Nguyên liệu, Dụng cụ, (Ngữ cảnh theo đoạn), Các bước, Lỗi và cách xử lý, Điểm chưa rõ, Thông tin nguồn
def test_empty_new_sections_are_hidden():     # không materials/safety -> không có heading "Nguyên liệu"/"An toàn"; "Lỗi và cách xử lý" vẫn in "Không được nêu trong video."
def test_parameter_line_and_badges():
    # parameter verified asr tại 135 -> "Nhiệt độ: 180 °C · ✓ khớp lời nói [00:02:15](#t=135.000)"
    # unverified -> "? chưa kiểm chứng" và mục xuất hiện lại trong "## Điểm chưa rõ"
def test_inferred_material_only_in_review(): # basis inferred không có trong "## Nguyên liệu"
def test_without_verification_no_badges():   # verification=None -> không có "✓" hoặc "?" huy hiệu
def test_exact_input_renders_fenced_block(): # như commands v1 (fence dài hơn backtick trong text)
def test_english_badges():                    # language en -> "✓ matches speech"
def test_yield_line():                         # "Khẩu phần: 4 người ăn" ngay dưới tóm tắt (en "Yield:")
```

- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Implement. Thứ tự trong bước: thao tác, thông số, `exact_inputs`, cảnh báo (tiền tố "Cảnh báo:"/"Warning:"), mẹo ("Mẹo:"/"Tip:"), kết quả, bằng chứng, ảnh. Huy hiệu tra theo đường dẫn mục (`materials/0`, `steps/3/parameters/0`…, đúng định dạng Task 6). Mốc của huy hiệu `verified` là `matched_sec`. Mục `unverified`/`not_checked` in thêm ở "Điểm chưa rõ" với nhãn loại mục.
- [ ] **Step 4:** Run `uv run pytest -q` — PASS.
- [ ] **Step 5:** Commit (`feat: domain-aware markdown with verification badges`).

### Task 9: Pipeline kiểm chứng trong worker

**Files:**
- Create: `backend/app/services/verification/pipeline.py`, `backend/migrations/versions/0004_verification.py`
- Modify: `backend/app/workers/runner.py`, `backend/app/db/models.py` (`Generation.verification_json_path`), `backend/app/api/routes.py`
- Test: `backend/tests/unit/test_verification_pipeline.py`, `backend/tests/integration/test_workflow.py`

**Interfaces:**
- Consumes: Task 6–8; `extract_frame`, `safe_path`, `atomic_write`.
- Produces:
  - `pipeline.transcript_cache_path(asset_sha256: str, settings) -> str` (rel path `transcripts/{sha}-{sha256(asr_engine+asr_model)[:12]}.json` dưới `data_dir`).
  - `pipeline.ensure_transcript(settings, asset, check_cancel) -> tuple[Transcript | None, Literal["ok","skipped","failed"]]` — `skipped` khi `asr_engine="none"` hoặc `asset.has_audio == 0`; đọc cache nếu có; lỗi/timeout → `failed`, không raise (trừ `CANCELLED`, `LEASE_LOST`, `JOB_TIMEOUT`).
  - `pipeline.run_verification(settings, asset, draft: TutorialDraftV2, transcript, asr_status, workdir: Path, check_cancel) -> VerificationReport` — duyệt mọi mục theo đường dẫn; OCR tối đa `verify_max_ocr_frames` frame (đầu, giữa, cuối khoảng bằng chứng hợp nhất, < duration) cho mục `observed` có `on_screen_text`; cache OCR theo giây trong một lần chạy.
  - `Generation.verification_json_path` (nullable); file `projects/{pid}/generations/{gid}/verification.json`.
  - Phase mới `transcribing` (trước upload đoạn đầu), `verifying` (sau `extracting_evidence`).
  - Job kind `verify`; route `POST /generations/{generation_id}/verify` (202, CSRF như route khác) tạo job, worker đọc draft bằng `load_draft`, chạy lại `ensure_transcript` + `run_verification`, ghi đè `verification.json`, render lại `document.md` của generation (không tạo revision; người dùng áp dụng qua "apply-generation" hiện có), cập nhật `quality_status`.
  - `GET /generations/{id}` trả `draft` đã nâng cấp (`load_draft(...).model_dump(by_alias=True)`) và `verification` (dict hoặc null).

- [ ] **Step 1: Test thất bại.** Unit với ASR/OCR giả (monkeypatch `get_asr`/`get_ocr`):

```python
def test_transcript_cached_per_asset_and_asr_config(): # lần 2 không gọi transcribe; đổi asr_model -> gọi lại
def test_no_audio_skips_asr():                         # has_audio=0 -> ("skipped"), stated -> not_checked
def test_asr_failure_does_not_raise():                 # transcribe raise RuntimeError -> (None, "failed")
def test_ocr_samples_at_most_three_frames_inside_evidence():
```

  Integration (mock provider trả v2 có 1 parameter `stated` với quote khớp transcript giả, 1 material `observed` có `on_screen_text` khớp OCR giả, 1 material `stated` không khớp):

```python
def test_pipeline_writes_verification_and_marks_review(env, clip, monkeypatch):
    # phases đi qua "transcribing" và "verifying"; generation.verification có 3 mục: verified asr, verified ocr, unverified
    # quality needs_review; markdown chứa "✓ khớp lời nói" và "? chưa kiểm chứng"
def test_verify_job_reruns_without_provider(env, generated, monkeypatch):
    # đổi transcript giả rồi POST /generations/{id}/verify -> MockProvider.analyze không bị gọi; verification đổi
def test_verify_job_on_v1_generation(env, monkeypatch):
    # ghi draft.json v1 (từ MockProvider v1 fixture) cho một generation -> verify job succeeded, verification.items == {}
```

- [ ] **Step 2:** Run — FAIL.
- [ ] **Step 3:** Migration `0004`: thêm cột nếu chưa có (theo mẫu `0003`). Implement pipeline; nối vào `Worker.analyze` (ASR trước vòng lặp đoạn, kiểm chứng sau evidence, truyền `verification` vào `render_markdown`, `quality = "needs_review"` thêm điều kiện có mục `unverified`/`not_checked`, warning `{"code": "VERIFICATION_DEGRADED", "asr": ..., "ocr": ...}` khi một nguồn `failed`). Thêm `verify` vào bảng dispatch của `execute`.
- [ ] **Step 4:** Run `uv run pytest -q` — PASS.
- [ ] **Step 5:** Commit (`feat: run ASR/OCR verification in worker`).

### Task 10: Giao diện

**Files:**
- Modify: `frontend/src/App.tsx`, `frontend/src/styles.css` (hoặc file CSS hiện có), `frontend/src/types/*` (đã sinh ở Task 2)
- Test: `tests/e2e/browser_flow.py`

**Interfaces:**
- Consumes: job state `not_tutorial`, warning `NOT_TUTORIAL`, `skip_tutorial_gate`, `GET /generations/{id}` có `verification`, `POST /generations/{id}/verify`.

- [ ] **Step 1:** Mở rộng `tests/e2e/browser_flow.py` (mock provider) để kiểm: nhãn lĩnh vực hiển thị; dòng "N/M mục đã kiểm chứng"; bật bộ lọc "Chỉ hiện mục chưa kiểm chứng" làm ẩn bước không có mục chưa kiểm chứng; với mock `is_tutorial=False` thấy lý do và nút "Vẫn phân tích toàn bộ", bấm → hộp xác nhận chi phí → job mới có `skip_tutorial_gate`.
- [ ] **Step 2:** Chạy E2E theo README — Expected FAIL.
- [ ] **Step 3:** Implement: thêm `not_tutorial` vào `terminal`; `phaseText` thêm `transcribing: "Chép lời nói"`, `verifying: "Kiểm chứng"`, `not_tutorial: "Không phải tutorial"`; câu upload "Video hướng dẫn: nấu ăn, sửa chữa, phần mềm…"; lời nhắc cuối "Luôn kiểm tra ảnh, định lượng và lệnh trước khi sử dụng"; trên mỗi bước một huy hiệu tóm tắt ("2 mục chưa kiểm chứng") tính từ `verification.items` có tiền tố `steps/{i}/`; nút "Kiểm chứng lại" gọi route verify.
- [ ] **Step 4:** `npm --prefix frontend run build` và E2E — PASS; screenshot desktop + mobile vào `tmp/e2e-artifacts/`, xem bằng mắt.
- [ ] **Step 5:** Commit (`feat: domain, verification and non-tutorial UI`).

### Task 11: Tài liệu dự án và bộ đánh giá

**Files:**
- Modify: `PROJECT_SPEC.md` (phạm vi mọi lĩnh vực how-to; ASR/OCR local được phép; schema v2), `README.md` (cài đặt, biến mới, trạng thái), `docs/decisions.md` (schema v2, chặn đoạn 1, kiểm chứng độc lập, không đưa transcript cho Gemini), `docs/evaluation-template.md` (bảng 8 video, cột mới: định lượng sai mang ✓, % ✓ đúng, chặn non-tutorial)
- Create: `fixtures/eval/README.md` (định dạng đáp án), `scripts/evaluate.py`
- Test: `backend/tests/unit/test_evaluate.py`

**Interfaces:**
- Produces: `scripts/evaluate.py --generation-dir <dir> --annotation <json>` in JSON: `verified_precision`, `wrong_verified_quantities`, `verified_false_negative_rate`, `step_coverage`, `not_tutorial_correct`. Đáp án: `{ "is_tutorial": bool, "steps": [{"title", "start_sec"}], "materials": [{"name","quantity","unit"}], "parameters": [{"step_index","name","value","unit"}], "warnings": [str] }`.

- [ ] **Step 1: Test thất bại:** với draft + verification + đáp án dựng tay: 2 mục `verified` đúng, 1 `verified` sai định lượng → `verified_precision == 2/3`, `wrong_verified_quantities == 1`; draft `is_tutorial=False` khớp đáp án `false` → `not_tutorial_correct is True`. Khớp mục draft với đáp án theo `normalize(name)` + `digit_runs` (tái dùng Task 6).
- [ ] **Step 2:** Run — FAIL. **Step 3:** Implement. **Step 4:** Run — PASS.
- [ ] **Step 5:** Cập nhật các tài liệu ở Files; chạy toàn bộ: `uv run pytest -q`, Ruff, `npm --prefix frontend run build`.
- [ ] **Step 6:** Commit (`docs: general how-to scope and evaluation`).
- [ ] **Step 7 (cần người dùng cung cấp video và đồng ý phí):** chạy bộ 8 video qua app, chấm bằng `scripts/evaluate.py`, ghi kết quả thật vào `docs/evaluation-template.md`, kể cả mục không đạt ngưỡng (≥ 95% ✓ đúng; 2/2 non-tutorial bị chặn; 0 định lượng/thông số sai mang ✓). Không chỉnh ngưỡng để coi là đạt.
