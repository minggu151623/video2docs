"""Local speech recognition. The engine is imported and loaded on first use, never at import time."""

import time
from pathlib import Path

from app.core.errors import AppError
from app.schemas.verification import Transcript, Word

# L1: Whisper's language guess is rechecked when it is neither of the languages whose numbers the matcher
# reads. English said with a Singapore accent came out as Malay (0.93), English over music as Yoruba; a
# Nepali dialect decodes as fluent-looking English (-0.87) better than as Nepali (-1.39). So vi/en wins
# only when decoding in it is good in itself and clearly better than in the guessed language.
READ_LANGUAGES = ("en", "vi")
RECHECK_SECONDS = 30  # each window decoded per candidate language
RECHECK_FLOOR = -0.5  # mean avg_logprob a vi/en decode needs (real English speech: -0.17 to -0.31)
RECHECK_MARGIN = 0.3  # and how much better than the guessed language it must be


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
        """The timeout also covers the model load and faster-whisper's VAD pass, not only decoding."""
        try:
            return self._transcribe(audio, check_cancel)
        except AppError:
            raise
        except Exception as error:
            raise AppError(
                "ASR_FAILED",
                "Không chạy được nhận dạng giọng nói local (thiếu thư viện, không tải được model hoặc lỗi giải mã).",
                503,
            ) from error

    def _transcribe(self, audio, check_cancel):
        started = time.monotonic()
        timeout = self.settings.asr_timeout_seconds

        def checkpoint():
            check_cancel()
            if time.monotonic() - started > timeout:
                raise AppError("ASR_TIMEOUT", "Nhận dạng giọng nói vượt thời gian cho phép.", 503)

        checkpoint()
        model = self._load()
        # segments decode lazily: the language is known here before any decoding work
        segments, info = model.transcribe(str(audio), word_timestamps=True, vad_filter=True)
        checkpoint()
        if info.language not in READ_LANGUAGES:
            language = self._recheck(model, audio, info.language, checkpoint)
            if language != info.language:
                segments, info = model.transcribe(
                    str(audio), word_timestamps=True, vad_filter=True, language=language
                )
                checkpoint()
        words = []
        for segment in segments:
            checkpoint()
            for word in segment.words or []:
                text = word.word.strip()
                if text:
                    words.append(Word(start=float(word.start), end=float(word.end), text=text))
        return Transcript(language=info.language, words=words)


    def _windows(self, audio) -> list:
        """Up to two RECHECK_SECONDS windows of speech (VAD), at its start and its middle."""
        import numpy as np
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import collect_chunks, get_speech_timestamps

        samples = decode_audio(str(audio), sampling_rate=16000)
        chunks, _ = collect_chunks(samples, get_speech_timestamps(samples))
        if not chunks:
            return []
        speech = np.concatenate(chunks)
        size = RECHECK_SECONDS * 16000
        starts = [0] if len(speech) <= 2 * size else [0, len(speech) // 2 - size // 2]
        return [speech[start : start + size] for start in starts]

    def _recheck(self, model, audio, guessed: str, checkpoint) -> str:
        """L1: the guessed language, or en/vi when decoding the same speech in it is good (RECHECK_FLOOR)
        and better than in the guessed language by RECHECK_MARGIN."""
        windows = self._windows(audio)
        if not windows:
            return guessed

        def score(language):
            values = []
            for window in windows:
                checkpoint()
                decoded, _ = model.transcribe(
                    window, language=language, vad_filter=False, condition_on_previous_text=False
                )
                values += [segment.avg_logprob for segment in decoded]
            return sum(values) / len(values) if values else float("-inf")

        base = score(guessed)
        scores = {language: score(language) for language in READ_LANGUAGES}
        best = max(scores, key=scores.get)
        return best if scores[best] >= RECHECK_FLOOR and scores[best] - base >= RECHECK_MARGIN else guessed


def get_asr(settings):
    return ASR(settings) if settings.asr_engine == "faster-whisper" else None
