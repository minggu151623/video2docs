"""Rulings T1-T3: terminal commands read off a real screen recording (evaluation round 1, video 1).

The OCR rows come from a Raspberry Pi desktop: a shell prompt with user, host and path before '$' (read as
'S' or 's' at times), and a file manager's folder names on the same screen line far to the right."""

import pytest
from app.core.config import Settings
from app.schemas.verification import Transcript, Word
from app.services.verification import guards
from app.services.verification.matcher import verify_item
from app.services.verification.ocr import reading_order
from app.services.verification.pipeline import ocr_seconds
from test_matcher import SETTINGS, exact, span
from test_matcher_final_review import mat


def at(item, start, end):
    """The item with one visual evidence span start-end."""
    return type(item).model_validate(item.model_dump() | {"evidence_spans": [span(start, end, "visual")]})


@pytest.mark.parametrize(
    "row",
    [
        "pi@damo:~/10DS-classwork $ git add --all",
        "pi@damo:~/10Ds-classwork S git add --all",
        "pi@damo:~/10DS-classwork s git add --all",
        "pi@damo : ∼/10DS-classwork $ git add --all",
        "pi@damo:~$ git add --all",
        "[root@box tmp]# git add --all",
        "me@mac repo % git add --all",
    ],
)
def test_t1_user_host_prompt_is_stripped(row):
    assert guards.exact_rows("git add --all", row) == "git add --all"


@pytest.mark.parametrize(
    "row",
    [
        "S git add --all",  # 'S' alone is a word, not a misread '$'
        "pi@damo:~ $ git add --all --force",  # the command goes on
        "ssh pi@damo $ git add --all",  # not a prompt at the row start
        "pi@damo:~ $ git add --all dev",  # a word right after it with a normal gap
    ],
)
def test_t1_prompt_never_makes_a_different_row_match(row):
    assert guards.exact_rows("git add --all", row) is None


def test_t2_wide_gap_becomes_a_tab_and_narrow_gaps_stay_spaces():
    texts = ["pi@damo:~ $ cd 10DS-classwork", "dev", "$ npm run build", "--prod"]
    boxes = [(139, 349, 374, 366), (1007, 339, 1042, 362), (0, 400, 150, 420), (160, 402, 220, 421)]
    assert reading_order(texts, boxes) == ["pi@damo:~ $ cd 10DS-classwork\tdev", "$ npm run build --prod"]


def test_t2_a_command_may_end_at_a_column_gap():
    assert guards.exact_rows("cd 10DS-classwork", "pi@damo:~ $ cd 10DS-classwork\tdev") == "cd 10DS-classwork"
    # the cell itself must be the whole command; text in the same column still blocks it
    assert guards.exact_rows("cd 10DS", "pi@damo:~ $ cd 10DS-classwork\tdev") is None
    assert guards.exact_rows("npm run build", "$ npm run build --prod") is None
    # a command never starts after a gap: the text left of it is on the same terminal line
    assert guards.exact_rows("dev", "pi@damo:~ $ cd 10DS-classwork\tdev") is None


def test_t2_wrapped_command_reads_each_continuation_up_to_its_gap():
    screen = "$ git commit -m\tDesktop\n'Removed test.txt'\tMusic"
    assert guards.exact_rows("git commit -m 'Removed test.txt'", screen) == "git commit -m\n'Removed test.txt'"


def test_t3_command_frames_are_taken_after_typing():
    command = exact(text="git add --all", on_screen_text="git add --all")
    command = at(command, 95, 100)
    assert ocr_seconds(command, 300.0, 3, 5.0) == [97.5, 100.0, 104.5]  # a frame found up to 0.5 s late
    material = mat("200", "g", ost="Sugar 200g", name="Sugar")
    material = at(material, 95, 100)
    assert ocr_seconds(material, 300.0, 3, 5.0) == [95.0, 97.5, 100.0]
    assert ocr_seconds(command, 102.0, 3, 5.0) == [97.5, 100.0, 101.5]  # never past the video's end


def test_t3_frame_after_the_span_verifies_the_finished_command():
    command = exact(text="cd 10DS-classwork", on_screen_text="cd 10DS-classwork")
    command = at(command, 74, 79)
    frames = [
        (76.5, "pi@damo:~ $ ls\npi@damo:~ $ cd 10ps\tdev"),
        (79.0, "pi@damo:~ $ ls\npi@damo:~ $ cd 10ps-cla\tdev"),
        (83.53, "pi@damo:~ $ ls\npi@damo:~ $ cd 10DS-classwork\tdev\npi@damo:~/10Ds-classwork $"),
    ]
    speech = Transcript(language="en", words=[Word(start=0.0, end=0.3, text="okay")])  # the video speaks
    out = verify_item("p", command, speech, frames, SETTINGS)
    assert (out.status, out.matched_text, out.matched_sec) == ("verified", "cd 10DS-classwork", 83.53)
    assert Settings().verify_window_seconds == 5
