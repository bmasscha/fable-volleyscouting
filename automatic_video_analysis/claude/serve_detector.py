"""Automatic volleyball SERVE detection from a YouTube URL (or public video URL).

First-try approach
------------------
This machine has no ffmpeg/yt-dlp, but it does have the `google-genai` SDK and a
working GOOGLE_API_KEY. Gemini can ingest a YouTube URL *directly*, sampling the
video at ~1 frame/second AND processing the audio track. For serve detection that
audio channel is the decisive advantage: in volleyball a referee whistle precedes
every single serve, so the model gets a strong, near-unambiguous cue that a
frames-only pipeline would miss.

So "detection" here is a single, carefully-structured Gemini call over a clipped
time window that returns serves as JSON with timestamps. No frame extraction, no
pose models, no training. It is intentionally the simplest thing that can work.

Timestamp convention
--------------------
When we clip a video with `start_offset`, Gemini reports timestamps relative to
the *start of the clip we handed it* (0:00 = clip start). We therefore add the
clip start back to get an absolute position in the original video. This is
verified empirically by tools/probe_timebase.py; see README.

Usage
-----
    python serve_detector.py "https://youtu.be/o-E31sQlLF8" --start 8:00 --end 13:00 \
        --model gemini-3.1-pro-preview --out serves.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
class Serve(BaseModel):
    """One detected serve. `timestamp` is what the model saw (relative to the clip)."""

    timestamp: str = Field(description="Time of ball contact on the serve, MM:SS or HH:MM:SS, relative to the start of the provided clip.")
    serving_team: str = Field(default="unknown", description="'left', 'right', a team name from the scoreboard, or 'unknown'.")
    server: str = Field(default="", description="Jersey number or name of the server if legible, else empty.")
    confidence: float = Field(default=0.0, description="0..1 confidence that this is a serve.")
    reasoning: str = Field(default="", description="Brief cue used, e.g. 'referee whistle then toss+overhand hit from behind baseline'.")

    # Filled in by post-processing (not part of the model's schema output).
    clip_start_seconds: float = Field(default=0.0, exclude=True)

    @property
    def clip_seconds(self) -> float:
        return parse_timestamp(self.timestamp)

    @property
    def video_seconds(self) -> float:
        """Absolute position in the original video."""
        return self.clip_start_seconds + self.clip_seconds

    @property
    def video_timestamp(self) -> str:
        return format_timestamp(self.video_seconds)


# --------------------------------------------------------------------------- #
# Timestamp helpers
# --------------------------------------------------------------------------- #
def parse_timestamp(value) -> float:
    """Parse 'SS', 'MM:SS', or 'HH:MM:SS' (int seconds or float) into seconds.

    Accepts an int/float directly. Raises ValueError on garbage.
    """
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        raise ValueError("empty timestamp")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(f"too many ':' in timestamp: {value!r}")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"non-numeric timestamp: {value!r}")
    seconds = 0.0
    for n in nums:  # left-to-right, each place is *60 the previous
        seconds = seconds * 60 + n
    return seconds


def format_timestamp(seconds: float) -> str:
    """Seconds -> 'M:SS' (<1h) or 'H:MM:SS'."""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #
DETECTION_PROMPT = """\
You are an expert volleyball video analyst. You are given a clip of a volleyball match.

Your ONLY task: find every SERVE in this clip.

A serve is how each rally begins. Judge only from what is VISIBLE in the video (do not rely on sound):
- One player stands behind the end line (baseline), tosses the ball, and hits it (overhand jump serve, standing float, or underhand) over the net. Before that contact the two teams are stationary in rotation; after it, live rally action begins.

Rules:
- Report the timestamp of BALL CONTACT on the serve (the moment the server strikes the ball).
- Timestamps are relative to the START of THIS clip (clip start = 0:00). Use MM:SS.
- Do NOT report attacks, sets, digs, blocks, or free balls. Only the serve that starts each rally.
- If a whistle is for a timeout, substitution, or challenge (no serve follows), do not report it.
- One entry per serve. If unsure whether something is a serve, include it with a lower confidence.
- Identify the serving side as 'left' or 'right' (from the broadcast camera view). If a scoreboard team name or the server's jersey number is clearly legible, include it.

