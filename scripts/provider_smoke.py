"""Explicitly submit a non-sensitive clip through the real local API + worker."""

import argparse
import importlib.metadata
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--video", type=Path, required=True)
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument("--confirm-google-upload", action="store_true", required=True)
parser.add_argument("--accept-unknown-cost", action="store_true", required=True)
args = parser.parse_args()
if not args.url.startswith(("http://127.0.0.1:", "http://localhost:")):
    parser.error("Only use the trusted localhost API")
with httpx.Client(base_url=args.url + "/api/v1", headers={"Origin": args.url}, timeout=60) as client:

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(
                f"{response.status_code}: {response.json().get('error', {}).get('code', 'HTTP_ERROR')}"
            )
        return response.json()

    token = request("GET", "/session")["csrf_token"]
    client.headers["X-CSRF-Token"] = token
    cap = request("GET", "/capabilities")
    if cap["provider"] != "gemini" or not cap["provider_ready"]:
        raise SystemExit("Live smoke requires AI_PROVIDER=gemini and a backend key; no fallback.")
    project = request("POST", "/projects", json={"name": "Live integration smoke", "output_language": "vi"})
    with args.video.open("rb") as stream:
        asset = request(
            "POST", f"/projects/{project['id']}/assets", files={"file": ("smoke.mp4", stream, "video/mp4")}
        )

    def wait(job_id):
        deadline = time.monotonic() + 2800
        while time.monotonic() < deadline:
            job = request("GET", f"/jobs/{job_id}")
            if job["state"] in (
                "succeeded",
                "needs_review",
                "not_tutorial",
                "failed",
                "interrupted",
                "cancelled",
            ):
                return job
            time.sleep(2)
        raise RuntimeError("Local wait timed out; job remains visible in the app.")

    validated = wait(asset["job_id"])
    if validated["state"] != "succeeded":
        raise SystemExit(validated["error_code"])
    meta = request("GET", f"/assets/{asset['id']}")
    if not 10 <= meta["duration_sec"] <= 30:
        raise SystemExit("Smoke clip must be 10–30 seconds; no provider call was made.")
    consent = request(
        "POST",
        f"/projects/{project['id']}/consents",
        json={"asset_sha256": asset["sha256"], "notice_version": cap["notice_version"]},
    )
    job = request(
        "POST",
        f"/projects/{project['id']}/jobs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "asset_id": asset["id"],
            "consent_id": consent["id"],
            "allow_unknown_cost": True,
            "budget_usd": 1,
        },
    )
    final = wait(job["id"])
    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "provider": "gemini",
        "requested_model": cap["model"],
        "sdk_version": importlib.metadata.version("google-genai"),
        "asset_sha256": asset["sha256"],
        "job": final,
        "result": "pass"
        if final["state"] in ("succeeded", "needs_review") and not final["cleanup_pending"]
        else "requires_attention",
        "quality_evaluation": "Not a substitute for the five-video manual rubric",
    }
    target = Path(__file__).resolve().parents[1] / "docs/live-smoke.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("Live smoke:", report["result"], "· Report:", target.name)
