"""Generalized volleyball action detector (serve, spike, block, reception, dig).

Works from either a local mp4 (uploaded via the Gemini File API) or a public
video/YouTube URL (passed by reference). Detection over a clip window returns a
validated JSON list of actions with timestamps.

This generalizes the validated serve-only prototype (serve_detector.py); the serve
cue text and the audio-whistle insight are preserved in actions_registry.py.
"""
from __future__ import annotations

import json
import time
from typing import Callable, Optional

from pydantic import BaseModel, Field

from actions_registry import ActionType, cues_for
# reuse the small, tested scalar helpers from the prototype
from serve_detector import parse_timestamp, format_timestamp, _seconds_to_offset


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
class Action(BaseModel):
    action: str = Field(description="Which action this is: one of the requested action keys (e.g. 'serve', 'spike').")
    timestamp: str = Field(description="Time of the key ball contact, MM:SS or HH:MM:SS, relative to the start of the provided clip.")
    team: str = Field(default="unknown", description="Acting team/side: 'left', 'right', a scoreboard team name, or 'unknown'.")
    player: str = Field(default="", description="Jersey number or name of the acting player if legible, else empty.")
    confidence: float = Field(default=0.0, description="0..1 confidence.")
    reasoning: str = Field(default="", description="Brief visual/audio cue used.")

    clip_start_seconds: float = Field(default=0.0, exclude=True)

    @property
    def clip_seconds(self) -> float:
        return parse_timestamp(self.timestamp)

    @property
    def video_seconds(self) -> float:
        return self.clip_start_seconds + self.clip_seconds

    @property
    def video_timestamp(self) -> str:
        return format_timestamp(self.video_seconds)


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #
def build_prompt(actions: list[ActionType]) -> str:
    keys = ", ".join(f"'{a.key}'" for a in actions)
    cue_block = "\n".join(f"- {a.cues}" for a in actions)
    return f"""\
You are an expert volleyball video analyst. You are given a clip of a volleyball match.

Find every occurrence of ONLY these actions: {keys}.

Action definitions and cues:
{cue_block}

Rules:
- Report the timestamp of the key BALL CONTACT for each action, as MM:SS relative to the START of THIS clip (clip start = 0:00).
- Set "action" to exactly one of: {keys}.
- One entry per occurrence. If unsure, include it with a lower confidence rather than omitting it.
- For the acting team, use the 3-letter team/country code shown on the scoreboard (e.g. USA, FRA) if legible; otherwise 'left' or 'right' from the broadcast camera view. Include the jersey number if clearly legible.
- Do NOT report actions that were not requested.

Return a JSON array of action objects. If none are present, return [].
"""


