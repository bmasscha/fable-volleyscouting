"""Synchronize scouting timestamps with a match video.

Events carry a wall-clock unix `ts`; a video has its own 0-based timeline. The
user pins the two together with one or more *anchors* -- each an (event_ts,
video_seconds) pair set by seeking the video to a known action. From those this
module maps any event timestamp to a video position, and turns a matched action
into a fixed 2 s-before / 5 s-after clip window.

Pure Python, no Qt. Mirrored to tablet/src/core/videoSync.ts (TRANSLATION.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# The clip pulled around each action: 2 s before -> 5 s after (7 s total). The
# generous pre-roll also absorbs a rough single-anchor sync.
PRE_ROLL = 2.0
POST_ROLL = 5.0

# Video source kinds.
FILE = "file"
YOUTUBE = "youtube"


@dataclass(frozen=True)
class Anchor:
    """Pins one scouting timestamp to a position in the video."""
    event_ts: float          # scouting wall-clock, unix seconds
    video_seconds: float     # position in the video (>= 0)


@dataclass
class VideoLink:
    """A video bound to a match, plus the anchors that align them."""
    source_kind: str = FILE              # FILE | YOUTUBE
    source_ref: str = ""                 # file path, or YouTube video id
    anchors: list[Anchor] = field(default_factory=list)
    pre_roll: float = PRE_ROLL
    post_roll: float = POST_ROLL

    def to_dict(self) -> dict:
        return {
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "anchors": [[a.event_ts, a.video_seconds] for a in self.anchors],
            "pre_roll": self.pre_roll,
            "post_roll": self.post_roll,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VideoLink":
        return cls(
            source_kind=d.get("source_kind", FILE),
            source_ref=d.get("source_ref", ""),
            anchors=[Anchor(float(a[0]), float(a[1]))
                     for a in d.get("anchors", [])],
            pre_roll=float(d.get("pre_roll", PRE_ROLL)),
            post_roll=float(d.get("post_roll", POST_ROLL)),
        )


def event_to_video_time(link: VideoLink, ts: float | None) -> float | None:
    """Map a scouting timestamp to a video position (seconds), or None when the
    link has no anchors or the event has no timestamp.

    One anchor -> a constant offset (slope 1). Two or more -> piecewise-linear
    interpolation between the surrounding anchors (which also corrects clock
    drift); outside the anchored span, the nearest anchor's offset is extended
    (slope 1), so recording gaps between anchored segments stay well-behaved.
    The result may be negative (before the video starts); clip_window clamps it.
    """
    if ts is None or not link.anchors:
        return None
    anchors = sorted(link.anchors, key=lambda a: a.event_ts)
    if ts <= anchors[0].event_ts:
        a = anchors[0]
        return a.video_seconds + (ts - a.event_ts)
    if ts >= anchors[-1].event_ts:
        a = anchors[-1]
        return a.video_seconds + (ts - a.event_ts)
    for lo, hi in zip(anchors, anchors[1:]):
        if lo.event_ts <= ts <= hi.event_ts:
            span = hi.event_ts - lo.event_ts
            if span <= 0:
                return lo.video_seconds
            frac = (ts - lo.event_ts) / span
            return lo.video_seconds + frac * (hi.video_seconds - lo.video_seconds)
    return None  # unreachable given the guards above


def clip_window(link: VideoLink, ts: float | None) -> tuple[float, float] | None:
    """The (start, end) video window to play/export for an action at `ts`:
    pre_roll before to post_roll after, clamped to the start of the video."""
    v = event_to_video_time(link, ts)
    if v is None:
        return None
    start = max(0.0, v - link.pre_roll)
    end = max(start, v + link.post_roll)
    return (start, end)


_YOUTUBE_ID = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})")


def youtube_id(url_or_id: str) -> str | None:
    """Extract the 11-char video id from a YouTube URL, or accept a bare id.
    Returns None when nothing looks like a video id."""
    text = (url_or_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    m = _YOUTUBE_ID.search(text)
    return m.group(1) if m else None


def suggest_offset(video_mtime: float, duration: float) -> float:
    """Estimate the wall-clock time at video position 0. A recording that
    finished at `video_mtime` and ran `duration` seconds started at their
    difference -- use it as the event_ts of a first (video_seconds=0) anchor."""
    return video_mtime - duration
