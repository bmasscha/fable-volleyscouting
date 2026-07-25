"""Video helpers: cut short fragments around a timestamp, probe duration, and
(for URL sources) download a local working copy. All via the ffmpeg binary that
ships with imageio-ffmpeg, so no system ffmpeg install is required.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Optional

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def _hms(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-") or "x"


def probe_duration(path: str) -> Optional[float]:
    """Return duration in seconds using ffmpeg (parses stderr). None if unknown."""
    try:
        proc = subprocess.run(
            [FFMPEG, "-i", path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
    except Exception:
        return None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not m:
        return None
    h, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mm * 60 + ss


def strip_audio(input_file: str, out_file: Optional[str] = None) -> str:
    """Fast remux dropping the audio track (video-only). Analysis must never see
    audio — real game footage has no commentary and we must not rely on it."""
    if out_file is None:
        import tempfile
        fd, out_file = tempfile.mkstemp(suffix="_muted.mp4")
        os.close(fd)
    cmd = [FFMPEG, "-y", "-i", input_file, "-c:v", "copy", "-an", out_file]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_file


def read_muted_bytes(input_file: str) -> bytes:
    """Bytes of a video-only (audio-stripped) copy of input_file."""
    tmp = strip_audio(input_file)
    try:
        with open(tmp, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def cut_clip(input_file: str, at_seconds: float, out_path: str, pre: float = 4.0, post: float = 5.0):
    """Cut [at-pre, at+post] from input_file, re-encoding to a frame-accurate,
    natively-playable mp4 (H.264/AAC) with audio."""
    start = max(0.0, at_seconds - pre)
    dur = (at_seconds - start) + post
    cmd = [
        FFMPEG, "-y",
        "-ss", f"{start:.3f}", "-i", input_file, "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def download_url_window(url: str, start_s: float, end_s: float, out_file: str) -> str:
    """Download [start,end] of a YouTube/public URL to out_file (mp4). Cached."""
    if os.path.exists(out_file) and os.path.getsize(out_file) > 0:
        return out_file
    os.makedirs(os.path.dirname(out_file) or ".", exist_ok=True)
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--ffmpeg-location", FFMPEG,
        "--download-sections", f"*{_hms(start_s)}-{_hms(end_s)}",
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=480][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<=480][ext=mp4]/bv*[height<=480]+ba/b",
        "--merge-output-format", "mp4",
        "-o", out_file,
        url,
    ]
    subprocess.run(cmd, check=True)
    return out_file
