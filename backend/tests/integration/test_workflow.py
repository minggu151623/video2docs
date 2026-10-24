import io
import json
import time
import zipfile
import pytest
from pypdf import PdfReader
from sqlalchemy import func, select, update
from app.db.models import Job, Chunk, ProviderCall, RemoteFile, Asset, Evidence, Generation
from app.core.storage import file_hash
from app.workers.runner import Worker
from app.providers.mock import MockProvider
from app.core.errors import AppError
from conftest import create_uploaded, enqueue_analysis


def test_upload_analysis_and_source_preservation(env, clip, generated):
    client, worker, cfg = env
    project, asset, job, doc = generated
    with worker.Session() as s:
        source = s.get(Asset, asset["id"])
        assert file_hash(cfg.data_dir / source.relative_path) == file_hash(clip)
        chunks = s.scalars(select(Chunk).where(Chunk.job_id == job["id"]).order_by(Chunk.index)).all()
        assert len(chunks) == 2 and all(c.state == "validated" for c in chunks)
    assert "#t=2.000" in doc["revision"]["markdown"]
    assert "MOCK" in doc["revision"]["markdown"]
    media = client.get(f"/api/v1/assets/{asset['id']}/media", headers={"Range": "bytes=0-63"})
    assert media.status_code == 206 and len(media.content) == 64
    assert (
        client.get(f"/api/v1/assets/{asset['id']}/media", headers={"Range": "bytes=9999999999-"}).status_code
        == 416
    )


@pytest.mark.parametrize("format", ["md", "zip", "pdf"])
def test_export_immutable_revision(env, generated, format):
    client, worker, cfg = env
    project, asset, job, doc = generated
    old = doc["revision"]
    response = client.post(
        f"/api/v1/documents/{doc['id']}/exports", json={"revision": old["id"], "format": format}
    )
    assert response.status_code == 202, response.text
    export_id = response.json()["id"]
    assert (
        client.put(
            f"/api/v1/documents/{doc['id']}",
            json={"base_revision": old["id"], "markdown": "Nội dung mới, chưa xuất"},
        ).status_code
        == 200
    )
    worker.once()
    state = client.get(f"/api/v1/exports/{export_id}").json()
    assert state["state"] == "succeeded", state
    data = client.get(state["download_url"]).content
    if format == "md":
        assert data.decode() == old["markdown"]
    if format == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            assert z.testzip() is None and z.read("document.md").decode() == old["markdown"]
            manifest = json.loads(z.read("manifest.json"))
            assert manifest["revision"] == old["id"]
            assert all("assets/" + e["id"] + ".png" in z.namelist() for e in manifest["evidence"])
            assert not any(name.endswith((".mp4", ".env", ".sqlite3")) for name in z.namelist())
    if format == "pdf":
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(p.extract_text() for p in reader.pages)
        assert "MOCK" in text and "Thông tin nguồn" in text and len(reader.pages) >= 1


def test_conflict_restore_and_regenerate(env, generated):
    client, worker, cfg = env
    project, asset, job, doc = generated
    base = doc["revision"]["id"]
    saved = client.put(
        f"/api/v1/documents/{doc['id']}", json={"base_revision": base, "markdown": "# Bản sửa của tôi"}
    )
    assert saved.status_code == 200
    assert (
        client.put(
            f"/api/v1/documents/{doc['id']}", json={"base_revision": base, "markdown": "stale"}
        ).status_code
        == 409
    )
    second, _ = enqueue_analysis(env, project, asset, "regenerate")
    worker.once()
    assert (
        client.get(f"/api/v1/projects/{project['id']}/document").json()["revision"]["markdown"]
        == "# Bản sửa của tôi"
    )
    restored = client.post(
        f"/api/v1/documents/{doc['id']}/restore", json={"base_revision": saved.json()["id"], "revision": base}
    )
    assert restored.status_code == 200 and restored.json()["revision_number"] == 3
    revisions = client.get(f"/api/v1/documents/{doc['id']}/revisions").json()
    assert len(revisions["items"]) == 3


def test_consent_and_idempotency(env, clip):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    bad = client.post(
        f"/api/v1/projects/{project['id']}/jobs",
        headers={"Idempotency-Key": "no-consent"},
        json={"asset_id": asset["id"], "consent_id": "missing", "allow_unknown_cost": True},
    )
    assert bad.status_code == 422
    job, body = enqueue_analysis(env, project, asset)
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/jobs", headers={"Idempotency-Key": "test-key"}, json=body
        ).json()["id"]
        == job["id"]
    )
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/jobs",
            headers={"Idempotency-Key": "test-key"},
            json={**body, "budget_usd": 2},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/jobs", headers={"Idempotency-Key": "another-key"}, json=body
        ).status_code
        == 409
    )
    with worker.Session() as s:
        assert not s.scalars(select(ProviderCall)).all()


