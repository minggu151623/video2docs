"""Verification results written by the app, stored apart from the model's draft (spec 2.4)."""

from typing import Literal
from pydantic import BaseModel, ConfigDict


class Word(BaseModel):
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    language: str | None = None
    words: list[Word]


class ItemVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["verified", "unverified", "not_checkable", "not_checked"]
    method: Literal["asr", "ocr", "none"]
    matched_text: str | None = None
    matched_sec: float | None = None
    checked_range: tuple[float, float] | None = None
    reason: str | None = None


class VerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: dict[str, ItemVerification]
    asr_status: Literal["ok", "skipped", "failed"]
    ocr_status: Literal["ok", "skipped", "failed"]
    asr_error: str | None = None  # error code when asr_status is "failed"
    ocr_error: str | None = None  # error code when ocr_status is "failed"
