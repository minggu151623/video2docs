import logging
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.core.storage import sha256
from app.schemas.tutorial_v2 import TutorialDraftV2
from app.schemas.verification import Transcript, Word
from app.services.verification import pipeline

SHA = "a" * 64


def settings(tmp_path, **extra):
    values = dict(
        data_dir=tmp_path,
        database_url="sqlite:///" + str(tmp_path / "app.sqlite3"),
        ai_provider="mock",
        asr_engine="faster-whisper",
        ocr_engine="paddleocr",
    )
    return Settings(**{**values, **extra})


def asset(has_audio=1, duration=10.0):
    return NS(sha256=SHA, has_audio=has_audio, playback_path="playback.mp4", duration_sec=duration)


def span(source, start=2.0, end=8.0):
    return {"start_sec": start, "end_sec": end, "source": source, "description": "Nguồn"}


def material(name, quantity, basis, *, quote=None, screen=None, spans=None):
    return {
        "name": name,
        "quantity": quantity,
        "unit": "g",
        "note": None,
        "evidence_spans": spans or [span("audio" if basis == "stated" else "visual")],
        "basis": basis,
        "quote": quote,
        "on_screen_text": screen,
    }


def draft(*materials):
    return TutorialDraftV2.model_validate(
        {
            "schema_version": "2.0",
            "is_tutorial": True,
            "not_tutorial_reason": None,
            "domain": "cooking",
            "yield": None,
            "title": "Bánh",
            "summary": "",
            "language": "vi",
            "objectives": [],
            "prerequisites": [],
            "safety": [],
            "materials": list(materials),
            "equipment": [],
            "steps": [
                {
                    "local_id": "s1",
                    "title": "Trộn",
                    "start_sec": 0,
                    "end_sec": 10,
                    "actions": ["Trộn bột"],
                    "expected_result": None,
                    "parameters": [],
                    "exact_inputs": [],
                    "warnings": [],
                    "tips": [],
                    "evidence_spans": [span("both", 0, 10)],
                    "screenshot_candidates_sec": [],
                    "needs_review": False,
                    "review_reason": None,
                }
            ],
            "troubleshooting": [],
            "uncertainties": [],
        },
        context={"duration": 10},
    )


SPOKEN = material("Đường", "50", "stated", quote="thêm 50 g đường vào bát")
SCREEN = material("Bột mì", "200", "observed", screen="Bột mì 200 g")
TRANSCRIPT = Transcript(
    language="vi",
    words=[
        Word(start=3 + i * 0.3, end=3.2 + i * 0.3, text=w)
        for i, w in enumerate("thêm 50 g đường vào bát".split())
    ],
)


class FakeASR:
    def __init__(self, transcript=TRANSCRIPT, error=None):
        self.transcript, self.error, self.calls = transcript, error, 0

    def transcribe(self, audio, check_cancel):
        self.calls += 1
        assert Path(audio).is_file()
        if self.error:
            raise self.error
        return self.transcript


class FakeOCR:
    def __init__(self, text="Bột mì 200 g", delay=0.0, error=None):
        self.text, self.delay, self.error, self.calls = text, delay, error, []

    def read(self, image, language=None):
        self.calls.append((Path(image).name, language))
        if self.error:
            raise self.error
        time.sleep(self.delay)
        return self.text


@pytest.fixture
def media(monkeypatch):
    calls = {"audio": [], "frames": []}

    def extract_audio(source, target, check_cancel, *, timeout):
        calls["audio"].append((target, timeout))
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(b"RIFF")

    def extract_frame(source, target, timestamp, check_cancel=lambda: None):
        calls["frames"].append(timestamp)
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(b"png")
        return timestamp, 10, 10

    monkeypatch.setattr(pipeline, "extract_audio", extract_audio)
    monkeypatch.setattr(pipeline, "extract_frame", extract_frame)
    return calls


def use(monkeypatch, asr=None, ocr=None):
    monkeypatch.setattr(pipeline, "get_asr", lambda cfg: asr)
    monkeypatch.setattr(pipeline, "get_ocr", lambda cfg: ocr)


def test_transcript_cache_path_names_asset_and_asr_config(tmp_path):
    cfg = settings(tmp_path, asr_model="small")
    key = sha256(b"faster-whispersmall")[:12]
    assert pipeline.transcript_cache_path(SHA, cfg) == f"transcripts/{SHA}-{key}.json"