def test_two_workers_claim_and_restart(env, clip):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    job, _ = enqueue_analysis(env, project, asset)
    other = Worker(cfg)
    assert worker.claim() == job["id"]
    assert other.claim() is None
    with worker.Session.begin() as s:
        s.execute(update(Job).where(Job.id == job["id"]).values(lease_expires_at=time.time() - 1))
        s.add(
            ProviderCall(
                job_id=job["id"], purpose="analyze", attempt=1, status="sent", requested_model="mock-fixture"
            )
        )
    scratch = cfg.data_dir / f"projects/{project['id']}/derived/{job['id']}/verification/asr-x/audio.wav"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(b"RIFF")
    other.recover()
    assert not scratch.parent.parent.parent.exists()  # a killed run leaves no speech audio behind
    status = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert status["state"] == "interrupted" and status["error_code"] == "UNKNOWN_OUTCOME"
    assert client.post(f"/api/v1/jobs/{job['id']}/retry", json={"reason": "manual"}).status_code == 422
    response = client.post(
        f"/api/v1/jobs/{job['id']}/retry",
        json={"reason": "manual", "acknowledge_possible_duplicate_cost": True},
    )
    assert response.status_code == 202
    other.engine.dispose()


def test_cancel_queued_and_delete(env, generated):
    client, worker, cfg = env
    project, asset, job, doc = generated
    queued, _ = enqueue_analysis(env, project, asset, "cancel-me")
    client.post(f"/api/v1/jobs/{queued['id']}/cancel")
    assert client.get(f"/api/v1/jobs/{queued['id']}").json()["state"] == "cancelled"
    deletion = client.delete(f"/api/v1/projects/{project['id']}").json()
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 404
    assert (
        client.put(
            f"/api/v1/documents/{doc['id']}",
            json={"base_revision": doc["revision"]["id"], "markdown": "blocked"},
        ).status_code
        == 404
    )
    worker.once()
    assert client.get(f"/api/v1/jobs/{deletion['id']}").json()["state"] == "succeeded"
    assert not (cfg.data_dir / "projects" / project["id"]).exists()


