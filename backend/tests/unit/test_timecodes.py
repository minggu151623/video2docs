import json
import pytest
from app.providers.timecodes import TimecodeError, format_timecode, parse_timecode, to_seconds


@pytest.mark.parametrize(
    "value,expected",
    [("00:00", 0), ("01:04", 64), ("1:04", 64), ("02:00", 120), ("01:04.5", 64.5), ("0:01:04", 64)],
)
def test_parse_timecode(value, expected):
    assert parse_timecode(value) == expected


@pytest.mark.parametrize("value", ["104", "1.04", "01:60", "", 64, None, "1:04 PM"])
def test_ambiguous_or_malformed_timecodes_are_rejected(value):
    with pytest.raises(ValueError):
        parse_timecode(value)


def test_format_timecode_never_rounds_past_clip_end():
    assert format_timecode(101.642) == "01:41"
    assert format_timecode(64) == "01:04"


def test_provider_json_is_converted_to_application_seconds():
    raw = json.dumps(
        {
            "title": "start: 01:04 stays text",
            "steps": [
                {
                    "start": "01:00",
                    "end": "01:18",
                    "screenshot_times": ["01:05", "01:17"],
                    "evidence_spans": [{"start": "01:04", "end": "01:18"}],
                }
            ],
            "uncertainties": [{"description": "x", "start": None, "end": None}],
        }
    )
    data = json.loads(to_seconds(raw))
    step = data["steps"][0]
    assert (step["start_sec"], step["end_sec"]) == (60, 78)
    assert step["screenshot_candidates_sec"] == [65, 77]
    assert step["evidence_spans"][0] == {"start_sec": 64, "end_sec": 78}
    assert data["uncertainties"][0]["start_sec"] is None
    assert data["title"] == "start: 01:04 stays text"


def test_seconds_written_as_digits_report_their_location():
    raw = json.dumps({"steps": [{"start": "01:00", "end": "01:18", "screenshot_times": ["117"]}]})
    with pytest.raises(TimecodeError) as exc:
        to_seconds(raw)
    assert exc.value.loc == ["steps", 0, "screenshot_times", 0]
    assert "01:04" in exc.value.message and exc.value.kind == "timecode_invalid"


def test_invalid_json_is_reported_as_json_error():
    with pytest.raises(TimecodeError) as exc:
        to_seconds('{"steps": invalid}')
    assert exc.value.kind == "json_invalid" and exc.value.loc == []
