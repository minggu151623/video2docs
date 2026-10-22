import shutil
import subprocess
import sys
import time
import types
import wave
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.verification import Transcript
from app.services import media
from app.services.verification import asr as asr_module
from app.services.verification import ocr as ocr_module
from app.services.verification.asr import ASR, get_asr
from app.services.verification.ocr import OCR, get_ocr

ROOT = Path(__file__).resolve().parents[3]
SPIKE_FRAMES = ROOT / "tmp" / "ocr-spike" / "frames"


def make_tone_clip(path: Path):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )
    return path


def test_engines_can_be_disabled():
    assert get_asr(Settings(asr_engine="none")) is None
    assert get_ocr(Settings(ocr_engine="none")) is None
    assert isinstance(get_asr(Settings()), ASR)
    assert isinstance(get_ocr(Settings()), OCR)


def test_engine_settings_are_validated_and_snapshotted():
    with pytest.raises(ValidationError):
        Settings(asr_engine="whisper-x")
    with pytest.raises(ValidationError):
        Settings(ocr_engine="tesseract")
    for field in ("asr_timeout_seconds", "ocr_timeout_seconds"):
        with pytest.raises(ValidationError):
            Settings(**{field: 0})
    settings = Settings()
    assert (settings.asr_engine, settings.asr_model, settings.asr_timeout_seconds) == (
        "faster-whisper",
        "small",
        1200,
    )
    assert (settings.ocr_engine, settings.ocr_timeout_seconds) == ("paddleocr", 300)
    snapshot = settings.snapshot()
    for key in ("asr_engine", "asr_model", "asr_timeout_seconds", "ocr_engine", "ocr_timeout_seconds"):
        assert key in snapshot
    assert "verify_input_threshold" not in snapshot


def test_extract_audio_writes_16khz_mono_wav(tmp_path):
    source = make_tone_clip(tmp_path / "tone.mp4")
    target = tmp_path / "out" / "audio.wav"
    media.extract_audio(source, target, lambda: None)
    with wave.open(str(target)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert 1.5 < wav.getnframes() / 16000 < 2.5
    assert not target.with_suffix(".partial").exists()


def test_extract_audio_on_fixture_without_audio_fails_cleanly(tmp_path):
    target = tmp_path / "audio.wav"
    with pytest.raises(AppError) as error:
        media.extract_audio(ROOT / "fixtures" / "synthetic_tutorial.mp4", target, lambda: None)
    assert error.value.code == "MEDIA_INVALID"
    assert not target.exists() and not target.with_suffix(".partial").exists()


def test_extract_audio_honours_cancellation(tmp_path):
    source = make_tone_clip(tmp_path / "tone.mp4")

    def cancel():
        raise AppError("CANCELLED", "stop", 409)

    with pytest.raises(AppError) as error:
        media.extract_audio(source, tmp_path / "audio.wav", cancel)
    assert error.value.code == "CANCELLED"


class FakeWord:
    def __init__(self, start, end, word):
        self.start, self.end, self.word = start, end, word


class FakeSegment:
    def __init__(self, words):
        self.words = words


class FakeModel:
    def __init__(self, segments, language="en", delay=0.0):
        self.segments, self.language, self.delay = segments, language, delay
        self.calls = []
        self.yielded = 0

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))

        def generate():
            for segment in self.segments:
                time.sleep(self.delay)
                self.yielded += 1
                yield segment

        return generate(), types.SimpleNamespace(language=self.language)


def asr_with(model, **settings):
    adapter = ASR(Settings(**settings))
    adapter._model = model
    return adapter


def test_asr_returns_word_timestamps_and_language(tmp_path):
    model = FakeModel(
        [
            FakeSegment([FakeWord(0.0, 0.4, " Chạy"), FakeWord(0.4, 0.9, " lệnh"), FakeWord(0.9, 1.0, " ")]),
            FakeSegment(None),
            FakeSegment([FakeWord(2.0, 2.5, " python")]),
        ],
        language="vi",
    )
    transcript = asr_with(model).transcribe(tmp_path / "a.wav", lambda: None)
    assert isinstance(transcript, Transcript)
    assert transcript.language == "vi"
    assert [(w.start, w.end, w.text) for w in transcript.words] == [
        (0.0, 0.4, "Chạy"),
        (0.4, 0.9, "lệnh"),
        (2.0, 2.5, "python"),
    ]
    options = model.calls[0][1]
    assert options["word_timestamps"] is True and options["vad_filter"] is True
    assert options.get("language") is None


def test_asr_calls_check_cancel_per_segment(tmp_path):
    segments = [FakeSegment([FakeWord(i, i + 0.5, "w")]) for i in range(3)]
    seen = []
    asr_with(FakeModel(segments)).transcribe(tmp_path / "a.wav", lambda: seen.append(1))
    assert len(seen) >= 3


def test_asr_cancellation_stops_iteration(tmp_path):
    model = FakeModel([FakeSegment([FakeWord(i, i + 0.5, "w")]) for i in range(5)])

    def cancel():
        if model.yielded >= 2:
            raise AppError("CANCELLED", "stop", 409)

    with pytest.raises(AppError) as error:
        asr_with(model).transcribe(tmp_path / "a.wav", cancel)
    assert error.value.code == "CANCELLED"
    assert model.yielded == 2


