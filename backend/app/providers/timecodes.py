"""Gemini sees MM:SS frame stamps in static video; numeric seconds made it write 01:04 as 104."""

import json
import math
import re

FIELDS = {"start_sec": "start", "end_sec": "end", "screenshot_candidates_sec": "screenshot_times"}
SECONDS = {alias: name for name, alias in FIELDS.items()}
TIMECODE = re.compile(r"^(?:(\d+):)?(\d+):([0-5]\d)(\.\d{1,3})?$")


class TimecodeError(ValueError):
    def __init__(self, loc, message, kind="timecode_invalid"):
        super().__init__(message)
        self.loc = loc
        self.message = message
        self.kind = kind


def format_timecode(seconds):
    total = int(math.floor(seconds))
    return f"{total // 60:02}:{total % 60:02}"


def parse_timecode(value):
    match = TIMECODE.match(value.strip()) if isinstance(value, str) else None
    if not match:
        raise ValueError("Timestamp must be a MM:SS string, for example 01:04 for 64 seconds")
    hours, minutes, seconds, fraction = match.groups()
    if hours is not None and int(minutes) > 59:
        raise ValueError("Timestamp minutes must be below 60 when hours are given")
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + float(fraction or 0)


def to_seconds(text):
    """Convert provider JSON (MM:SS fields) into application JSON (float seconds)."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise TimecodeError([], f"Invalid JSON: {exc.msg} at character {exc.pos}", "json_invalid") from None

    def convert(value, loc):
        try:
            return parse_timecode(value)
        except ValueError as exc:
            raise TimecodeError(loc, str(exc)) from None

    def walk(node, loc):
        if isinstance(node, list):
            return [walk(value, [*loc, index]) for index, value in enumerate(node)]
        if not isinstance(node, dict):
            return node
        result = {}
        for key, value in node.items():
            if key not in SECONDS:
                result[key] = walk(value, [*loc, key])
            elif key == "screenshot_times" and isinstance(value, list):
                result[SECONDS[key]] = [convert(v, [*loc, key, i]) for i, v in enumerate(value)]
            else:
                result[SECONDS[key]] = None if value is None else convert(value, [*loc, key])
        return result

    return json.dumps(walk(data, []), ensure_ascii=False)


def to_timecodes(node):
    """Express application metadata in the provider's MM:SS vocabulary."""
    if isinstance(node, list):
        return [to_timecodes(value) for value in node]
    if not isinstance(node, dict):
        return node
    result = {}
    for key, value in node.items():
        if key == "screenshot_candidates_sec":
            result[FIELDS[key]] = [format_timecode(v) for v in value]
        elif key.endswith("_sec") and isinstance(value, (int, float)):
            result[FIELDS.get(key, key[:-4])] = format_timecode(value)
        else:
            result[key] = to_timecodes(value)
    return result
