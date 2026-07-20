"""Tests for core.video_export: filename and command construction (pure), plus a
real ffmpeg cut smoke test using the bundled ffmpeg binary."""
import shutil
import subprocess

import pytest

from core.query import Action
from core.models import Rating, Role, Skill
from core.video_export import (clip_filename, concat_list_text, export_clip,
                              ffmpeg_clip_cmd, ffmpeg_concat_cmd, ffmpeg_exe,
                              ytdlp_clip_cmd)
from core.video_sync import FILE, YOUTUBE, Anchor, VideoLink


def make_action(**kw) -> Action:
    base = dict(index=0, ts=12458965.0, set_number=1, rally_index=1,
                team_key="away", player_id="a1", player_number=7,
                player_name="Player X", role=Role.OUTSIDE, skill=Skill.ATTACK,
                rating=Rating.PERFECT)
    base.update(kw)
    return Action(**base)


def test_clip_filename_matches_convention():
    assert clip_filename(make_action()) == "player_x_away_attack_ts12458965.mp4"


def test_clip_filename_falls_back_to_number_then_unknown():
    assert clip_filename(make_action(player_name="", player_number=9)).startswith("num9_")
    assert clip_filename(
        make_action(player_name="", player_number=None)).startswith("unknown_")


def test_clip_filename_uses_team_name_when_given():
    assert clip_filename(make_action(), team_name="Away Owls") == \
        "player_x_away_owls_attack_ts12458965.mp4"


def test_ffmpeg_clip_cmd_stream_copy():
    cmd = ffmpeg_clip_cmd("in.mp4", 10.0, 17.0, "out.mp4", ffmpeg="ffmpeg")
    assert cmd[:1] == ["ffmpeg"]
    assert "-ss" in cmd and "10.000" in cmd
    assert "-t" in cmd and "7.000" in cmd            # duration = end - start
    assert cmd[-3:] == ["-c", "copy", "out.mp4"]


def test_ffmpeg_clip_cmd_reencode():
    cmd = ffmpeg_clip_cmd("in.mp4", 0.0, 7.0, "out.mp4", reencode=True)
    assert "libx264" in cmd and "aac" in cmd
    assert "copy" not in cmd


def test_ytdlp_clip_cmd_download_sections():
    cmd = ytdlp_clip_cmd("dQw4w9WgXcQ", 10.0, 17.0, "out.mp4", ytdlp=["yt-dlp"])
    assert cmd[0] == "yt-dlp"
    assert "--download-sections" in cmd
    assert "*10.000-17.000" in cmd
    assert cmd[-1] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_concat_helpers():
    text = concat_list_text(["a/one.mp4", "b/two.mp4"])
    assert text == "file 'a/one.mp4'\nfile 'b/two.mp4'\n"
    cmd = ffmpeg_concat_cmd("list.txt", "reel.mp4", ffmpeg="ffmpeg")
    assert cmd[:3] == ["ffmpeg", "-y", "-f"]
    assert "concat" in cmd and cmd[-1] == "reel.mp4"


def test_export_clip_without_anchor_raises():
    link = VideoLink(source_kind=FILE, source_ref="match.mp4")  # no anchors
    with pytest.raises(ValueError):
        export_clip(link, make_action(), out_dir=".")


def test_export_clip_builds_youtube_command(monkeypatch, tmp_path):
    calls = {}

    def fake_run(cmd):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("core.video_export.run", fake_run)
    link = VideoLink(source_kind=YOUTUBE, source_ref="vid123",
                     anchors=[Anchor(event_ts=12458965.0, video_seconds=100.0)])
    out, result = export_clip(link, make_action(), out_dir=str(tmp_path))
    assert out.endswith("player_x_away_attack_ts12458965.mp4")
    assert "--download-sections" in calls["cmd"]
    assert "vid123" in calls["cmd"][-1]


# ------------------------------------------------------------------ real ffmpeg

def _have_ffmpeg() -> bool:
    exe = ffmpeg_exe()
    return exe != "ffmpeg" or shutil.which("ffmpeg") is not None


@pytest.mark.skipif(not _have_ffmpeg(), reason="no ffmpeg available")
def test_real_ffmpeg_cut_produces_a_clip(tmp_path):
    ffmpeg = ffmpeg_exe()
    src = tmp_path / "src.mp4"
    # 30 s test pattern with a tone, so a stream-copy cut has keyframes to snap to
    gen = subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=30",
                          "-pix_fmt", "yuv420p", "-g", "15", str(src)],
                         capture_output=True, text=True)
    assert gen.returncode == 0, gen.stderr[-500:]

    link = VideoLink(source_kind=FILE, source_ref=str(src),
                     anchors=[Anchor(event_ts=12458965.0, video_seconds=10.0)])
    out, result = export_clip(link, make_action(), out_dir=str(tmp_path))
    assert result.returncode == 0, result.stderr[-500:]
    assert (tmp_path / "player_x_away_attack_ts12458965.mp4").exists()
    assert (tmp_path / "player_x_away_attack_ts12458965.mp4").stat().st_size > 0