def test_transcript_cached_per_asset_and_asr_config(tmp_path, monkeypatch, media):
    fake = FakeASR()
    use(monkeypatch, asr=fake)
    cfg = settings(tmp_path)
    assert pipeline.ensure_transcript(cfg, asset(), lambda: None) == (TRANSCRIPT, "ok")
    assert (tmp_path / pipeline.transcript_cache_path(SHA, cfg)).is_file()
    assert pipeline.ensure_transcript(cfg, asset(), lambda: None) == (TRANSCRIPT, "ok")
    assert fake.calls == 1 and len(media["audio"]) == 1
    assert media["audio"][0][1] == cfg.asr_timeout_seconds
    wav = media["audio"][0][0]
    assert wav.is_relative_to(tmp_path / "transcripts" / "work")  # inside DATA_DIR without a job workdir
    assert not wav.exists()  # the temporary WAV is removed
    other = settings(tmp_path, asr_model="medium")
    assert pipeline.ensure_transcript(other, asset(), lambda: None) == (TRANSCRIPT, "ok")
    assert fake.calls == 2


def test_corrupt_transcript_cache_is_recomputed(tmp_path, monkeypatch, media):
    fake = FakeASR()
    use(monkeypatch, asr=fake)
    cfg = settings(tmp_path)
    cache = tmp_path / pipeline.transcript_cache_path(SHA, cfg)
    cache.parent.mkdir(parents=True)
    cache.write_text("{not json")
    assert pipeline.ensure_transcript(cfg, asset(), lambda: None) == (TRANSCRIPT, "ok")
    assert fake.calls == 1
    assert Transcript.model_validate_json(cache.read_bytes()) == TRANSCRIPT


def test_no_audio_skips_asr(tmp_path, monkeypatch, media):
    fake = FakeASR()
    use(monkeypatch, asr=fake)
    cfg = settings(tmp_path)
    assert pipeline.ensure_transcript(cfg, asset(has_audio=0), lambda: None) == (None, "skipped")
    assert not media["audio"] and fake.calls == 0
    report = pipeline.run_verification(
        cfg, asset(has_audio=0), draft(SPOKEN), None, "skipped", tmp_path, lambda: None
    )
    assert report.asr_status == "skipped" and report.asr_error is None
    assert report.items["materials/0"].status == "not_checked"
    assert report.items["materials/0"].reason == "video không có track âm thanh"


def test_asr_engine_none_is_skipped(tmp_path, monkeypatch, media):
    use(monkeypatch, asr=FakeASR())
    assert pipeline.ensure_transcript(settings(tmp_path, asr_engine="none"), asset(), lambda: None) == (
        None,
        "skipped",
    )
    assert not media["audio"]
    cfg = settings(tmp_path, asr_engine="none")
    report = pipeline.run_verification(cfg, asset(), draft(SPOKEN), None, "skipped", tmp_path, lambda: None)
    assert report.items["materials/0"].reason == "ASR đang tắt"


@pytest.mark.parametrize(
    "error, code, kind, reason",
    [
        (RuntimeError("boom"), "ASR_INTERNAL_ERROR", "RuntimeError", "ASR lỗi (ASR_INTERNAL_ERROR)"),
        (AppError("ASR_FAILED", "x", 503), "ASR_FAILED", None, "ASR lỗi (ASR_FAILED)"),
        (AppError("ASR_TIMEOUT", "x", 503), "ASR_TIMEOUT", None, "hết thời gian ASR (ASR_TIMEOUT)"),
    ],
)
def test_asr_failure_does_not_raise(tmp_path, monkeypatch, media, caplog, error, code, kind, reason):
    use(monkeypatch, asr=FakeASR(error=error))
    cfg = settings(tmp_path)
    work = tmp_path / "projects" / "p" / "derived" / "job" / "verification"
    with caplog.at_level(logging.WARNING, logger="video2docs.verification"):
        assert pipeline.transcribe_asset(cfg, asset(), lambda: None, work) == (None, "failed", code)
    assert code in caplog.text and (kind is None or kind in caplog.text)
    assert not (tmp_path / pipeline.transcript_cache_path(SHA, cfg)).exists()
    wav = media["audio"][0][0]
    assert wav.is_relative_to(work) and not wav.exists()
    report = pipeline.run_verification(
        cfg, asset(), draft(SPOKEN), None, "failed", tmp_path, lambda: None, code
    )
    assert report.asr_error == code
    assert report.items["materials/0"].status == "not_checked"
    assert report.items["materials/0"].reason == reason
    assert pipeline.degraded_warning(report) == {
        "code": "VERIFICATION_DEGRADED",
        "asr": "failed",
        "ocr": "skipped",
        "asr_error": code,
        "ocr_error": None,
    }


