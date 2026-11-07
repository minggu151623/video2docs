import json
import math
import os
import re
import signal
import subprocess
import time
from app.core.errors import AppError


def plan_chunks(duration, size=300, overlap=5):
    if not math.isfinite(duration) or duration < 0 or size <= 0 or not 0 <= overlap < size:
        raise ValueError("Invalid timeline settings")
    result, start = [], 0.0
    while start < duration:
        end = min(start + size, duration)
        result.append((start, end))
        if end == duration:
            break
        start += size - overlap
    return result


def run_process(args, timeout=30, check_cancel=lambda: None):
    import tempfile

    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(args, stdout=output, stderr=errors, start_new_session=True)
        except FileNotFoundError:
            raise AppError("FFMPEG_MISSING", "Cài FFmpeg và ffprobe trước khi xử lý video.", 503)
        started = time.monotonic()
        try:
            if hasattr(check_cancel, "register_process"):
                check_cancel.register_process(process.pid)
            while process.poll() is None:
                check_cancel()
                if time.monotonic() - started > timeout:
                    raise AppError("MEDIA_TIMEOUT", "Xử lý media vượt thời gian cho phép.", 503)
                if output.tell() + errors.tell() > 8 * 1024 * 1024:
                    raise AppError("MEDIA_OUTPUT_LIMIT", "Media tạo log vượt giới hạn.", 422)
                time.sleep(0.1)
            output.seek(0)
            errors.seek(0)
            stdout, stderr = output.read(8 * 1024 * 1024), errors.read(8 * 1024 * 1024)
            if process.returncode:
                raise AppError("MEDIA_INVALID", "FFmpeg không xử lý được media này.", 422)
            return stdout, stderr
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
        finally:
            if hasattr(check_cancel, "register_process"):
                check_cancel.register_process(None)


def probe(path, settings):
    try:
        data, _ = run_process(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )
    except FileNotFoundError:
        raise AppError("FFMPEG_MISSING", "Cài FFmpeg và ffprobe trước khi xử lý video.", 503)
    metadata = json.loads(data)
    video = next(
        (
            s
            for s in metadata.get("streams", [])
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    container = metadata.get("format", {}).get("format_name", "")
    if video is None or not any(x in container.split(",") for x in ("mov", "mp4", "matroska", "webm")):
        raise AppError("UNSUPPORTED_MEDIA", "Chỉ nhận MP4/MOV/WebM có video stream.", 415)
    with open(path, "rb") as stream:
        header = stream.read(32)
    if b"ftyp" not in header and header[:4] != b"\x1aE\xdf\xa3":
        raise AppError("UNSUPPORTED_MEDIA", "Chữ ký container không hợp lệ.", 415)
    duration = float(metadata["format"].get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise AppError("MEDIA_INVALID", "Không đo được thời lượng video.", 422)
    if duration > settings.max_video_seconds:
        raise AppError("VIDEO_TOO_LONG", "Video vượt giới hạn thời lượng.", 422)
    w, h = int(video.get("width", 0)), int(video.get("height", 0))
    if w <= 0 or h <= 0 or w * h > settings.max_video_pixels:
        raise AppError("RESOLUTION_LIMIT", "Độ phân giải video vượt giới hạn.", 422)
    return {
        "duration_sec": duration,
        "width": w,
        "height": h,
        "has_audio": int(any(s.get("codec_type") == "audio" for s in metadata["streams"])),
        "mime_type": "video/webm" if "webm" in container else "video/mp4",
        "timeline_map_json": json.dumps(
            {
                "source_start_time": float(metadata["format"].get("start_time", 0)),
                "normalized_start": 0,
                "rotation_applied": True,
            }
        ),
    }


UPLOAD_MAX_SIDE = 1280


def encode(source, target, start, end, check_cancel=lambda: None, upload=False):
    """Playback keeps full resolution for OCR and evidence frames; clips for the provider are downscaled,
    since the model samples frames at low resolution; a 2-minute CRF 18 1080p clip (~77 MB) broke the
    upload on a ~1 Mbps uplink while the same clip at 1280 px CRF 26 (~15 MB) went through."""
    scale = f"scale=w='min({UPLOAD_MAX_SIDE},iw)':h='min({UPLOAD_MAX_SIDE},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    try:
        run_process(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-protocol_whitelist",
                "file",
                "-threads",
                "2",
                "-i",
                str(source),
                "-ss",
                str(start),
                "-t",
                str(end - start),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                (scale if upload else "") + "setpts=PTS-STARTPTS",
                "-af",
                "asetpts=PTS-STARTPTS",
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "veryfast",
                "-crf",
                "26" if upload else "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                *(["-b:a", "96k"] if upload else []),
                "-movflags",
                "+faststart",
                "-fs",
                "1073741824",
                "-f",
                "mp4",
                str(partial),
            ],
            600,
            check_cancel,
        )
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


SEEK_PREROLL = 3.0  # seconds decoded before the wanted frame; the seek itself lands on a keyframe


def extract_frame(source, target, timestamp, check_cancel=lambda: None):
    """The first frame at or after `timestamp` as PNG; returns (its time, width, height).

    ffmpeg seeks to SEEK_PREROLL seconds before it and decodes from there (frame-accurate: it starts from
    the keyframe before the seek point and drops what comes earlier), instead of decoding the video from
    its start, which took 25-37 s per frame near the middle of a 9-minute 1080p video."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    start = max(0.0, timestamp - SEEK_PREROLL)
    try:
        _, stderr = run_process(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "info",
                "-y",
                "-protocol_whitelist",
                "file",
                "-threads",
                "2",
                "-ss",
                f"{start:.6f}",
                "-i",
                str(source),
                "-vf",
                f"select=gte(t\\,{timestamp - start:.6f}),scale=w='min(1920,iw)':h='min(1920,ih)':force_original_aspect_ratio=decrease,showinfo",
                "-frames:v",
                "1",
                "-threads",
                "2",
                "-f",
                "image2",
                "-c:v",
                "png",
                str(partial),
            ],
            60,
            check_cancel,
        )
        matches = re.findall(rb"pts_time:([0-9.e+\-]+)", stderr)
        if not matches or not partial.exists() or partial.stat().st_size == 0:
            raise AppError("FRAME_FAILED", "Không trích được frame tại mốc đã chọn.", 422)
        actual = start + float(matches[0])  # timestamps after an input seek count from `start`
        if abs(actual - timestamp) > 0.5:
            raise AppError("FRAME_TIMING", "Frame lệch quá 0,5 giây; hãy chọn mốc khác.", 422)
        os.replace(partial, target)
        import struct

        width, height = struct.unpack(">II", target.read_bytes()[16:24])
        return actual, width, height
    finally:
        partial.unlink(missing_ok=True)


def extract_audio(source, target, check_cancel, *, timeout):
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    try:
        run_process(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-protocol_whitelist",
                "file",
                "-threads",
                "2",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                str(partial),
            ],
            timeout,
            check_cancel,
        )
        if not partial.exists() or partial.stat().st_size == 0:
            raise AppError("MEDIA_INVALID", "Không trích được audio từ video này.", 422)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