Return a JSON array of serve objects. If there are no serves in the clip, return an empty array [].
"""


# --------------------------------------------------------------------------- #
# Core detection
# --------------------------------------------------------------------------- #
def _seconds_to_offset(seconds: float) -> str:
    """Gemini VideoMetadata offsets are strings like '480s'."""
    return f"{int(round(seconds))}s"


def build_contents(youtube_url: str, start_seconds: float, end_seconds: Optional[float], fps: float):
    """Build the `contents` list for generate_content. Kept separate for testability."""
    from google.genai import types

    vm_kwargs = {"start_offset": _seconds_to_offset(start_seconds), "fps": fps}
    if end_seconds is not None:
        vm_kwargs["end_offset"] = _seconds_to_offset(end_seconds)

    video_part = types.Part(
        file_data=types.FileData(file_uri=youtube_url, mime_type="video/*"),
        video_metadata=types.VideoMetadata(**vm_kwargs),
    )
    return [video_part, DETECTION_PROMPT]


def serves_from_json(text: str, clip_start_seconds: float = 0.0) -> list[Serve]:
    """Parse a JSON array (the model's raw text) into validated, sorted, deduped Serves.

    Tolerant of a JSON object that wraps the array under a 'serves'/'results' key,
    and of ```json fences.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    data = json.loads(text)
    if isinstance(data, dict):
        for key in ("serves", "results", "detections", "items"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            data = [data]
    serves = [Serve.model_validate(item) for item in data]
    for sv in serves:
        sv.clip_start_seconds = clip_start_seconds
    return dedupe_and_sort(serves)


def dedupe_and_sort(serves: list[Serve], merge_window_seconds: float = 2.0) -> list[Serve]:
    """Sort by time; collapse near-duplicate detections within `merge_window_seconds`
    (keeping the higher-confidence one)."""
    ordered = sorted(serves, key=lambda s: s.clip_seconds)
    out: list[Serve] = []
    for sv in ordered:
        if out and abs(sv.clip_seconds - out[-1].clip_seconds) <= merge_window_seconds:
            if sv.confidence > out[-1].confidence:
                out[-1] = sv
            continue
        out.append(sv)
    return out


def detect_serves(
    youtube_url: str,
    start: float | str = 0.0,
    end: float | str | None = None,
    model: str = "gemini-3.1-pro-preview",
    fps: float = 1.0,
    media_resolution: str = "MEDIA_RESOLUTION_LOW",
    client=None,
) -> list[Serve]:
    """Run one Gemini pass over [start, end] of the video and return detected serves.

    `start`/`end` accept seconds or 'MM:SS'/'HH:MM:SS' strings.
    """
    from google import genai
    from google.genai import types

    start_s = parse_timestamp(start)
    end_s = parse_timestamp(end) if end is not None else None
    client = client or genai.Client()

    contents = build_contents(youtube_url, start_s, end_s, fps)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=list[Serve],
        media_resolution=media_resolution,
        temperature=0.0,
    )
    response = client.models.generate_content(model=model, contents=contents, config=config)
    serves = serves_from_json(response.text, clip_start_seconds=start_s)
    return serves


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _serve_to_dict(sv: Serve) -> dict:
    return {
        "video_timestamp": sv.video_timestamp,
        "video_seconds": round(sv.video_seconds, 2),
        "clip_timestamp": sv.timestamp,
        "serving_team": sv.serving_team,
        "server": sv.server,
        "confidence": sv.confidence,
        "reasoning": sv.reasoning,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Detect volleyball serves in a YouTube/video clip via Gemini.")
    p.add_argument("url", help="YouTube URL (or public video URL).")
    p.add_argument("--start", default="0:00", help="Clip start (seconds or MM:SS). Default 0:00.")
    p.add_argument("--end", default=None, help="Clip end (seconds or MM:SS). Default: end of video.")
    p.add_argument("--model", default="gemini-3.1-pro-preview", help="Gemini model id.")
    p.add_argument("--fps", type=float, default=1.0, help="Frames/sec Gemini samples. Default 1.0.")
    p.add_argument("--media-resolution", default="MEDIA_RESOLUTION_LOW",
                   help="MEDIA_RESOLUTION_LOW (cheaper) or MEDIA_RESOLUTION_MEDIUM.")
    p.add_argument("--out", default=None, help="Write results JSON to this file.")
    args = p.parse_args(argv)

    if not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY is not set.", file=sys.stderr)
        return 2

    print(f"Analyzing {args.url}  window=[{args.start}..{args.end or 'end'}]  model={args.model}", file=sys.stderr)
    serves = detect_serves(
        args.url, start=args.start, end=args.end,
        model=args.model, fps=args.fps, media_resolution=args.media_resolution,
    )

    result = [_serve_to_dict(s) for s in serves]
    print(f"\nDetected {len(serves)} serve(s):\n", file=sys.stderr)
    for s in serves:
        print(f"  {s.video_timestamp:>8}  {s.serving_team:<7} conf={s.confidence:.2f}  {s.reasoning}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
        print(f"\nWrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