@pytest.mark.parametrize("code", ["MEDIA_TIMEOUT", "MEDIA_INVALID"])
def test_audio_extraction_failure_does_not_raise(tmp_path, monkeypatch, code):
    fake = FakeASR()
    use(monkeypatch, asr=fake)

    def broken(source, target, check_cancel, *, timeout):
        raise AppError(code, "x", 422)

    monkeypatch.setattr(pipeline, "extract_audio", broken)
    assert pipeline.transcribe_asset(settings(tmp_path), asset(), lambda: None) == (None, "failed", code)
    assert pipeline.ensure_transcript(settings(tmp_path), asset(), lambda: None) == (None, "failed")
    assert fake.calls == 0


@pytest.mark.parametrize("code", ["CANCELLED", "LEASE_LOST", "JOB_TIMEOUT"])
def test_asr_stop_signals_propagate(tmp_path, monkeypatch, media, code):
    use(monkeypatch, asr=FakeASR(error=AppError(code, "x", 409)))
    with pytest.raises(AppError) as raised:
        pipeline.ensure_transcript(settings(tmp_path), asset(), lambda: None)
    assert raised.value.code == code


def test_ocr_samples_at_most_three_frames_inside_evidence(tmp_path, monkeypatch, media):
    ocr = FakeOCR()
    use(monkeypatch, ocr=ocr)
    cfg = settings(tmp_path)
    same_span = material("Bơ", "200", "observed", screen="Bột mì 200 g")
    at_end = material("Bột mì", "200", "observed", screen="Bột mì 200 g", spans=[span("both", 6, 10)])
    report = pipeline.run_verification(
        cfg, asset(), draft(SCREEN, same_span, at_end), TRANSCRIPT, "ok", tmp_path / "work", lambda: None
    )
    assert report.ocr_status == "ok"
    assert report.items["materials/0"].status == "verified"
    assert report.items["materials/0"].method == "ocr"
    assert report.items["materials/2"].status == "verified"
    first = media["frames"][:3]
    assert first == [2.0, 5.0, 8.0]  # start, middle, end; the identical span is not extracted twice
    assert media["frames"][3:] == [6.0, 9.5]  # 8.0 reused, end clamped inside the video
    assert all(t < 10 for t in media["frames"])
    assert len(ocr.calls) == len(media["frames"]) == 5
    assert {language for _, language in ocr.calls} == {"vi"}
    assert not (tmp_path / "work").exists() or not any((tmp_path / "work").iterdir())


def test_ocr_frames_respect_configured_maximum(tmp_path, monkeypatch, media):
    use(monkeypatch, ocr=FakeOCR())
    two_spans = material(
        "Bột mì", "200", "observed", screen="Bột mì 200 g", spans=[span("visual", 0, 2), span("both", 4, 6)]
    )
    pipeline.run_verification(
        settings(tmp_path, verify_max_ocr_frames=2),
        asset(),
        draft(two_spans),
        None,
        "skipped",
        tmp_path,
        lambda: None,
    )
    assert len(media["frames"]) == 2


def test_ocr_skipped_without_engine_or_need(tmp_path, monkeypatch, media):
    use(monkeypatch, ocr=None)
    report = pipeline.run_verification(
        settings(tmp_path), asset(), draft(SCREEN), None, "ok", tmp_path, lambda: None
    )
    assert report.ocr_status == "skipped" and report.items["materials/0"].status == "not_checked"
    use(monkeypatch, ocr=FakeOCR())
    report = pipeline.run_verification(
        settings(tmp_path), asset(), draft(SPOKEN), TRANSCRIPT, "ok", tmp_path, lambda: None
    )
    assert report.ocr_status == "skipped" and not media["frames"]
    assert report.items["materials/0"].status == "verified"


def test_ocr_budget_exhaustion_marks_remaining_not_checked(tmp_path, monkeypatch, media):
    use(monkeypatch, ocr=FakeOCR(delay=1.1))
    report = pipeline.run_verification(
        settings(tmp_path, ocr_timeout_seconds=1),
        asset(),
        draft(SCREEN, SPOKEN),
        TRANSCRIPT,
        "ok",
        tmp_path,
        lambda: None,
    )
    assert len(media["frames"]) == 1
    assert report.ocr_status == "failed"
    assert report.items["materials/0"].status == "not_checked"
    assert report.items["materials/0"].reason == "hết thời gian OCR"
    assert report.items["materials/1"].status == "verified"
    assert pipeline.degraded_warning(report) == {
        "code": "VERIFICATION_DEGRADED",
        "asr": "ok",
        "ocr": "failed",
        "asr_error": None,
        "ocr_error": "OCR_TIMEOUT",
    }
    assert pipeline.needs_review(report)