def test_security_boundaries(env):
    client, worker, cfg = env
    assert (
        client.post(
            "/api/v1/projects", json={"name": "bad"}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert (
        client.post("/api/v1/projects", json={"name": "bad"}, headers={"X-CSRF-Token": "bad"}).status_code
        == 403
    )
    client.cookies.clear()
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/session", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.get("/api/v1/health", headers={"Host": "evil.test"}).status_code == 400


def test_reject_forged_and_large_upload(env):
    client, worker, cfg = env
    project = client.post("/api/v1/projects", json={"name": "fake"}).json()
    r = client.post(
        f"/api/v1/projects/{project['id']}/assets",
        files={"file": ("$(touch bad).mp4", b"not a video", "video/mp4")},
    )
    assert r.status_code == 201
    worker.once()
    state = client.get(f"/api/v1/jobs/{r.json()['job_id']}").json()
    assert state["state"] == "failed"
    cfg.max_upload_mb = 1
    p2 = client.post("/api/v1/projects", json={"name": "large"}).json()
    assert (
        client.post(
            f"/api/v1/projects/{p2['id']}/assets", files={"file": ("x.mp4", b"x" * (1024 * 1024 + 1))}
        ).status_code
        == 413
    )
    assert not list(cfg.data_dir.rglob("*.partial"))


def test_schema_repair_only_once(env, clip, monkeypatch):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    job, _ = enqueue_analysis(env, project, asset)
    calls = []

    def malformed(*args, **kwargs):
        calls.append(1)
        return {"text": "{}", "usage": None, "model": "mock-fixture", "request_id": None, "error": None}

    monkeypatch.setattr(MockProvider, "analyze", malformed)
    worker.once()
    result = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert result["error_code"] == "SCHEMA_INVALID" and len(calls) == 2
    assert client.get(f"/api/v1/projects/{project['id']}/document").json() is None


def test_remote_cleanup_retry(env, monkeypatch):
    client, worker, cfg = env
    with worker.Session.begin() as s:
        job = Job(id="cleanup-job", kind="provider_check", state="failed")
        s.add(job)
        s.flush()
        s.add(RemoteFile(job_id=job.id, provider_file_name="files/fixture"))
    monkeypatch.setattr(
        MockProvider, "delete", lambda *args: (_ for _ in ()).throw(AppError("FAIL", "failure"))
    )
    worker.cleanup()
    assert client.get("/api/v1/jobs/cleanup-job").json()["cleanup_pending"] == 1
    monkeypatch.setattr(MockProvider, "delete", lambda *args: None)
    with worker.Session.begin() as s:
        s.execute(update(RemoteFile).values(next_cleanup_at=0))
    worker.cleanup()
    assert client.get("/api/v1/jobs/cleanup-job").json()["cleanup_pending"] == 0


def test_reselect_frame_creates_revision(env, generated):
    client, worker, cfg = env
    project, asset, job, doc = generated
    generation = client.get(f"/api/v1/generations/{doc['revision']['generation_id']}").json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/evidence",
        json={
            "asset_id": asset["id"],
            "generation_id": generation["id"],
            "step_id": generation["draft"]["steps"][0]["local_id"],
            "timestamp": 1.5,
            "base_revision": doc["revision"]["id"],
        },
    )
    assert response.status_code == 202
    worker.once()
    new = client.get(f"/api/v1/projects/{project['id']}/document").json()["revision"]
    assert new["revision_number"] == 2 and new["id"] != doc["revision"]["id"]
    with worker.Session() as s:
        image = s.scalars(select(Evidence).where(Evidence.requested_sec == 1.5)).first()
        assert abs(image.actual_sec - 1.5) <= 0.5


def test_checkpoint_retry_does_not_repeat_validated_chunk(env, clip, monkeypatch):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    job, _ = enqueue_analysis(env, project, asset)
    real = MockProvider.analyze
    calls = []

    def fail_second(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise AppError("UNKNOWN_OUTCOME", "unknown")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(MockProvider, "analyze", fail_second)
    worker.once()
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["state"] == "interrupted"
    retry = client.post(
        f"/api/v1/jobs/{job['id']}/retry",
        json={"reason": "explicit retry", "acknowledge_possible_duplicate_cost": True},
    )
    assert retry.status_code == 202
    worker.once()
    assert len(calls) == 3
    assert client.get(f"/api/v1/jobs/{retry.json()['id']}").json()["state"] == "needs_review"


def test_cancel_during_encode_stops_next_stage(env, clip, monkeypatch):
    client, worker, cfg = env
    project = client.post("/api/v1/projects", json={"name": "cancel in encode"}).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/assets", files={"file": ("clip.mp4", clip.read_bytes())}
    )
    job_id = response.json()["job_id"]

    def cancel_encode(*args):
        client.post(f"/api/v1/jobs/{job_id}/cancel")
        args[-1]()

    monkeypatch.setattr("app.workers.runner.encode", cancel_encode)
    worker.once()
    assert client.get(f"/api/v1/jobs/{job_id}").json()["state"] == "cancelled"
    with worker.Session() as s:
        assert not s.scalars(select(ProviderCall)).all()


def test_missing_image_fails_zip_without_broken_archive(env, generated):
    client, worker, cfg = env
    project, asset, job, doc = generated
    with worker.Session() as s:
        evidence = s.scalars(select(Evidence)).first()
        (cfg.data_dir / evidence.relative_path).unlink()
    response = client.post(
        f"/api/v1/documents/{doc['id']}/exports", json={"revision": doc["revision"]["id"], "format": "zip"}
    )
    worker.once()
    export = client.get(f"/api/v1/exports/{response.json()['id']}").json()
    assert export["state"] == "failed" and export["job"]["error_code"] == "EVIDENCE_MISSING"


def test_low_disk_stops_upload_without_partial(env, clip, monkeypatch):
    from types import SimpleNamespace

    client, worker, cfg = env
    project = client.post("/api/v1/projects", json={"name": "low disk"}).json()
    monkeypatch.setattr("app.api.routes.shutil.disk_usage", lambda *args: SimpleNamespace(free=0))
    response = client.post(
        f"/api/v1/projects/{project['id']}/assets", files={"file": ("x.mp4", clip.read_bytes())}
    )
    assert response.status_code == 503 and response.json()["error"]["code"] == "DISK_FULL"
    assert not list(cfg.data_dir.rglob("*.partial"))


def test_remote_image_rejected_for_pdf(env, generated):
    client, worker, cfg = env
    project, asset, job, doc = generated
    revision = client.put(
        f"/api/v1/documents/{doc['id']}",
        json={
            "base_revision": doc["revision"]["id"],
            "markdown": "# Unsafe\n\n![track](https://evil.invalid/track.png)",
        },
    ).json()
    export = client.post(
        f"/api/v1/documents/{doc['id']}/exports", json={"revision": revision["id"], "format": "pdf"}
    ).json()
    worker.once()
    assert client.get(f"/api/v1/exports/{export['id']}").json()["job"]["error_code"] == "UNSAFE_IMAGE"


def test_recovery_kills_only_matching_owned_process(env):
    import os
    import signal
    import subprocess
    from app.workers.runner import process_identity
    from app.core.storage import sha256

    client, worker, cfg = env
    project = client.post("/api/v1/projects", json={"name": "owned process recovery"}).json()
    target = cfg.data_dir / "projects" / project["id"] / "derived" / "crash.mp4"
    target.parent.mkdir(parents=True)
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-re",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=64x64:r=1",
            "-t",
            "20",
            "-y",
            str(target),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        time.sleep(0.1)
        signature = sha256(process_identity(process.pid).encode())
        with worker.Session.begin() as s:
            s.add(
                Job(
                    id="crashed-media",
                    project_id=project["id"],
                    kind="validate_asset",
                    state="running",
                    lease_expires_at=time.time() - 1,
                    subprocess_pid=process.pid,
                    subprocess_signature=signature,
                )
            )
        worker.recover()
        assert process.wait(timeout=3) < 0
        assert client.get("/api/v1/jobs/crashed-media").json()["state"] == "interrupted"
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


@pytest.mark.parametrize("fmt", ["mov", "webm"])
def test_supported_containers(env, clip, tmp_path, fmt):
    import subprocess

    client, worker, cfg = env
    target = tmp_path / ("video." + fmt)
    codec = ["-c:v", "libvpx-vp9", "-threads", "2"] if fmt == "webm" else ["-c", "copy"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), *codec, str(target)], check=True)
    project = client.post("/api/v1/projects", json={"name": fmt}).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/assets", files={"file": (target.name, target.read_bytes())}
    )
    worker.once()
    assert client.get(f"/api/v1/assets/{response.json()['id']}").json()["validation_status"] == "validated"


def test_duration_limit_refuses_before_analysis(env, clip):
    client, worker, cfg = env
    cfg.max_video_seconds = 1
    project = client.post("/api/v1/projects", json={"name": "too long"}).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/assets", files={"file": ("clip.mp4", clip.read_bytes())}
    )
    worker.once()
    result = client.get(f"/api/v1/jobs/{response.json()['job_id']}").json()
    assert result["state"] == "failed" and result["error_code"] == "VIDEO_TOO_LONG"
    with worker.Session() as s:
        assert not s.scalars(select(ProviderCall)).all()


