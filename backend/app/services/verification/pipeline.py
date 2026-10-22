"""Verification step of the worker (spec 3.1, 3.4): local ASR and selective OCR, then the matcher.

Nothing here calls the AI provider, so a generation can be re-verified for free. ASR or OCR trouble
never fails the job: the affected items become `not_checked` and the report says which source failed.
Only the worker's own stop signals (cancel, lost lease, job timeout, disk/storage guards) propagate."""

import shutil
import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.core.errors import AppError
from app.core.storage import atomic_write, safe_path, sha256
from app.schemas.tutorial_v2 import TutorialDraftV2
from app.schemas.verification import ItemVerification, Transcript, VerificationReport
from app.services.media import extract_audio, extract_frame
from app.services.verification.asr import get_asr
from app.services.verification.matcher import iter_grounded_items, verify_item
from app.services.verification.ocr import get_ocr

Status = Literal["ok", "skipped", "failed"]
STOP = {"CANCELLED", "LEASE_LOST", "JOB_TIMEOUT", "DISK_FULL", "STORAGE_LIMIT"}
REVIEW = {"unverified", "not_checked"}
EOF_MARGIN = 0.5  # same distance from the end as screenshot fallbacks; frame timing tolerates 0.5 s
OCR_TIMEOUT, OCR_ERROR, NO_FRAME = "hết thời gian OCR", "OCR lỗi", "không trích được khung hình để OCR"


def _stop(error: BaseException) -> bool:
    return isinstance(error, AppError) and error.code in STOP


def transcript_cache_path(asset_sha256: str, settings) -> str:
    config = sha256((settings.asr_engine + settings.asr_model).encode())[:12]
    return f"transcripts/{asset_sha256}-{config}.json"


def ensure_transcript(settings, asset, check_cancel) -> tuple[Transcript | None, Status]:
    if settings.asr_engine == "none" or asset.has_audio == 0:
        return None, "skipped"
    cache = safe_path(settings.data_dir, transcript_cache_path(asset.sha256, settings))
    if cache.is_file():
        try:
            return Transcript.model_validate_json(cache.read_bytes()), "ok"
        except (ValidationError, ValueError, OSError):
            pass  # unreadable cache: recompute and overwrite it
    asr = get_asr(settings)
    if asr is None:
        return None, "skipped"
    source = safe_path(settings.data_dir, asset.playback_path)
    workdir = Path(tempfile.mkdtemp(prefix="video2docs-asr-"))
    try:
        audio = workdir / "audio.wav"
        extract_audio(source, audio, check_cancel, timeout=settings.asr_timeout_seconds)
        transcript = asr.transcribe(audio, check_cancel)
    except Exception as error:
        if _stop(error):
            raise
        return None, "failed"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    atomic_write(cache, transcript.model_dump_json().encode())
    return transcript, "ok"


def ocr_seconds(item, duration: float, limit: int) -> list[float]:
    """Start, middle and end of each visual span, inside the video, at most `limit` evenly spread."""
    last = max(0.0, duration - EOF_MARGIN)
    found = set()
    for span in item.evidence_spans:
        if span.source in ("visual", "both"):
            for t in (span.start_sec, (span.start_sec + span.end_sec) / 2, span.end_sec):
                found.add(round(min(max(t, 0.0), last), 3))
    seconds = sorted(found)
    if len(seconds) <= limit:
        return seconds
    if limit == 1:
        return [seconds[len(seconds) // 2]]
    return [seconds[round(i * (len(seconds) - 1) / (limit - 1))] for i in range(limit)]


class _Budget(Exception):
    pass


def run_verification(
    settings,
    asset,
    draft: TutorialDraftV2,
    transcript: Transcript | None,
    asr_status: Status,
    workdir: Path,
    check_cancel,
) -> VerificationReport:
    items = list(iter_grounded_items(draft))
    results = {path: verify_item(path, item, transcript, None, settings) for path, _, item in items}
    pending = [
        (path, item)
        for path, _, item in items
        if results[path].status == "not_checked" and results[path].method == "ocr"
    ]
    ocr = get_ocr(settings) if pending else None
    if ocr is None:
        return VerificationReport(items=results, asr_status=asr_status, ocr_status="skipped")
    ocr_status: Status = "ok"
    failure = None
    language = transcript.language if transcript else None
    source = safe_path(settings.data_dir, asset.playback_path)
    workdir.mkdir(parents=True, exist_ok=True)
    frames = Path(tempfile.mkdtemp(prefix="ocr-", dir=workdir))
    texts: dict[float, tuple[float, str] | None] = {}  # one OCR per second within this run
    started = time.monotonic()
    try:
        for path, item in pending:
            seconds = ocr_seconds(item, asset.duration_sec, settings.verify_max_ocr_frames)
            if failure is None:
                try:
                    for second in seconds:
                        if second in texts:
                            continue
                        check_cancel()
                        if time.monotonic() - started >= settings.ocr_timeout_seconds:
                            raise _Budget
                        image = frames / f"{len(texts)}.png"
                        try:
                            actual, _, _ = extract_frame(source, image, second, check_cancel)
                        except AppError as error:
                            if _stop(error):
                                raise
                            texts[second] = None  # this frame is missing; the others still count
                            continue
                        texts[second] = (actual, ocr.read(image, language))
                        image.unlink(missing_ok=True)
                except _Budget:
                    failure = OCR_TIMEOUT
                except Exception as error:
                    if _stop(error):
                        raise
                    failure = OCR_ERROR
            if failure is not None:
                ocr_status = "failed"
                results[path] = ItemVerification(status="not_checked", method="ocr", reason=failure)
                continue
            read = [texts[s] for s in seconds if texts.get(s) is not None]
            results[path] = (
                verify_item(path, item, transcript, read, settings)
                if read
                else ItemVerification(status="not_checked", method="ocr", reason=NO_FRAME)
            )
    finally:
        shutil.rmtree(frames, ignore_errors=True)
    return VerificationReport(items=results, asr_status=asr_status, ocr_status=ocr_status)


def needs_review(report: VerificationReport) -> bool:
    return any(result.status in REVIEW for result in report.items.values())


def degraded_warning(report: VerificationReport) -> dict | None:
    if "failed" in (report.asr_status, report.ocr_status):
        return {"code": "VERIFICATION_DEGRADED", "asr": report.asr_status, "ocr": report.ocr_status}
    return None


def report_path(project_id: str, generation_id: str) -> str:
    return f"projects/{project_id}/generations/{generation_id}/verification.json"


def save_report(settings, project_id: str, generation_id: str, report: VerificationReport) -> str:
    rel = report_path(project_id, generation_id)
    atomic_write(safe_path(settings.data_dir, rel), report.model_dump_json().encode())
    return rel
