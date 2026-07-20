"""Offscreen tests for the desktop video-review window: match loading, filter
-> clip list, anchor-based mapping, and a real ffmpeg clip export."""
import os
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication          # noqa: E402

from core.events import (AttackEvent, DigEvent, ReceptionEvent,  # noqa: E402
                         ServeEvent)
from core.models import AWAY, HOME, MatchConfig, Rating          # noqa: E402
from core.persistence import save_match           # noqa: E402
from core.video_export import ffmpeg_exe          # noqa: E402
from core.video_sync import FILE, Anchor          # noqa: E402
from ui.video_review import VideoReviewWindow, sidecar_path      # noqa: E402

from .test_engine import make_teams, set_start_event  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _write_match(tmp_path):
    teams = make_teams()
    events = [
        set_start_event(teams, serving=HOME, left=HOME),
        ServeEvent(team=HOME, player_id=teams[HOME].players[0].id,
                   rating=Rating.ERROR, ts=1000.0),
        ServeEvent(team=HOME, player_id=teams[HOME].players[0].id,
                   rating=Rating.GOOD, ts=1010.0),
        ReceptionEvent(team=AWAY, player_id=teams[AWAY].players[0].id,
                       rating=Rating.GOOD, ts=1011.0),
        AttackEvent(team=AWAY, player_id=teams[AWAY].players[1].id,
                    rating=Rating.PERFECT, ts=1012.0),
        DigEvent(team=HOME, player_id=teams[HOME].players[6].id,
                 rating=Rating.POOR, ts=1013.0),
    ]
    path = tmp_path / "match.json"
    save_match(path, MatchConfig(), teams, events)
    return path, teams


def test_open_match_builds_action_list(app, tmp_path):
    path, _ = _write_match(tmp_path)
    win = VideoReviewWindow()
    win.open_match_path(path)
    # 2 serves + reception + attack + dig
    assert len(win._actions) == 5
    # all show up with no filter
    win.refresh_clip_list()
    assert win.clip_list.count() == 5


def test_filter_attack_by_away(app, tmp_path):
    path, _ = _write_match(tmp_path)
    win = VideoReviewWindow()
    win.open_match_path(path)
    win.team_combo.setCurrentText("Away")
    win.skill_combo.setCurrentText("attack")
    win.refresh_clip_list()
    assert len(win._filtered) == 1
    assert win._filtered[0].ts == 1012.0
    assert win.clip_list.count() == 1


def test_filter_failed_serve(app, tmp_path):
    path, _ = _write_match(tmp_path)
    win = VideoReviewWindow()
    win.open_match_path(path)
    win.skill_combo.setCurrentText("serve")
    win.rating_combo.setCurrentText(Rating.ERROR.symbol)
    win.refresh_clip_list()
    assert len(win._filtered) == 1
    assert win._filtered[0].rating == Rating.ERROR


def test_anchor_maps_action_to_video_time_in_label(app, tmp_path):
    path, _ = _write_match(tmp_path)
    win = VideoReviewWindow()
    win.open_match_path(path)
    # pin the attack (ts 1012) to video second 20
    win._link.source_kind = FILE
    win._link.source_ref = "match.mp4"
    win._link.anchors.append(Anchor(event_ts=1012.0, video_seconds=20.0))
    win.refresh_clip_list()
    attack = next(a for a in win._filtered if a.rating == Rating.PERFECT)
    label = win._clip_label(attack)
    assert "@ 0:20" in label   # 20 s -> 0:20


def test_youtube_rejects_bad_url_without_building_player(app, tmp_path):
    path, _ = _write_match(tmp_path)
    win = VideoReviewWindow()
    win.open_match_path(path)
    assert win.set_video_source_youtube("this is not a link") is False
    assert win._player is None


def test_sidecar_saved_on_video_source(app, tmp_path):
    path, _ = _write_match(tmp_path)
    win = VideoReviewWindow()
    win.open_match_path(path)
    win._link.source_kind = FILE
    win._link.source_ref = str(tmp_path / "clip.mp4")
    win._save_link()
    assert sidecar_path(path).exists()


@pytest.mark.skipif(
    ffmpeg_exe() == "ffmpeg" and __import__("shutil").which("ffmpeg") is None,
    reason="no ffmpeg available")
def test_export_selected_writes_a_clip(app, tmp_path):
    path, _ = _write_match(tmp_path)
    win = VideoReviewWindow()
    win.open_match_path(path)

    src = tmp_path / "src.mp4"
    ffmpeg = ffmpeg_exe()
    gen = subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i",
         "testsrc=size=320x240:rate=15:duration=30", "-pix_fmt", "yuv420p",
         "-g", "15", str(src)], capture_output=True, text=True)
    assert gen.returncode == 0, gen.stderr[-400:]

    win._link.source_kind = FILE
    win._link.source_ref = str(src)
    win._link.anchors.append(Anchor(event_ts=1012.0, video_seconds=10.0))

    attack = next(a for a in win._actions if a.rating == Rating.PERFECT)
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    written, failures = win._export_actions([attack], str(out_dir))
    assert failures == []
    assert len(written) == 1
    assert os.path.exists(written[0])
    assert os.path.getsize(written[0]) > 0
