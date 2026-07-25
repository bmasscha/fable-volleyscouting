"""Offline unit tests for the generalized engine. No network / API key needed."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import action_detector as ad
from action_detector import Action, actions_from_json, merge_actions, chunk_windows, is_url, build_prompt
from actions_registry import ACTIONS_BY_KEY, cues_for


# --------------------------- Action model ------------------------------- #
def test_action_absolute_time():
    a = Action(action="serve", timestamp="0:30", clip_start_seconds=600)
    assert a.clip_seconds == 30
    assert a.video_seconds == 630
    assert a.video_timestamp == "10:30"


SAMPLE = """[
  {"action":"serve","timestamp":"0:05","team":"left","player":"7","confidence":0.95,"reasoning":"whistle"},
  {"action":"spike","timestamp":"0:12","team":"right","player":"","confidence":0.7,"reasoning":"downward hit"}
]"""


def test_actions_from_json_basic():
    acts = actions_from_json(SAMPLE, clip_start_seconds=600)
    assert [a.action for a in acts] == ["serve", "spike"]
    assert acts[0].video_timestamp == "10:05"


def test_actions_from_json_fenced_and_wrapped():
    assert len(actions_from_json("```json\n" + SAMPLE + "\n```")) == 2
    assert len(actions_from_json('{"actions": ' + SAMPLE + "}")) == 2


def test_actions_from_json_defaults():
    a = actions_from_json('[{"action":"serve","timestamp":"1:00"}]')[0]
    assert a.team == "unknown" and a.confidence == 0.0


# --------------------------- dedupe within a chunk ---------------------- #
def test_dedupe_same_action_merges_keeping_confidence():
    acts = actions_from_json("""[
      {"action":"serve","timestamp":"0:10","confidence":0.6},
      {"action":"serve","timestamp":"0:11","confidence":0.9}
    ]""")
    assert len(acts) == 1 and acts[0].confidence == 0.9


def test_dedupe_keeps_different_actions_at_same_time():
    acts = actions_from_json("""[
      {"action":"serve","timestamp":"0:10","confidence":0.9},
      {"action":"reception","timestamp":"0:11","confidence":0.8}
    ]""")
    assert len(acts) == 2  # a serve and a reception co-occur -> both kept


# --------------------------- cross-chunk merge -------------------------- #
def test_merge_actions_dedupes_by_absolute_time():
    # same serve seen in two overlapping chunks: chunk A [600..] and chunk B [585..]
    a = Action(action="serve", timestamp="0:20", clip_start_seconds=600, confidence=0.8)  # 620s
    b = Action(action="serve", timestamp="0:35", clip_start_seconds=585, confidence=0.9)  # 620s
    merged = merge_actions([a, b])
    assert len(merged) == 1 and merged[0].confidence == 0.9


def test_merge_keeps_distinct_serves():
    a = Action(action="serve", timestamp="0:20", clip_start_seconds=600)  # 620
    b = Action(action="serve", timestamp="0:50", clip_start_seconds=600)  # 650
    assert len(merge_actions([a, b])) == 2


# --------------------------- chunk windows ------------------------------ #
def test_chunk_windows_overlap_and_cover():
    wins = list(chunk_windows(0, 900, chunk_seconds=300, overlap_seconds=15))
    assert wins[0] == (0, 300)
    assert wins[1][0] == 285  # overlaps previous by 15s
    assert wins[-1][1] == 900  # covers the end


def test_chunk_windows_single_when_short():
    assert list(chunk_windows(0, 120, chunk_seconds=300)) == [(0, 120)]


def test_chunk_windows_empty_when_degenerate():
    assert list(chunk_windows(100, 100, 300)) == []


# --------------------------- misc --------------------------------------- #
@pytest.mark.parametrize("s,expected", [
    ("https://youtu.be/x", True), ("http://x", True), ("www.x.com", True),
    (r"C:\videos\game.mp4", False), ("game.mp4", False),
])
def test_is_url(s, expected):
    assert is_url(s) is expected


def test_build_prompt_includes_selected_action_cues_only():
    prompt = build_prompt(cues_for(["serve"]))
    assert "'serve'" in prompt
    assert "SERVE" in prompt
    assert "SPIKE" not in prompt  # not selected


def test_registry_has_serve_reliable():
    assert ACTIONS_BY_KEY["serve"].reliable is True
    assert ACTIONS_BY_KEY["spike"].reliable is False
