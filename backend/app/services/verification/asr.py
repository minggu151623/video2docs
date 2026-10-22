"""Local speech recognition. The engine is imported and loaded on first use, never at import time."""

import time
from pathlib import Path

from app.core.errors import AppError
from app.schemas.verification import Transcript, Word


class ASR:
    def __init__(self, settings):
        self.settings = settings
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.settings.asr_model, device="auto", compute_type="int8")
        return self._model

    def transcribe(self, audio: Path, check_cancel) -> Transcript:
        started = time.monotonic()
        timeout = self.settings.asr_timeout_seconds

        def checkpoint():
            check_cancel()
            if time.monotonic() - started > timeout:
                raise AppError("ASR_TIMEOUT", "Nhận dạng giọng nói vượt thời gian cho phép.", 503)

        checkpoint()
        segments, info = self._load().transcribe(str(audio), word_timestamps=True, vad_filter=True)
        checkpoint()
        words = []
        for segment in segments:
            checkpoint()
            for word in segment.words or []:
                text = word.word.strip()
                if text:
                    words.append(Word(start=float(word.start), end=float(word.end), text=text))
        return Transcript(language=info.language, words=words)


def get_asr(settings):
    return ASR(settings) if settings.asr_engine == "faster-whisper" else None