# --------------------------------------------------------------------------- #
# JSON parsing
# --------------------------------------------------------------------------- #
def actions_from_json(text: str, clip_start_seconds: float = 0.0) -> list[Action]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    data = json.loads(text)
    if isinstance(data, dict):
        for key in ("actions", "results", "detections", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    actions = [Action.model_validate(item) for item in data]
    for a in actions:
        a.clip_start_seconds = clip_start_seconds
    return dedupe_and_sort(actions)


def dedupe_and_sort(actions: list[Action], merge_window_seconds: float = 2.0) -> list[Action]:
    """Sort by time; collapse near-duplicate detections OF THE SAME action type
    within merge_window_seconds (keeping the higher-confidence one). Different
    action types at the same instant are kept (a serve and a reception co-occur)."""
    ordered = sorted(actions, key=lambda a: (a.clip_seconds, a.action))
    out: list[Action] = []
    last_by_action: dict[str, int] = {}
    for a in ordered:
        idx = last_by_action.get(a.action)
        if idx is not None and abs(a.clip_seconds - out[idx].clip_seconds) <= merge_window_seconds:
            if a.confidence > out[idx].confidence:
                out[idx] = a
            continue
        out.append(a)
        last_by_action[a.action] = len(out) - 1
    return sorted(out, key=lambda a: a.clip_seconds)


# --------------------------------------------------------------------------- #
# Video analyzer (source preparation + detection)
# --------------------------------------------------------------------------- #
def is_url(source: str) -> bool:
    return source.strip().lower().startswith(("http://", "https://", "www."))


class VideoAnalyzer:
    """Prepare a source once (upload local files), then detect over any window.

    Keeping preparation separate means a long video is uploaded a single time and
    reused across every chunk.
    """

    def __init__(self, source: str, client=None):
        self.source = source
        self.is_url = is_url(source)
        self._client = client
        self._file_uri: Optional[str] = None
        self._mime: str = "video/*"

    # -- lazy client so importing this module never needs an API key ---------- #
    @property
    def client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client()
        return self._client

    def prepare(self, log: Optional[Callable[[str], None]] = None, poll_seconds: float = 2.0):
        """For local files: strip audio, upload, and wait until ACTIVE. For URLs: nothing to do.

        Audio is removed so the model reasons from the picture only — real game footage
        has no commentary (and no reliable whistle), and we must not depend on it.
        """
        import os
        import video_clipper as vc
        log = log or (lambda _m: None)
        if self.is_url:
            self._file_uri = self.source
            return
        log("Removing audio (video-only analysis) ...")
        muted = vc.strip_audio(self.source)
        try:
            log(f"Uploading {self.source} to Gemini File API ...")
            f = self.client.files.upload(file=muted)
            while str(f.state) in ("FileState.PROCESSING", "PROCESSING"):
                time.sleep(poll_seconds)
                f = self.client.files.get(name=f.name)
                log("  ...still processing")
            if str(f.state) in ("FileState.FAILED", "FAILED"):
                raise RuntimeError(f"Gemini failed to process the uploaded video: {self.source}")
            self._file_uri = f.uri
            self._mime = f.mime_type or "video/*"
        finally:
            try:
                os.remove(muted)
            except OSError:
                pass
        log("Upload ready.")

    def _video_part(self, start_s: float, end_s: Optional[float], fps: float):
        from google.genai import types
        if self._file_uri is None:
            raise RuntimeError("call prepare() before detect()")
        vm_kwargs = {"start_offset": _seconds_to_offset(start_s), "fps": fps}
        if end_s is not None:
            vm_kwargs["end_offset"] = _seconds_to_offset(end_s)
        return types.Part(
            file_data=types.FileData(file_uri=self._file_uri, mime_type=self._mime),
            video_metadata=types.VideoMetadata(**vm_kwargs),
        )

    def detect(
        self,
        actions: list[ActionType],
        start: float | str = 0.0,
        end: float | str | None = None,
        model: str = "gemini-3.1-pro-preview",
        fps: float = 1.0,
        media_resolution: str = "MEDIA_RESOLUTION_LOW",
    ) -> list[Action]:
        from google.genai import types
        start_s = parse_timestamp(start)
        end_s = parse_timestamp(end) if end is not None else None
        contents = [self._video_part(start_s, end_s, fps), build_prompt(actions)]
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[Action],
            media_resolution=media_resolution,
            temperature=0.0,
        )
        resp = self.client.models.generate_content(model=model, contents=contents, config=config)
        return actions_from_json(resp.text, clip_start_seconds=start_s)


# --------------------------------------------------------------------------- #
# Chunking helper
# --------------------------------------------------------------------------- #
def merge_actions(actions: list[Action], window_seconds: float = 2.0) -> list[Action]:
    """Merge detections from multiple (overlapping) chunks by ABSOLUTE video time.
    Same-action occurrences within window_seconds collapse to the higher-confidence
    one; different action types are always kept."""
    ordered = sorted(actions, key=lambda a: (a.video_seconds, a.action))
    out: list[Action] = []
    last_by_action: dict[str, int] = {}
    for a in ordered:
        idx = last_by_action.get(a.action)
        if idx is not None and abs(a.video_seconds - out[idx].video_seconds) <= window_seconds:
            if a.confidence > out[idx].confidence:
                out[idx] = a
            continue
        out.append(a)
        last_by_action[a.action] = len(out) - 1
    return sorted(out, key=lambda a: a.video_seconds)


def chunk_windows(start_s: float, end_s: float, chunk_seconds: float, overlap_seconds: float = 15.0):
    """Yield (win_start, win_end) tuples covering [start,end] in chunk_seconds
    steps with overlap so an action near a seam isn't lost."""
    if end_s <= start_s:
        return
    pos = start_s
    while pos < end_s:
        win_end = min(pos + chunk_seconds, end_s)
        yield (pos, win_end)
        if win_end >= end_s:
            break
        pos = win_end - overlap_seconds