def test_missing_chromium_does_not_lose_markdown(env, generated, monkeypatch):
    client, worker, cfg = env
    project, asset, job, doc = generated

    def missing(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr("app.services.exports.subprocess.Popen", missing)
    export = client.post(
        f"/api/v1/documents/{doc['id']}/exports", json={"revision": doc["revision"]["id"], "format": "pdf"}
    ).json()
    worker.once()
    result = client.get(f"/api/v1/exports/{export['id']}").json()
    assert result["job"]["error_code"] == "PDF_DEPENDENCY"
    assert (
        client.get(f"/api/v1/projects/{project['id']}/document").json()["revision"]["markdown"]
        == doc["revision"]["markdown"]
    )


def test_chunked_oversize_stream_returns_413(env):
    client, worker, cfg = env
    cfg.max_upload_mb = 1
    project = client.post("/api/v1/projects", json={"name": "stream limit"}).json()

    def stream():
        yield b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="x.mp4"\r\nContent-Type: video/mp4\r\n\r\n'
        for _ in range(25):
            yield b"x" * (100 * 1024)
        yield b"\r\n--boundary--\r\n"

    response = client.post(
        f"/api/v1/projects/{project['id']}/assets",
        content=stream(),
        headers={"Content-Type": "multipart/form-data; boundary=boundary"},
    )
    assert response.status_code == 413, response.text
    assert not list(cfg.data_dir.rglob("*.partial"))


def test_real_long_chunk_offsets_and_overlimit_fixture(env):
    from pathlib import Path

    client, worker, cfg = env
    root = Path(__file__).resolve().parents[3]
    long_clip = root / "fixtures/synthetic_long.mp4"
    if not long_clip.exists():
        import subprocess

        subprocess.run(
            ["uv", "run", "python", str(root / "scripts/generate_fixtures.py")], check=True, cwd=root
        )
    cfg.chunk_seconds, cfg.chunk_overlap_seconds = 300, 5
    project, asset = create_uploaded(env, long_clip)
    job, _ = enqueue_analysis(env, project, asset)
    worker.once()
    doc = client.get(f"/api/v1/projects/{project['id']}/document").json()
    assert "#t=295.000" in doc["revision"]["markdown"]
    with worker.Session() as s:
        chunks = s.scalars(select(Chunk).where(Chunk.job_id == job["id"]).order_by(Chunk.index)).all()
        assert [(c.start_sec, c.end_sec) for c in chunks] == [(0, 300), (295, 305)]
    project2 = client.post("/api/v1/projects", json={"name": "over 20 minutes"}).json()
    response = client.post(
        f"/api/v1/projects/{project2['id']}/assets",
        files={"file": ("long.mp4", (root / "fixtures/synthetic_overlimit.mp4").read_bytes())},
    )
    worker.once()
    assert client.get(f"/api/v1/jobs/{response.json()['job_id']}").json()["error_code"] == "VIDEO_TOO_LONG"


def test_retry_rejects_changed_analyzer_contract(env, generated):
    client, worker, cfg = env
    _, _, job, _ = generated
    with worker.Session.begin() as s:
        old = s.get(Job, job["id"])
        old.state = "failed"
        snapshot = json.loads(old.settings_snapshot_json)
        snapshot["analysis_contract_sha256"] = "old-contract"
        old.settings_snapshot_json = json.dumps(snapshot)
    response = client.post(f"/api/v1/jobs/{job['id']}/retry", json={"reason": "contract changed"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "SETTINGS_CHANGED"


def test_repair_receives_actionable_errors_without_raw_model_input(env, clip, monkeypatch):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    job, _ = enqueue_analysis(env, project, asset)
    real = MockProvider.analyze
    repairs = []

    def analyze(self, reference, duration, language, metadata, repair=None):
        result = real(self, reference, duration, language, metadata, repair)
        if repair:
            repairs.append(json.loads(repair))
        elif not repairs:
            payload = json.loads(result["text"])
            payload["summary"] = "private-invalid-output-marker"
            payload["steps"][0]["end_sec"] = duration + 1
            result["text"] = json.dumps(payload)
        return result

    monkeypatch.setattr(MockProvider, "analyze", analyze)
    worker.once()
    response = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert response["state"] == "needs_review"
    assert repairs and "outside clip timeline" in repairs[0]["errors"][0]["message"]
    assert all("input" not in e for e in repairs[0]["errors"])
    assert json.loads(repairs[0]["previous_output"])["summary"] == "private-invalid-output-marker"
    assert "private-invalid-output-marker" not in json.dumps(response)
    assert any(w.get("code") == "SCHEMA_INVALID" for w in response["warnings"] if isinstance(w, dict))


def test_digit_seconds_from_timecode_provider_go_to_repair(env, clip, monkeypatch):
    from app.providers.timecodes import to_seconds, to_timecodes

    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    job, _ = enqueue_analysis(env, project, asset)
    real = MockProvider.analyze
    repairs = []

    def analyze(self, reference, duration, language, metadata, repair=None):
        result = real(self, reference, duration, language, metadata, repair)
        payload = to_timecodes(json.loads(result["text"]))
        if repair:
            repairs.append(json.loads(repair))
        elif not repairs:
            payload["steps"][0]["end"] = "1"
        result["text"] = json.dumps(payload)
        return result

    monkeypatch.setattr(MockProvider, "analyze", analyze)
    monkeypatch.setattr(MockProvider, "decode", staticmethod(to_seconds))
    worker.once()
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["state"] == "needs_review"
    error = repairs[0]["errors"][0]
    assert error["loc"] == ["steps", "0", "end"] and error["type"] == "timecode_invalid"
    assert json.loads(repairs[0]["previous_output"])["steps"][0]["end"] == "1"


def test_conflicting_screenshot_uses_end_of_visual_evidence_and_requires_review(env, clip, monkeypatch):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    original = MockProvider.analyze

    def analyze(self, reference, duration, language, metadata, repair=None):
        result = original(self, reference, duration, language, metadata, repair)
        payload = json.loads(result["text"])
        payload["uncertainties"] = []
        step = payload["steps"][0]
        step.update(needs_review=False, review_reason=None, screenshot_candidates_sec=[0.2])
        step["evidence_spans"][0].update(start_sec=1, end_sec=1.5)
        result["text"] = json.dumps(payload)
        return result

    monkeypatch.setattr(MockProvider, "analyze", analyze)
    job, _ = enqueue_analysis(env, project, asset)
    worker.once()
    detail = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert detail["state"] == "needs_review"
    conflicts = [w for w in detail["warnings"] if w["code"] == "EVIDENCE_TIMESTAMP_CONFLICT"]
    assert conflicts and conflicts[0]["fallback_sec"] == 1.5
    document = client.get(f"/api/v1/projects/{project['id']}/document").json()
    generation = client.get(f"/api/v1/generations/{document['revision']['generation_id']}").json()
    assert 1.5 in [e["requested_sec"] for e in generation["evidence"]]
    assert "đã dùng frame cuối của khoảng bằng chứng" in document["revision"]["markdown"]


def test_chunk_context_claim_review_and_result_evidence_in_pipeline(env, clip, monkeypatch):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    original = MockProvider.analyze
    contexts = []

    def analyze(self, reference, duration, language, metadata, repair=None):
        contexts.append(metadata)
        result = original(self, reference, duration, language, metadata, repair)
        payload = json.loads(result["text"])
        payload["uncertainties"] = []
        step = payload["steps"][0]
        step.update(needs_review=False, review_reason=None, expected_result="Observed result")
        step["screenshot_candidates_sec"] = [0.5, 1.5]
        payload["troubleshooting"] = [
            {
                "text": "Unproven remedy",
                "basis": "inferred",
                "scope": "clip",
                "evidence_spans": step["evidence_spans"],
            }
        ]
        result["text"] = json.dumps(payload)
        return result

    monkeypatch.setattr(MockProvider, "analyze", analyze)
    job, _ = enqueue_analysis(env, project, asset)
    worker.once()
    detail = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert detail["state"] == "needs_review" and not detail["warnings"]
    assert [c["clip_index"] for c in contexts] == [1, 2]
    assert not contexts[0]["previous_steps"] and contexts[1]["previous_steps"]
    assert contexts[1]["clip_start_sec"] == 2
    document = client.get(f"/api/v1/projects/{project['id']}/document").json()
    text = document["revision"]["markdown"]
    assert "Unproven remedy" not in text.split("## Điểm chưa rõ", 1)[0]
    assert "chưa đủ bằng chứng: Unproven remedy" in text
    generation = client.get(f"/api/v1/generations/{document['revision']['generation_id']}").json()
    assert sorted(e["requested_sec"] for e in generation["evidence"]) == [1.5, 3.5]


def non_tutorial_payload(payload, reason="Vlog"):
    payload.update(is_tutorial=False, not_tutorial_reason=reason, steps=[], troubleshooting=[])
    return payload


def patch_provider(monkeypatch, edit):
    original = MockProvider.analyze
    calls = []

    def analyze(self, reference, duration, language, metadata, repair=None):
        calls.append(metadata)
        result = original(self, reference, duration, language, metadata, repair)
        result["text"] = json.dumps(edit(json.loads(result["text"]), metadata["clip_index"]))
        return result

    monkeypatch.setattr(MockProvider, "analyze", analyze)
    return calls


def test_not_tutorial_stops_after_first_clip(env, clip, monkeypatch):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    patch_provider(monkeypatch, lambda payload, clip_index: non_tutorial_payload(payload))
    job, _ = enqueue_analysis(env, project, asset)
    worker.once()
    detail = client.get(f"/api/v1/jobs/{job['id']}").json()
    with worker.Session() as s:
        assert s.scalar(select(func.count()).select_from(Chunk).where(Chunk.job_id == job["id"])) == 2
    assert detail["state"] == "not_tutorial" and detail["phase"] == "not_tutorial"
    assert len(detail["provider_calls"]) == 1
    assert {"code": "NOT_TUTORIAL", "reason": "Vlog"} in detail["warnings"]
    assert client.get(f"/api/v1/projects/{project['id']}/document").json() is None
    with worker.Session() as s:
        assert not s.scalars(select(Generation)).all()
        chunks = s.scalars(select(Chunk).where(Chunk.job_id == job["id"]).order_by(Chunk.index)).all()
        assert [c.state for c in chunks] == ["validated", "queued"]
    again, _ = enqueue_analysis(env, project, asset, "again", skip_tutorial_gate=True)
    assert again["id"] != job["id"] and again["state"] == "queued"
    retried = client.post(f"/api/v1/jobs/{job['id']}/retry", json={"reason": "again"})
    assert retried.status_code == 409 and retried.json()["error"]["code"] == "RETRY_NOT_ALLOWED"


def test_single_clip_video_is_also_gated(env, clip, monkeypatch):
    client, worker, cfg = env
    cfg.chunk_seconds, cfg.chunk_overlap_seconds = 60, 1
    project, asset = create_uploaded(env, clip)
    patch_provider(monkeypatch, lambda payload, clip_index: non_tutorial_payload(payload, "Quảng cáo"))
    job, _ = enqueue_analysis(env, project, asset)
    worker.once()
    detail = client.get(f"/api/v1/jobs/{job['id']}").json()
    with worker.Session() as s:
        assert s.scalar(select(func.count()).select_from(Chunk).where(Chunk.job_id == job["id"])) == 1
    assert detail["state"] == "not_tutorial" and len(detail["provider_calls"]) == 1
    assert {"code": "NOT_TUTORIAL", "reason": "Quảng cáo"} in detail["warnings"]
    assert client.get(f"/api/v1/projects/{project['id']}/document").json() is None


def test_later_clip_not_tutorial_is_only_recorded(env, clip, monkeypatch):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)

    def edit(payload, clip_index):
        return non_tutorial_payload(payload, "Lời kết") if clip_index == 2 else payload

    calls = patch_provider(monkeypatch, edit)
    job, _ = enqueue_analysis(env, project, asset)
    worker.once()
    detail = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert detail["state"] in ("needs_review", "succeeded") and len(calls) == 2
    assert {"code": "LATER_CLIP_NOT_TUTORIAL", "clip_index": 2} in detail["warnings"]
    assert not any(w.get("code") == "NOT_TUTORIAL" for w in detail["warnings"] if isinstance(w, dict))
    assert client.get(f"/api/v1/projects/{project['id']}/document").json() is not None


def test_skip_gate_analyzes_all_clips(env, clip, monkeypatch):
    client, worker, cfg = env
    project, asset = create_uploaded(env, clip)
    calls = patch_provider(
        monkeypatch, lambda payload, clip_index: non_tutorial_payload(payload) if clip_index == 1 else payload
    )
    job, _ = enqueue_analysis(env, project, asset, skip_tutorial_gate=True)
    worker.once()
    detail = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert detail["state"] == "needs_review" and len(detail["provider_calls"]) == len(calls) == 2
    assert not any(w.get("code") == "NOT_TUTORIAL" for w in detail["warnings"] if isinstance(w, dict))
    assert client.get(f"/api/v1/projects/{project['id']}/document").json() is not None


def grounded_payload(payload, clip_index):
    """One stated parameter, one observed material with screen text, one stated material."""
    payload["uncertainties"] = []
    step = payload["steps"][0]
    step.update(needs_review=False, review_reason=None)
    audio = [{"start_sec": 0, "end_sec": 2, "source": "audio", "description": "Lời nói"}]
    visual = [{"start_sec": 0, "end_sec": 2, "source": "visual", "description": "Chữ trên màn hình"}]
    step["parameters"] = [
        {
            "name": "Nhiệt độ",
            "value": "180",
            "unit": "độ",
            "evidence_spans": audio,
            "basis": "stated",
            "quote": "đặt nhiệt độ 180 độ",
            "on_screen_text": None,
        }
    ]
    payload["materials"] = [
        {
            "name": "Bột mì",
            "quantity": "200",
            "unit": "g",
            "note": None,
            "evidence_spans": visual,
            "basis": "observed",
            "quote": None,
            "on_screen_text": "Bột mì 200 g",
        },
        {
            "name": "Đường",
            "quantity": "50",
            "unit": "g",
            "note": None,
            "evidence_spans": audio,
            "basis": "stated",
            "quote": "thêm 50 g đường",
            "on_screen_text": None,
        },
    ]
    return payload


class FakeASR:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def transcribe(self, audio, check_cancel):
        from app.schemas.verification import Transcript, Word

        self.calls += 1
        assert audio.stat().st_size > 0
        words = self.text.split()
        return Transcript(
            language="vi",
            words=[Word(start=0.2 + 0.2 * i, end=0.35 + 0.2 * i, text=w) for i, w in enumerate(words)],
        )


class FakeOCR:
    def __init__(self, text="Bột mì 200 g", delay=0.0):
        self.text, self.delay, self.frames = text, delay, []

    def read(self, image, language=None):
        assert image.stat().st_size > 0
        self.frames.append(image.name)
        time.sleep(self.delay)
        return self.text


# far enough apart that the matcher does not read the two numbers as a range or an alternative
BOTH_SAID = "đặt nhiệt độ 180 độ rồi khuấy đều tay cho bột thật mịn và sau đó thêm 50 g đường"


def use_engines(monkeypatch, cfg, asr, ocr):
    cfg.asr_engine, cfg.ocr_engine, cfg.chunk_seconds = "faster-whisper", "paddleocr", 60
    monkeypatch.setattr("app.services.verification.pipeline.get_asr", lambda settings: asr)
    monkeypatch.setattr("app.services.verification.pipeline.get_ocr", lambda settings: ocr)


def record_phases(monkeypatch):
    phases = []
    original = Worker.phase

    def phase(self, job_id, name, completed=None, total=None):
        phases.append(name)
        return original(self, job_id, name, completed, total)

    monkeypatch.setattr(Worker, "phase", phase)
    return phases


def verified_generation(env, voiced_clip, monkeypatch, asr, ocr):
    client, worker, cfg = env
    use_engines(monkeypatch, cfg, asr, ocr)
    project, asset = create_uploaded(env, voiced_clip)
    assert asset["has_audio"] == 1
    patch_provider(monkeypatch, grounded_payload)
    job, _ = enqueue_analysis(env, project, asset)
    phases = record_phases(monkeypatch)
    worker.once()
    detail = client.get(f"/api/v1/jobs/{job['id']}").json()
    document = client.get(f"/api/v1/projects/{project['id']}/document").json()
    generation = client.get(f"/api/v1/generations/{document['revision']['generation_id']}").json()
    return project, asset, detail, document, generation, phases


def test_pipeline_writes_verification_and_marks_review(env, voiced_clip, monkeypatch):
    client, worker, cfg = env
    asr = FakeASR("đặt nhiệt độ 180 độ rồi khuấy đều")
    ocr = FakeOCR()
    from app.services.verification import pipeline

    real, audio = pipeline.extract_audio, []

    def spy(source, target, check_cancel, *, timeout):
        audio.append(target)
        return real(source, target, check_cancel, timeout=timeout)

    monkeypatch.setattr(pipeline, "extract_audio", spy)
    project, asset, detail, document, generation, phases = verified_generation(
        env, voiced_clip, monkeypatch, asr, ocr
    )
    assert detail["state"] == "needs_review", detail
    assert phases.index("transcribing") < phases.index("uploading")
    assert phases.index("extracting_evidence") < phases.index("verifying") < phases.index("saving")
    assert generation["quality_status"] == "needs_review"
    report = generation["verification"]
    assert report["asr_status"] == "ok" and report["ocr_status"] == "ok"
    items = report["items"]
    assert set(items) == {"materials/0", "materials/1", "steps/0/parameters/0"}
    assert (items["steps/0/parameters/0"]["status"], items["steps/0/parameters/0"]["method"]) == (
        "verified",
        "asr",
    )
    assert (items["materials/0"]["status"], items["materials/0"]["method"]) == ("verified", "ocr")
    assert items["materials/1"]["status"] == "unverified"
    assert 1 <= len(ocr.frames) <= 3 and asr.calls == 1
    job_dir = cfg.data_dir / "projects" / project["id"] / "derived" / detail["id"]
    assert len(audio) == 1 and audio[0].is_relative_to(job_dir) and not audio[0].exists()
    assert generation["draft"]["schema_version"] == "2.0" and "yield" in generation["draft"]
    assert "verification_json_path" not in generation
    markdown = document["revision"]["markdown"]
    assert "✓ khớp lời nói" in markdown and "? chưa kiểm chứng" in markdown
    assert "✓ khớp chữ trên màn hình" in markdown
    assert not any(w.get("code") == "VERIFICATION_DEGRADED" for w in detail["warnings"])
    assert not (cfg.data_dir / "projects" / project["id"] / "derived" / detail["id"]).exists()


def test_verify_job_reruns_without_provider(env, voiced_clip, monkeypatch):
    client, worker, cfg = env
    project, asset, detail, document, generation, _ = verified_generation(
        env, voiced_clip, monkeypatch, FakeASR("đặt nhiệt độ 180 độ rồi khuấy đều"), FakeOCR()
    )
    assert generation["verification"]["items"]["materials/1"]["status"] == "unverified"

    def forbidden(*args, **kwargs):
        raise AssertionError("verify must not call the AI provider")

    monkeypatch.setattr(MockProvider, "analyze", forbidden)
    monkeypatch.setattr(MockProvider, "upload", forbidden)
    monkeypatch.setattr("app.workers.runner.get_provider", forbidden)
    asr = FakeASR(BOTH_SAID)
    use_engines(monkeypatch, cfg, asr, FakeOCR())
    cfg.asr_model = "medium"  # a new ASR configuration has its own transcript cache entry
    phases = record_phases(monkeypatch)
    response = client.post(f"/api/v1/generations/{generation['id']}/verify")
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["kind"] == "verify"
    again = client.post(f"/api/v1/generations/{generation['id']}/verify")
    assert again.status_code == 409 and again.json()["error"]["code"] == "JOB_IN_PROGRESS"
    worker.once()
    finished = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert finished["state"] == "succeeded", finished
    assert "transcribing" in phases and "verifying" in phases and asr.calls == 1
    after = client.get(f"/api/v1/generations/{generation['id']}").json()
    assert after["verification"]["items"]["materials/1"]["status"] == "verified"
    assert after["quality_status"] == "succeeded"
    path = cfg.data_dir / f"projects/{project['id']}/generations/{generation['id']}/document.md"
    assert "? chưa kiểm chứng" not in path.read_text()
    revisions = client.get(f"/api/v1/documents/{document['id']}/revisions").json()["items"]
    assert len(revisions) == 1  # re-verification never creates a revision by itself


def test_verify_route_requires_csrf_and_known_generation(env, generated):
    client, worker, cfg = env
    project, asset, job, doc = generated
    generation_id = doc["revision"]["generation_id"]
    forged = client.post(f"/api/v1/generations/{generation_id}/verify", headers={"X-CSRF-Token": "bad"})
    assert forged.status_code == 403
    assert client.post("/api/v1/generations/missing/verify").status_code == 404


def test_verify_job_on_v1_generation(env, generated, monkeypatch):
    client, worker, cfg = env
    project, asset, job, doc = generated
    generation_id = doc["revision"]["generation_id"]
    span = {"start_sec": 0, "end_sec": 2, "source": "visual", "description": "Màn hình"}
    v1 = {
        "schema_version": "1.0",
        "title": "Tài liệu cũ",
        "summary": "Bản v1",
        "language": "vi",
        "objectives": [],
        "prerequisites": [],
        "tools": [{"name": "Python", "version": "3.13", "evidence_spans": [span]}],
        "steps": [
            {
                "local_id": "s1",
                "title": "Mở terminal",
                "start_sec": 0,
                "end_sec": 2,
                "actions": ["Mở terminal"],
                "expected_result": None,
                "commands": [],
                "evidence_spans": [span],
                "screenshot_candidates_sec": [1],
                "needs_review": False,
                "review_reason": None,
            }
        ],
        "troubleshooting": [],
        "uncertainties": [],
    }
    path = cfg.data_dir / f"projects/{project['id']}/generations/{generation_id}/draft.json"
    path.write_text(json.dumps(v1))
    monkeypatch.setattr("app.workers.runner.get_provider", lambda *a: (_ for _ in ()).throw(AssertionError()))
    response = client.post(f"/api/v1/generations/{generation_id}/verify")
    assert response.status_code == 202, response.text
    worker.once()
    assert client.get(f"/api/v1/jobs/{response.json()['id']}").json()["state"] == "succeeded"
    generation = client.get(f"/api/v1/generations/{generation_id}").json()
    assert generation["verification"]["items"] == {}
    assert generation["draft"]["schema_version"] == "2.0" and generation["draft"]["domain"] == "software"
    assert generation["draft"]["equipment"][0]["spec"] == "3.13"


def test_generation_without_verification_returns_null(env, generated):
    client, worker, cfg = env
    project, asset, job, doc = generated
    generation_id = doc["revision"]["generation_id"]
    with worker.Session.begin() as s:
        s.execute(update(Generation).values(verification_json_path=None))
    assert client.get(f"/api/v1/generations/{generation_id}").json()["verification"] is None


def test_ocr_budget_exhaustion_degrades_but_completes(env, voiced_clip, monkeypatch):
    client, worker, cfg = env
    cfg.ocr_timeout_seconds = 1
    ocr = FakeOCR(delay=1.1)
    project, asset, detail, document, generation, _ = verified_generation(
        env, voiced_clip, monkeypatch, FakeASR(BOTH_SAID), ocr
    )
    assert detail["state"] == "needs_review", detail
    assert len(ocr.frames) == 1
    item = generation["verification"]["items"]["materials/0"]
    assert item["status"] == "not_checked" and item["reason"] == "hết thời gian OCR"
    assert generation["verification"]["ocr_status"] == "failed"
    assert {
        "code": "VERIFICATION_DEGRADED",
        "asr": "ok",
        "ocr": "failed",
        "asr_error": None,
        "ocr_error": "OCR_TIMEOUT",
    } in detail["warnings"]
    assert generation["quality_status"] == "needs_review"


def test_silent_video_skips_asr_without_extracting_audio(env, clip, monkeypatch):
    client, worker, cfg = env
    asr = FakeASR("đặt nhiệt độ 180 độ")
    use_engines(monkeypatch, cfg, asr, FakeOCR())
    calls = []
    monkeypatch.setattr("app.services.verification.pipeline.extract_audio", lambda *a, **k: calls.append(a))
    project, asset = create_uploaded(env, clip)
    assert asset["has_audio"] == 0
    patch_provider(monkeypatch, grounded_payload)
    job, _ = enqueue_analysis(env, project, asset)
    worker.once()
    detail = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert detail["state"] == "needs_review" and not calls and asr.calls == 0
    document = client.get(f"/api/v1/projects/{project['id']}/document").json()
    generation = client.get(f"/api/v1/generations/{document['revision']['generation_id']}").json()
    assert generation["verification"]["asr_status"] == "skipped"
    assert generation["verification"]["items"]["steps/0/parameters/0"]["status"] == "not_checked"


def test_delete_project_removes_cached_transcript(env, voiced_clip, monkeypatch):
    client, worker, cfg = env
    project, asset, detail, *_ = verified_generation(
        env, voiced_clip, monkeypatch, FakeASR(BOTH_SAID), FakeOCR()
    )
    cached = list((cfg.data_dir / "transcripts").glob(f"{asset['sha256']}-*.json"))
    assert len(cached) == 1
    assert client.delete(f"/api/v1/projects/{project['id']}").status_code == 202
    worker.once()
    assert not cached[0].exists()


def test_asr_failure_is_reported_with_code(env, voiced_clip, monkeypatch, caplog):
    client, worker, cfg = env

    class BrokenASR:
        def transcribe(self, audio, check_cancel):
            raise AppError("ASR_FAILED", "Không chạy được nhận dạng giọng nói local.", 503)

    with caplog.at_level("WARNING", logger="video2docs.verification"):
        project, asset, detail, document, generation, _ = verified_generation(
            env, voiced_clip, monkeypatch, BrokenASR(), FakeOCR()
        )
    assert "ASR_FAILED" in caplog.text
    assert detail["state"] == "needs_review"
    warning = next(w for w in detail["warnings"] if w.get("code") == "VERIFICATION_DEGRADED")
    assert (warning["asr"], warning["asr_error"], warning["ocr_error"]) == ("failed", "ASR_FAILED", None)
    report = generation["verification"]
    assert report["asr_status"] == "failed" and report["asr_error"] == "ASR_FAILED"
    item = report["items"]["steps/0/parameters/0"]
    assert (item["status"], item["reason"]) == ("not_checked", "ASR lỗi (ASR_FAILED)")
