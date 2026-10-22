"""Derive a compact Gemini schema; Pydantic retains the full application contract."""

import hashlib
import json
import math
from copy import deepcopy
from functools import lru_cache
from app.schemas.tutorial import TutorialDraftV1
from app.providers.timecodes import FIELDS, format_timecode


@lru_cache
def tutorial_provider_schema():
    original = TutorialDraftV1.model_json_schema()
    definitions = original.get("$defs", {})

    def convert(node, references=()):
        if "$ref" in node:
            reference = node["$ref"]
            if not reference.startswith("#/$defs/") or reference in references:
                raise ValueError("Unsupported recursive or external schema reference")
            return convert(definitions[reference.rsplit("/", 1)[1]], (*references, reference))
        if "anyOf" in node:
            branches = node["anyOf"]
            non_null = [branch for branch in branches if branch.get("type") != "null"]
            if len(non_null) != 1 or len(branches) != 2:
                raise ValueError("Only nullable unions are supported by this adapter")
            converted = convert(non_null[0], references)
            converted["type"] = [converted["type"], "null"]
            return converted
        result = {
            key: node[key]
            for key in ("type", "enum", "format", "minimum", "maximum", "additionalProperties")
            if key in node
        }
        if "const" in node:
            result["enum"] = [node["const"]]
        if "properties" in node:
            result["properties"] = {}
            for key, value in node["properties"].items():
                converted = convert(value, references)
                result["properties"][FIELDS.get(key, key)] = (
                    timecode(converted) if key in FIELDS else converted
                )
            result["required"] = list(result["properties"])
        if "items" in node:
            result["items"] = convert(node["items"], references)
        hints = []
        if node.get("description"):
            hints.append(node["description"])
        for key, label in (
            ("minItems", "Minimum items"),
            ("maxItems", "Maximum items"),
            ("minLength", "Minimum characters"),
            ("maxLength", "Maximum characters"),
        ):
            if key in node:
                hints.append(f"{label}: {node[key]}.")
        if hints:
            result["description"] = " ".join(hints)
        return result

    def timecode(node):
        if node["type"] == "array":
            node["items"] = timecode(node["items"])
            return node
        node.pop("minimum", None)
        node["type"] = ["string", "null"] if node["type"] == ["number", "null"] else "string"
        node["description"] = "MM:SS from the start of this clip, for example 01:04 for 64 seconds."
        return node

    return convert(original)


def video_provider_schema(duration):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("A finite measured clip duration is required")
    schema = deepcopy(tutorial_provider_schema())
    last = format_timecode(duration)
    frame = format_timecode(max(0, math.ceil(duration) - 1))
    schema["description"] = (
        f"All times are MM:SS strings from the start of this clip, which runs 00:00 to {last}. "
        "Write 64 seconds as 01:04, never as 104 or 1.04. "
        f"Every span requires 00:00 <= start <= end <= {last}. "
        "For each step: start <= screenshot time <= end, and every screenshot time is at most "
        f"{frame}. Use an empty screenshot_times array when no suitable frame exists."
    )

    def bound(node):
        if not isinstance(node, dict):
            return
        for name, field in node.get("properties", {}).items():
            if name in ("start", "end"):
                field["description"] += f" At most {last}."
            if name == "screenshot_times":
                field["maxItems"] = 2
                field["description"] = (
                    f"MM:SS frame times, at most {frame}. Each must be within this step's start and end. "
                    "Use [] if no suitable frame exists."
                )
            bound(field)
        if "items" in node:
            bound(node["items"])

    bound(schema)
    return schema


def analysis_contract_hash():
    contract = {
        "adapter": "interactions-static-v8",
        "timestamp_policy": "MM:SS strings from clip start, parsed to seconds by the adapter; screenshots inside step and before EOF; empty candidates allowed",
        "repair_policy": "bounded previous output in untrusted repair data; transient only; errors without raw input in audit",
        "screenshot_candidates_limit": 2,
        "claim_policy": "declared basis; later prerequisites scoped to clip; ungrounded claims shown as review",
        "context_policy": "bounded previous step titles, never evidence; local timestamps",
        "evidence_policy": "latest supported result candidate; on candidate/span conflict use end of latest visual span with review; midpoint only without candidates",
        "thinking_level": "low",
        "provider_schema": tutorial_provider_schema(),
        "application_schema": TutorialDraftV1.model_json_schema(),
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