def test_asr_timeout_on_slow_segments(tmp_path):
    model = FakeModel([FakeSegment([FakeWord(i, i + 0.5, "w")]) for i in range(5)], delay=0.7)
    started = time.monotonic()
    with pytest.raises(AppError) as error:
        asr_with(model, asr_timeout_seconds=1).transcribe(tmp_path / "a.wav", lambda: None)
    assert error.value.code == "ASR_TIMEOUT"
    assert model.yielded < 5
    assert time.monotonic() - started < 3


def test_asr_model_is_created_lazily_and_once(monkeypatch, tmp_path):
    created = []

    class FakeWhisperModel(FakeModel):
        def __init__(self, name, device, compute_type):
            super().__init__([FakeSegment([FakeWord(0, 1, "x")])])
            created.append((name, device, compute_type))

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    adapter = ASR(Settings(asr_model="tiny"))
    assert created == []
    adapter.transcribe(tmp_path / "a.wav", lambda: None)
    adapter.transcribe(tmp_path / "a.wav", lambda: None)
    assert created == [("tiny", "auto", "int8")]


def array(*rows):
    return types.SimpleNamespace(tolist=lambda: [list(r) for r in rows])


class FakeOCRResult(dict):
    pass


def install_fake_paddle(monkeypatch, result=None):
    created = []

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.predicted = []

        def predict(self, path):
            self.predicted.append(path)
            return [result or FakeOCRResult(rec_texts=[], rec_boxes=[])]

    monkeypatch.setitem(sys.modules, "paddleocr", types.SimpleNamespace(PaddleOCR=FakePaddleOCR))
    return created


@pytest.mark.parametrize(
    "language, rec",
    [
        ("ko", "korean_PP-OCRv5_mobile_rec"),
        ("kor", "korean_PP-OCRv5_mobile_rec"),
        ("Korean", "korean_PP-OCRv5_mobile_rec"),
        ("en", "en_PP-OCRv5_mobile_rec"),
        ("vi", "en_PP-OCRv5_mobile_rec"),
        (None, "en_PP-OCRv5_mobile_rec"),
    ],
)
def test_ocr_routes_language_to_recognition_model(monkeypatch, tmp_path, language, rec):
    created = install_fake_paddle(monkeypatch)
    ocr = OCR(Settings())
    assert created == []
    ocr.read(tmp_path / "f.png", language)
    assert len(created) == 1
    options = created[0]
    assert options["text_detection_model_name"] == "PP-OCRv5_mobile_det"
    assert options["text_recognition_model_name"] == rec
    assert options["use_doc_orientation_classify"] is False
    assert options["use_doc_unwarping"] is False
    assert options["use_textline_orientation"] is False


def test_ocr_reuses_pipeline_per_model(monkeypatch, tmp_path):
    created = install_fake_paddle(monkeypatch)
    ocr = OCR(Settings())
    for language in (None, "vi", "en", "ko", "kor"):
        ocr.read(tmp_path / "f.png", language)
    assert [c["text_recognition_model_name"] for c in created] == [
        "en_PP-OCRv5_mobile_rec",
        "korean_PP-OCRv5_mobile_rec",
    ]


def test_ocr_joins_lines_in_reading_order(monkeypatch, tmp_path):
    boxes = [
        (300, 100, 500, 130),  # row 2, right
        (10, 200, 200, 232),  # row 3
        (10, 12, 150, 40),  # row 1 left
        (200, 10, 400, 42),  # row 1 right, slightly lower
        (10, 102, 250, 128),  # row 2, left
    ]
    texts = ["two-right", "three", "one-left", "one-right", "two-left"]
    result = FakeOCRResult(rec_texts=texts, rec_boxes=array(*boxes))
    install_fake_paddle(monkeypatch, result)
    out = OCR(Settings()).read(tmp_path / "f.png")
    assert out == "one-left\none-right\ntwo-left\ntwo-right\nthree"


def test_ocr_skips_blank_lines_and_handles_empty(monkeypatch, tmp_path):
    result = FakeOCRResult(rec_texts=["  ", "keep"], rec_boxes=array((0, 0, 10, 10), (0, 20, 10, 30)))
    install_fake_paddle(monkeypatch, result)
    assert OCR(Settings()).read(tmp_path / "f.png") == "keep"
    install_fake_paddle(monkeypatch, FakeOCRResult(rec_texts=[], rec_boxes=[]))
    assert OCR(Settings()).read(tmp_path / "f.png") == ""


def test_adapters_import_without_loading_engines():
    assert "faster_whisper" not in vars(asr_module)
    assert "paddleocr" not in vars(ocr_module)


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("say") is None, reason="macOS say is needed to synthesize speech")
def test_faster_whisper_tiny_transcribes_synthesized_speech(tmp_path):
    aiff, wav = tmp_path / "speech.aiff", tmp_path / "speech.wav"
    subprocess.run(["say", "-o", str(aiff), "open the settings menu and click install"], check=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", "16000", str(wav)], check=True
    )
    transcript = ASR(Settings(asr_model="tiny")).transcribe(wav, lambda: None)
    assert transcript.language == "en"
    text = " ".join(w.text.lower() for w in transcript.words)
    assert "settings" in text and "install" in text
    assert all(0 <= w.start <= w.end for w in transcript.words)


@pytest.mark.slow
@pytest.mark.skipif(not (SPIKE_FRAMES / "vid_30.png").exists(), reason="spike frames are not present")
def test_paddleocr_reads_real_frame():
    text = OCR(Settings()).read(SPIKE_FRAMES / "vid_30.png", "en")
    assert "Welcome to Python.org" in text
