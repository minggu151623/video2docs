"""Verification step of the worker (spec 3.1, 3.4): local ASR and selective OCR, then the matcher.

Nothing here calls the AI provider, so a generation can be re-verified for free. ASR or OCR trouble
never fails the job: the affected items become `not_checked` and the report says which source failed.
Only the worker's own stop signals (cancel, lost lease, job timeout, disk/storage guards) propagate."""

import logging
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

LOG = logging.getLogger("video2docs.verification")
Status = Literal["ok", "skipped", "failed"]
STOP = {"CANCELLED", "LEASE_LOST", "JOB_TIMEOUT", "DISK_FULL", "STORAGE_LIMIT"}
REVIEW = {"unverified", "not_checked"}
EOF_MARGIN = 0.5  # same distance from the end as screenshot fallbacks; frame timing tolerates 0.5 s
NO_FRAME = "không trích được khung hình để OCR"
TIMEOUTS = {"ASR_TIMEOUT", "MEDIA_TIMEOUT"}


def _stop(error: BaseException) -> bool:
    return isinstance(error, AppError) and error.code in STOP


def _code(error: BaseException, fallback: str) -> str:
    """The AppError code, or `fallback` for an unexpected exception (a bug or an engine crash)."""
    return error.code if isinstance(error, AppError) else fallback


def _log(source: str, error: BaseException, code: str):
    kind = "" if isinstance(error, AppError) else f" ({type(error).__name__})"
    LOG.warning("%s verification degraded: %s%s", source, code, kind, exc_info=False)


def transcript_cache_path(asset_sha256: str, settings) -> str:
    config = sha256((settings.asr_engine + settings.asr_model).encode())[:12]
    return f"transcripts/{asset_sha256}-{config}.json"


def transcribe_asset(
    settings, asset, check_cancel, workdir: Path | None = None
) -> tuple[Transcript | None, Status, str | None]:
    """(transcript, status, error code). The temporary WAV stays inside DATA_DIR: in `workdir` (the
    job's derived folder, removed when the job ends) or, without one, under `transcripts/work`."""
    if settings.asr_engine == "none" or asset.has_audio == 0:
        return None, "skipped", None
    cache = safe_path(settings.data_dir, transcript_cache_path(asset.sha256, settings))
    if cache.is_file():
        try:
            return Transcript.model_validate_json(cache.read_bytes()), "ok", None
        except (ValidationError, ValueError, OSError):
            LOG.warning("Unreadable transcript cache %s; recomputing", cache.name)
    asr = get_asr(settings)
    if asr is None:
        return None, "skipped", None
    source = safe_path(settings.data_dir, asset.playback_path)
    workdir = workdir or safe_path(settings.data_dir, "transcripts/work")
    workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    scratch = Path(tempfile.mkdtemp(prefix="asr-", dir=workdir))
    try:
        audio = scratch / "audio.wav"
        extract_audio(source, audio, check_cancel, timeout=settings.asr_timeout_seconds)
        transcript = asr.transcribe(audio, check_cancel)
    except Exception as error:
        if _stop(error):
            raise
        code = _code(error, "ASR_INTERNAL_ERROR")
        _log("ASR", error, code)
        return None, "failed", code
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    atomic_write(cache, transcript.model_dump_json().encode())
    return transcript, "ok", None


def ensure_transcript(
    settings, asset, check_cancel, workdir: Path | None = None
) -> tuple[Transcript | None, Status]:
    transcript, status, _ = transcribe_asset(settings, asset, check_cancel, workdir)
    return transcript, status


