"""Domain-neutral draft schema v2 and the v1 upgrade path."""

import json
from copy import deepcopy
from typing import Annotated, Literal
from pydantic import ConfigDict, Field, ValidationInfo, model_validator
from app.schemas.tutorial import Seconds, Short, Spans, Strict, Uncertainty

Domain = Literal["software", "cooking", "repair", "craft", "fitness", "beauty", "gardening", "music", "other"]
Basis = Literal["observed", "stated", "inferred", "unclear"]
Quote = Annotated[str, Field(max_length=1000)] | None
ScreenText = Annotated[str, Field(max_length=2000)] | None


def check_quote(item, needs_screen_text):
    """Verbatim-text rules of spec 2.3: stated needs a quote, observed text/values need on_screen_text."""
    if item.basis == "stated" and not item.quote:
        raise ValueError("A stated item requires the speaker's verbatim quote")
    if item.basis == "observed" and needs_screen_text and not item.on_screen_text:
        raise ValueError("An observed value requires the verbatim on_screen_text")


class GroundedClaim(Strict):
    text: Short
    evidence_spans: Spans
    basis: Basis = "unclear"
    scope: Literal["tutorial", "clip"] = "clip"
    quote: Quote = None
    on_screen_text: ScreenText = None

    @model_validator(mode="after")
    def grounded(self):
        check_quote(self, False)
        if self.basis == "stated" and not any(s.source in ("audio", "both") for s in self.evidence_spans):
            raise ValueError("A spoken claim requires audio evidence")
        if self.basis == "observed" and not any(s.source in ("visual", "both") for s in self.evidence_spans):
            raise ValueError("An observed claim requires visual evidence")
        return self


class Material(Strict):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    quantity: Annotated[str, Field(max_length=100)] | None
    unit: Annotated[str, Field(max_length=40)] | None
    note: Annotated[str, Field(max_length=500)] | None
    evidence_spans: Spans
    basis: Basis
    quote: Quote
    on_screen_text: ScreenText

    @model_validator(mode="after")
    def grounded(self):
        check_quote(self, self.quantity is not None)
        return self


class Equipment(Strict):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    spec: Annotated[str, Field(max_length=100)] | None
    evidence_spans: Spans


class Parameter(Strict):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    value: Annotated[str, Field(min_length=1, max_length=100)]
    unit: Annotated[str, Field(max_length=40)] | None
    evidence_spans: Spans
    basis: Basis
    quote: Quote
    on_screen_text: ScreenText

    @model_validator(mode="after")
    def grounded(self):
        check_quote(self, True)
        return self


class ExactInput(Strict):
    kind: Literal["code", "command", "text"]
    language: Annotated[str, Field(max_length=40)] | None
    text: Annotated[str, Field(min_length=1, max_length=12000)]
    completeness: Literal["complete", "partial", "unclear"]
    evidence_spans: Spans
    basis: Basis
    quote: Quote
    on_screen_text: ScreenText

    @model_validator(mode="after")
    def grounded(self):
        check_quote(self, True)
        return self


class StepV2(Strict):
    local_id: Annotated[str, Field(min_length=1, max_length=40)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    start_sec: Seconds
    end_sec: Seconds
    actions: Annotated[list[Short], Field(min_length=1, max_length=20)]
    expected_result: Short | None
    parameters: Annotated[list[Parameter], Field(max_length=10)]
    exact_inputs: Annotated[list[ExactInput], Field(max_length=10)]
    warnings: Annotated[list[GroundedClaim], Field(max_length=5)]
    tips: Annotated[list[GroundedClaim], Field(max_length=5)]
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
        if any(i.completeness != "complete" for i in self.exact_inputs):
            self.needs_review = True
            self.review_reason = self.review_reason or "Code chưa đọc chắc chắn; cần kiểm tra nguồn."
        if self.needs_review and not self.review_reason:
            raise ValueError("Review reason required")
        return self


class TutorialDraftV2(Strict):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    schema_version: Literal["2.0"]
    is_tutorial: bool
    not_tutorial_reason: Annotated[str, Field(max_length=1000)] | None
    domain: Domain
    yield_: Annotated[str, Field(max_length=200)] | None = Field(alias="yield")
    title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(max_length=3000)]
    language: Literal["vi", "en"]
    objectives: Annotated[list[Annotated[str, Field(max_length=2000)]], Field(max_length=20)]
    prerequisites: Annotated[list[GroundedClaim], Field(max_length=30)]
    safety: Annotated[list[GroundedClaim], Field(max_length=30)]
    materials: Annotated[list[Material], Field(max_length=60)]
    equipment: Annotated[list[Equipment], Field(max_length=30)]
    steps: Annotated[list[StepV2], Field(max_length=80)]
    troubleshooting: Annotated[list[GroundedClaim], Field(max_length=30)]
    uncertainties: Annotated[list[Uncertainty], Field(max_length=50)]

    @model_validator(mode="after")
    def valid_draft(self):
        if not self.is_tutorial:
            if not self.not_tutorial_reason:
                raise ValueError("not_tutorial_reason is required when is_tutorial is false")
            if self.steps:
                raise ValueError("A non-tutorial must not contain steps")
        elif not self.steps and not self.uncertainties:
            raise ValueError("No observable steps requires uncertainty")
        if len({s.local_id for s in self.steps}) != len(self.steps):
            raise ValueError("Step IDs must be unique")
        return self


def upgrade_v1(data: dict) -> dict:
    """Return a v2-shaped dict from a stored v1 draft; the input is left untouched."""
    old = deepcopy(data)

    def claim(value):
        value.setdefault("basis", "unclear")
        value.setdefault("scope", "clip")
        value["quote"] = value["on_screen_text"] = None
        if value["basis"] == "stated":
            value["basis"] = "unclear"
        return value

    def step(value):
        commands = value.pop("commands", [])
        value["exact_inputs"] = [
            {
                "kind": "command",
                "language": c["language"],
                "text": c["text"],
                "completeness": c["completeness"],
                "evidence_spans": c["evidence_spans"],
                "basis": "unclear",
                "quote": None,
                "on_screen_text": None,
            }
            for c in commands
        ]
        value.update(parameters=[], warnings=[], tips=[])
        return value

    old.update(
        schema_version="2.0",
        is_tutorial=True,
        not_tutorial_reason=None,
        domain="software",
        safety=[],
        materials=[],
        prerequisites=[claim(c) for c in old.get("prerequisites", [])],
        troubleshooting=[claim(c) for c in old.get("troubleshooting", [])],
        equipment=[
            {"name": t["name"], "spec": t.get("version"), "evidence_spans": t["evidence_spans"]}
            for t in old.pop("tools", [])
        ],
        steps=[step(s) for s in old.get("steps", [])],
    )
    old["yield"] = None
    return old


def load_draft(raw: str | bytes, duration: float) -> TutorialDraftV2:
    """Read a stored or provider draft of either version as v2."""
    try:
        data = json.loads(raw)
    except ValueError:
        return TutorialDraftV2.model_validate_json(raw, context={"duration": duration})
    if isinstance(data, dict) and data.get("schema_version") == "1.0":
        data = upgrade_v1(data)
    return TutorialDraftV2.model_validate(data, context={"duration": duration})
