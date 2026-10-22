from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

Short = Annotated[str, Field(min_length=1, max_length=2000)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Span(Strict):
    start_sec: Seconds
    end_sec: Seconds
    source: Literal["visual", "audio", "both"]
    description: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def bounds(self, info: ValidationInfo):
        if self.start_sec > self.end_sec or self.end_sec > (info.context or {}).get("duration", float("inf")):
            raise ValueError("Evidence span outside clip timeline")
        return self


Spans = Annotated[list[Span], Field(min_length=1, max_length=5)]


class SourceClaim(Strict):
    text: Short
    evidence_spans: Spans
    basis: Literal["observed", "stated", "inferred", "unclear"] = "unclear"
    scope: Literal["tutorial", "clip"] = "clip"

    @model_validator(mode="after")
    def evidence_kind(self):
        if self.basis == "stated" and not any(s.source in ("audio", "both") for s in self.evidence_spans):
            raise ValueError("A spoken claim requires audio evidence")
        if self.basis == "observed" and not any(s.source in ("visual", "both") for s in self.evidence_spans):
            raise ValueError("An observed claim requires visual evidence")
        return self


class ToolMention(Strict):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    version: Annotated[str, Field(max_length=100)] | None
    evidence_spans: Spans


class Command(Strict):
    language: Annotated[str, Field(min_length=1, max_length=40)]
    text: Annotated[str, Field(min_length=1, max_length=12000)]
    completeness: Literal["complete", "partial", "unclear"]
    evidence_spans: Spans


class Step(Strict):
    local_id: Annotated[str, Field(min_length=1, max_length=40)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    start_sec: Seconds
    end_sec: Seconds
    actions: Annotated[list[Short], Field(min_length=1, max_length=20)]
    expected_result: Short | None
    commands: Annotated[list[Command], Field(max_length=10)]
    evidence_spans: Spans
    screenshot_candidates_sec: Annotated[list[Seconds], Field(max_length=2)]
    needs_review: bool
    review_reason: Short | None

    @model_validator(mode="after")
    def valid_step(self, info: ValidationInfo):
        duration = (info.context or {}).get("duration", float("inf"))
        if not 0 <= self.start_sec <= self.end_sec <= duration:
            raise ValueError("Step outside clip timeline")
        if any(
            not self.start_sec <= t <= self.end_sec or t >= duration for t in self.screenshot_candidates_sec
        ):
            raise ValueError("Screenshot outside step or at EOF")
        if any(c.completeness != "complete" for c in self.commands):
            self.needs_review = True
            self.review_reason = self.review_reason or "Code chưa đọc chắc chắn; cần kiểm tra nguồn."
        if self.needs_review and not self.review_reason:
            raise ValueError("Review reason required")
        return self


class Uncertainty(Strict):
    description: Annotated[str, Field(min_length=1, max_length=1000)]
    start_sec: Seconds | None
    end_sec: Seconds | None

    @model_validator(mode="after")
    def bounds(self, info: ValidationInfo):
        duration = (info.context or {}).get("duration", float("inf"))
        if (self.start_sec is None) != (self.end_sec is None):
            raise ValueError("Uncertainty requires both timestamps or neither")
        if self.start_sec is not None and not 0 <= self.start_sec <= self.end_sec <= duration:
            raise ValueError("Uncertainty outside clip")
        return self


class TutorialDraftV1(Strict):
    schema_version: Literal["1.0"]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(max_length=3000)]
    language: Literal["vi", "en"]
    objectives: Annotated[list[Annotated[str, Field(max_length=2000)]], Field(max_length=20)]
    prerequisites: Annotated[list[SourceClaim], Field(max_length=30)]
    tools: Annotated[list[ToolMention], Field(max_length=30)]
    steps: Annotated[list[Step], Field(max_length=80)]
    troubleshooting: Annotated[list[SourceClaim], Field(max_length=30)]
    uncertainties: Annotated[list[Uncertainty], Field(max_length=50)]

    @model_validator(mode="after")
    def no_invented_steps(self):
        if not self.steps and not self.uncertainties:
            raise ValueError("No observable steps requires uncertainty")
        if len({s.local_id for s in self.steps}) != len(self.steps):
            raise ValueError("Step IDs must be unique")
        return self