def no_transcript_reason(settings, asset, asr_status: Status, asr_error: str | None) -> str:
    """Why a spoken item could not be checked, more specific than the matcher's generic reason."""
    if asr_status == "failed":
        if asr_error in TIMEOUTS:
            return f"hết thời gian ASR ({asr_error})"
        return f"ASR lỗi ({asr_error or 'ASR_FAILED'})"
    if asset.has_audio == 0:
        return "video không có track âm thanh"
    if settings.asr_engine == "none":
        return "ASR đang tắt"
    return "không có bản ghi lời nói"


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
    asr_error: str | None = None,
) -> VerificationReport:
    items = list(iter_grounded_items(draft))
    results = {path: verify_item(path, item, transcript, None, settings) for path, _, item in items}
    if transcript is None:
        reason = no_transcript_reason(settings, asset, asr_status, asr_error)
        for path, result in results.items():
            if result.status == "not_checked" and result.method == "asr":
                results[path] = result.model_copy(update={"reason": reason})
    asr_error = asr_error if asr_status == "failed" else None
    pending = [
        (path, item)
        for path, _, item in items
        if results[path].status == "not_checked" and results[path].method == "ocr"
    ]
    ocr = get_ocr(settings) if pending else None
    if ocr is None:
        return VerificationReport(
            items=results, asr_status=asr_status, ocr_status="skipped", asr_error=asr_error
        )
    failure = None  # (error code, item reason) once OCR has stopped
    missing = False  # some item got no frame at all
    language = transcript.language if transcript else None
    source = safe_path(settings.data_dir, asset.playback_path)
    workdir.mkdir(parents=True, exist_ok=True)
    frames = Path(tempfile.mkdtemp(prefix="ocr-", dir=workdir))
    texts: dict[float, tuple[float, str] | None] = {}  # one OCR per second within this run
    started = time.monotonic()
    try:
        for path, item in pending:
            seconds = ocr_seconds(item, asset.duration_sec, settings.verify_max_ocr_frames)
            if not seconds:  # no visual span: the matcher gives the precise `unverified` reason
                results[path] = verify_item(path, item, transcript, [], settings)
                continue
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
                            _log("OCR frame", error, error.code)
                            texts[second] = None  # this frame is missing; the others still count
                            continue
                        texts[second] = (actual, ocr.read(image, language))
                        image.unlink(missing_ok=True)
                except _Budget:
                    LOG.warning(
                        "OCR verification degraded: OCR_TIMEOUT after %s s", settings.ocr_timeout_seconds
                    )
                    failure = ("OCR_TIMEOUT", "hết thời gian OCR")
                except Exception as error:
                    if _stop(error):
                        raise
                    code = _code(error, "OCR_INTERNAL_ERROR")
                    _log("OCR", error, code)
                    failure = (code, f"OCR lỗi ({code})")
            if failure is not None:
                results[path] = ItemVerification(status="not_checked", method="ocr", reason=failure[1])
                continue
            read = [texts[s] for s in seconds if texts.get(s) is not None]
            if read:
                results[path] = verify_item(path, item, transcript, read, settings)
            else:
                missing = True
                results[path] = ItemVerification(status="not_checked", method="ocr", reason=NO_FRAME)
    finally:
        shutil.rmtree(frames, ignore_errors=True)
    ocr_error = failure[0] if failure else "NO_FRAME" if missing else None
    return VerificationReport(
        items=results,
        asr_status=asr_status,
        ocr_status="failed" if ocr_error else "ok",
        asr_error=asr_error,
        ocr_error=ocr_error,
    )


def needs_review(report: VerificationReport) -> bool:
    return any(result.status in REVIEW for result in report.items.values())


def degraded_warning(report: VerificationReport) -> dict | None:
    if "failed" in (report.asr_status, report.ocr_status):
        return {
            "code": "VERIFICATION_DEGRADED",
            "asr": report.asr_status,
            "ocr": report.ocr_status,
            "asr_error": report.asr_error,
            "ocr_error": report.ocr_error,
        }
    return None


def report_path(project_id: str, generation_id: str) -> str:
    return f"projects/{project_id}/generations/{generation_id}/verification.json"


def save_report(settings, project_id: str, generation_id: str, report: VerificationReport) -> str:
    rel = report_path(project_id, generation_id)
    atomic_write(safe_path(settings.data_dir, rel), report.model_dump_json().encode())
    return rel
