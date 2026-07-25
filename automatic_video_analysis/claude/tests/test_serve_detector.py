"""Offline unit tests for serve_detector. No network / no API key required.

Run:  python -m pytest automatic_video_analysis/claude/tests -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serve_detector import (  # noqa: E402
    Serve,
    parse_timestamp,
    format_timestamp,
    serves_from_json,
    dedupe_and_sort,
    build_contents,
    _seconds_to_offset,
)


# --------------------------- timestamp parsing --------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("0:00", 0), ("0:05", 5), ("1:30", 90), ("10:00", 600),
    ("1:00:00", 3600), ("1:02:03", 3723), ("45", 45), ("2:07", 127),
])
def test_parse_timestamp(text, expected):
    assert parse_timestamp(text) == expected


def test_parse_timestamp_numeric_passthrough():
    assert parse_timestamp(90) == 90.0
    assert parse_timestamp(12.5) == 12.5


@pytest.mark.parametrize("bad", ["", "1:2:3:4", "abc", "1:xx"])
def test_parse_timestamp_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_timestamp(bad)


@pytest.mark.parametrize("secs,expected", [
    (0, "0:00"), (5, "0:05"), (90, "1:30"), (600, "10:00"),
    (3600, "1:00:00"), (3723, "1:02:03"),
])
def test_format_timestamp(secs, expected):
    assert format_timestamp(secs) == expected


def test_parse_format_roundtrip():
    for secs in (0, 7, 59, 60, 125, 3599, 3600, 7325):
        assert parse_timestamp(format_timestamp(secs)) == secs


# --------------------------- absolute video time ------------------------- #
def test_video_seconds_adds_clip_offset():
    sv = Serve(timestamp="0:30", clip_start_seconds=480)  # clip started at 8:00
    assert sv.clip_seconds == 30
    assert sv.video_seconds == 510
    assert sv.video_timestamp == "8:30"


# --------------------------- JSON parsing -------------------------------- #
SAMPLE = """[
  {"timestamp": "0:05", "serving_team": "left",  "server": "7",  "confidence": 0.95, "reasoning": "whistle then jump serve"},
  {"timestamp": "0:35", "serving_team": "right", "server": "",   "confidence": 0.90, "reasoning": "float serve behind baseline"}
]"""


def test_serves_from_json_basic():
    serves = serves_from_json(SAMPLE, clip_start_seconds=480)
    assert len(serves) == 2
    assert serves[0].serving_team == "left"
    assert serves[0].video_timestamp == "8:05"
    assert serves[1].video_timestamp == "8:35"


def test_serves_from_json_handles_code_fence():
    fenced = "```json\n" + SAMPLE + "\n```"
    assert len(serves_from_json(fenced)) == 2


def test_serves_from_json_handles_wrapper_object():
    wrapped = '{"serves": ' + SAMPLE + "}"
    assert len(serves_from_json(wrapped)) == 2


def test_serves_from_json_empty():
    assert serves_from_json("[]") == []


def test_serves_from_json_defaults_for_missing_fields():
    serves = serves_from_json('[{"timestamp": "1:00"}]')
    assert serves[0].serving_team == "unknown"
    assert serves[0].confidence == 0.0


# --------------------------- dedupe & sort ------------------------------- #
def test_dedupe_and_sort_orders_by_time():
    serves = [Serve(timestamp="0:30"), Serve(timestamp="0:05"), Serve(timestamp="1:00")]
    out = dedupe_and_sort(serves)
    assert [s.timestamp for s in out] == ["0:05", "0:30", "1:00"]


def test_dedupe_collapses_near_duplicates_keeping_higher_confidence():
    serves = [
        Serve(timestamp="0:10", confidence=0.6),
        Serve(timestamp="0:11", confidence=0.9),  # within 2s -> merge, keep 0.9
        Serve(timestamp="0:30", confidence=0.5),
    ]
    out = dedupe_and_sort(serves)
    assert len(out) == 2
    assert out[0].confidence == 0.9
    assert out[1].timestamp == "0:30"


def test_dedupe_keeps_distinct_serves():
    serves = [Serve(timestamp="0:10"), Serve(timestamp="0:25")]  # 15s apart
    assert len(dedupe_and_sort(serves)) == 2


# --------------------------- contents builder ---------------------------- #
def test_seconds_to_offset():
    assert _seconds_to_offset(480) == "480s"
    assert _seconds_to_offset(480.6) == "481s"


def test_build_contents_sets_clip_window():
    contents = build_contents("https://youtu.be/x", start_seconds=480, end_seconds=780, fps=1.0)
    video_part = contents[0]
    assert video_part.file_data.file_uri == "https://youtu.be/x"
    assert video_part.video_metadata.start_offset == "480s"
    assert video_part.video_metadata.end_offset == "780s"
    assert video_part.video_metadata.fps == 1.0
    assert isinstance(contents[1], str) and "serve" in contents[1].lower()


def test_build_contents_open_ended():
    contents = build_contents("https://youtu.be/x", start_seconds=0, end_seconds=None, fps=2.0)
    assert contents[0].video_metadata.end_offset is None
    assert contents[0].video_metadata.fps == 2.0