@pytest.mark.parametrize(
    "error, code, kind",
    [
        (AppError("OCR_FAILED", "x", 503), "OCR_FAILED", None),
        (KeyError("rec_texts"), "OCR_INTERNAL_ERROR", "KeyError"),
    ],
)
def test_ocr_failure_does_not_raise(tmp_path, monkeypatch, media, caplog, error, code, kind):
    use(monkeypatch, ocr=FakeOCR(error=error))
    with caplog.at_level(logging.WARNING, logger="video2docs.verification"):
        report = pipeline.run_verification(
            settings(tmp_path), asset(), draft(SCREEN), None, "skipped", tmp_path, lambda: None
        )
    assert code in caplog.text and (kind is None or kind in caplog.text)
    assert report.ocr_status == "failed" and report.ocr_error == code
    assert report.items["materials/0"].status == "not_checked"
    assert report.items["materials/0"].reason == f"OCR lỗi ({code})"
    assert pipeline.degraded_warning(report)["ocr_error"] == code


def test_ocr_checks_cancellation_between_frames(tmp_path, monkeypatch, media):
    use(monkeypatch, ocr=FakeOCR())
    calls = []

    def cancel():
        calls.append(1)
        if len(calls) > 1:
            raise AppError("CANCELLED", "x")

    with pytest.raises(AppError):
        pipeline.run_verification(
            settings(tmp_path), asset(), draft(SCREEN), None, "skipped", tmp_path, cancel
        )
    assert len(media["frames"]) == 1


def test_frame_extraction_failure_leaves_item_not_checked(tmp_path, monkeypatch, caplog):
    use(monkeypatch, ocr=FakeOCR())

    def broken(source, target, timestamp, check_cancel=lambda: None):
        raise AppError("FRAME_FAILED", "x", 422)

    monkeypatch.setattr(pipeline, "extract_frame", broken)
    with caplog.at_level(logging.WARNING, logger="video2docs.verification"):
        report = pipeline.run_verification(
            settings(tmp_path), asset(), draft(SCREEN), None, "skipped", tmp_path, lambda: None
        )
    assert "FRAME_FAILED" in caplog.text
    assert report.ocr_status == "failed" and report.ocr_error == "NO_FRAME"
    assert report.items["materials/0"].status == "not_checked"
    assert pipeline.degraded_warning(report) == {
        "code": "VERIFICATION_DEGRADED",
        "asr": "skipped",
        "ocr": "failed",
        "asr_error": None,
        "ocr_error": "NO_FRAME",
    }


def test_observed_item_without_visual_span_is_unverified_by_matcher(tmp_path, monkeypatch, media):
    use(monkeypatch, ocr=FakeOCR())
    built = draft(SCREEN)
    built.materials[0].evidence_spans = built.steps[0].evidence_spans[:0] + [
        built.steps[0].evidence_spans[0].model_copy(update={"source": "audio"})
    ]
    report = pipeline.run_verification(
        settings(tmp_path), asset(), built, None, "skipped", tmp_path, lambda: None
    )
    item = report.items["materials/0"]
    assert (item.status, item.method, item.reason) == (
        "unverified",
        "ocr",
        "không có khoảng bằng chứng phù hợp",
    )
    assert not media["frames"] and report.ocr_status == "ok"


def test_report_review_and_degraded_rules(tmp_path, monkeypatch, media):
    use(monkeypatch, ocr=FakeOCR())
    report = pipeline.run_verification(
        settings(tmp_path), asset(), draft(SCREEN, SPOKEN), TRANSCRIPT, "ok", tmp_path, lambda: None
    )
    assert not pipeline.needs_review(report) and pipeline.degraded_warning(report) is None
    failed = report.model_copy(update={"asr_status": "failed"})
    assert pipeline.degraded_warning(failed) == {
        "code": "VERIFICATION_DEGRADED",
        "asr": "failed",
        "ocr": "ok",
        "asr_error": None,
        "ocr_error": None,
    }


def test_draft_language_reaches_the_matcher(tmp_path, monkeypatch, media):
    # ruling I2/C3a: the name check runs because the draft and the transcript are both Vietnamese
    use(monkeypatch)
    cfg = settings(tmp_path, ocr_engine="none")
    wrong = material("Muối", "50", "stated", quote="thêm 50 g đường vào bát")
    report = pipeline.run_verification(
        cfg, asset(), draft(SPOKEN, wrong), TRANSCRIPT, "ok", tmp_path, lambda: None
    )
    assert report.items["materials/0"].status == "verified"
    assert report.items["materials/1"].status == "unverified"
