import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.workers.runner import Worker

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "tutorial.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=10:duration=4",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="session")
def voiced_clip(tmp_path_factory):
    """Same picture as `clip` plus a tone track, so the asset has audio for the ASR step."""
    path = tmp_path_factory.mktemp("media") / "voiced.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=10:duration=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=4",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture
def env(tmp_path):
    cfg = Settings(
        data_dir=tmp_path,
        database_url="sqlite:///" + str(tmp_path / "app.sqlite3"),
        ai_provider="mock",
        chunk_seconds=3,
        chunk_overlap_seconds=1,
        asr_engine="none",
        ocr_engine="none",
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        client.headers["Origin"] = "http://127.0.0.1:8000"
        token = client.get("/api/v1/session").json()["csrf_token"]
        client.headers["X-CSRF-Token"] = token
        worker = Worker(cfg)
        yield client, worker, cfg
    worker.engine.dispose()


def create_uploaded(env, clip):
    client, worker, cfg = env
    project = client.post(
        "/api/v1/projects", json={"name": "Tài liệu thử nghiệm", "output_language": "vi"}
    ).json()
    with clip.open("rb") as stream:
        response = client.post(
            f"/api/v1/projects/{project['id']}/assets", files={"file": ("tutorial.mp4", stream, "video/mp4")}
        )
    assert response.status_code == 201, response.text
    asset = response.json()
    worker.once()
    detail = client.get(f"/api/v1/assets/{asset['id']}").json()
    assert detail["validation_status"] == "validated", client.get(f"/api/v1/jobs/{asset['job_id']}").text
    return project, detail


def enqueue_analysis(env, project, asset, key="test-key", **extra):
    client, _, _ = env
    consent = client.post(
        f"/api/v1/projects/{project['id']}/consents",
        json={"asset_sha256": asset["sha256"], "notice_version": "2026-10-20.v1"},
    ).json()
    body = {
        "asset_id": asset["id"],
        "consent_id": consent["id"],
        "allow_unknown_cost": True,
        "output_language": "vi",
        "budget_usd": 1,
        **extra,
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/jobs", json=body, headers={"Idempotency-Key": key}
    )
    assert response.status_code == 202, response.text
    return response.json(), body


@pytest.fixture
def generated(env, clip):
    project, asset = create_uploaded(env, clip)
    job, body = enqueue_analysis(env, project, asset)
    env[1].once()
    response = env[0].get(f"/api/v1/jobs/{job['id']}").json()
    assert response["state"] == "needs_review", response
    doc = env[0].get(f"/api/v1/projects/{project['id']}/document").json()
    assert doc is not None
    return project, asset, job, doc
