"""Export match-video fragments (desktop only).

The command lines are built by pure functions (unit-tested without the binaries
present); only the small runner and the resolvers touch the filesystem/network.
Local files are cut with ffmpeg; YouTube fragments are fetched with yt-dlp.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .query import Action
from .video_sync import YOUTUBE, VideoLink, clip_window


# --------------------------------------------------------------- tool resolvers

def ffmpeg_exe() -> str:
    """A usable ffmpeg path: the imageio-ffmpeg bundle if installed, else PATH."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def ytdlp_base() -> list[str]:
    """Argv prefix that runs yt-dlp: the importable module if present (most
    reliable), else a `yt-dlp` on PATH."""
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        return ["yt-dlp"]


# ------------------------------------------------------------ filename / commands

def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text.strip().lower()).strip("_")
    return s or "x"


def clip_filename(action: Action, team_name: str = "") -> str:
    """`{player}_{team}_{skill}_ts{unix_seconds}.mp4`, e.g.
    `player_x_away_attack_ts12458965.mp4`."""
    if action.player_name:
        name = _slug(action.player_name)
    elif action.player_number is not None:
        name = f"num{action.player_number}"
    else:
        name = "unknown"
    team = _slug(team_name or action.team_key)
    skill = _slug(getattr(action.skill, "value", str(action.skill)))
    ts = int(action.ts) if action.ts is not None else 0
    return f"{name}_{team}_{skill}_ts{ts}.mp4"


def ffmpeg_clip_cmd(src: str, start: float, end: float, out: str,
                    reencode: bool = False, ffmpeg: str = "ffmpeg") -> list[str]:
    """Cut [start, end] from a local file. `-ss` before `-i` fast-seeks; with
    stream copy that snaps to the nearest keyframe (fast, a few frames loose --
    the 2 s pre-roll absorbs it). `reencode` gives a frame-accurate cut."""
    duration = max(0.0, end - start)
    cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-i", src, "-t", f"{duration:.3f}"]
    if reencode:
        cmd += ["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"]
    else:
        cmd += ["-c", "copy"]
    cmd += [out]
    return cmd


def ytdlp_clip_cmd(video_id: str, start: float, end: float, out: str,
                   ytdlp: list[str] | None = None) -> list[str]:
    """Download just the [start, end] window of a YouTube video."""
    base = list(ytdlp) if ytdlp is not None else ["yt-dlp"]
    section = f"*{start:.3f}-{end:.3f}"
    return base + ["--download-sections", section, "--force-keyframes-at-cuts",
                   "-o", out, f"https://www.youtube.com/watch?v={video_id}"]


def ffmpeg_concat_cmd(list_file: str, out: str, ffmpeg: str = "ffmpeg") -> list[str]:
    """Concatenate the clips named in `list_file` (ffmpeg concat demuxer) into a
    single highlight reel."""
    return [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
            "-c", "copy", out]


def concat_list_text(clip_paths: list[str]) -> str:
    """Body of the concat demuxer list file: one `file '...'` line per clip."""
    return "".join(f"file '{Path(p).as_posix()}'\n" for p in clip_paths)


# ----------------------------------------------------------------------- runner

def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a built command, capturing output. Raises nothing; inspect
    `.returncode`/`.stderr`."""
    return subprocess.run(cmd, capture_output=True, text=True)


def export_clip(link: VideoLink, action: Action, out_dir: str,
                team_name: str = "", reencode: bool = False) -> tuple[str, subprocess.CompletedProcess]:
    """Export one action's 7 s fragment to `out_dir`. Returns (path, result).
    Raises ValueError if the action can't be mapped to the video (no anchor)."""
    window = clip_window(link, action.ts)
    if window is None:
        raise ValueError("no sync anchor set -- cannot map this action to the video")
    start, end = window
    out = str(Path(out_dir) / clip_filename(action, team_name))
    if link.source_kind == YOUTUBE:
        cmd = ytdlp_clip_cmd(link.source_ref, start, end, out, ytdlp=ytdlp_base())
    else:
        cmd = ffmpeg_clip_cmd(link.source_ref, start, end, out,
                              reencode=reencode, ffmpeg=ffmpeg_exe())
    return out, run(cmd)
