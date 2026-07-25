"""Rough serve/spike trajectory estimation via Gemini keypoint grounding.

Instead of dense frame-by-frame ball tracking (hard: a volleyball is ~5px and
motion-blurred), this asks Gemini for a few KEY POINTS it localizes well — where
the ball is at serve contact, where it crosses the net, and where it is received —
then fits a smooth arc through them and overlays it on the clip.

This gives serve PLACEMENT / DIRECTION (origin -> target), not true physical speed
or height. The detector is intentionally swappable: a dense tracker (TrackNet /
vball-net) can replace `estimate_trajectory` later for a physically accurate arc
without touching the rendering.
"""
from __future__ import annotations

import os
from typing import Optional

import cv2
import numpy as np
from pydantic import BaseModel, Field

from serve_detector import parse_timestamp


# Points we ask Gemini to localise, in flight order. Player points are context.
FLIGHT_LABELS = ["serve_contact", "net_crossing", "reception"]
PLAYER_LABELS = ["server", "receiver"]


class TrajPoint(BaseModel):
    label: str = Field(description="One of: serve_contact, net_crossing, reception, server, receiver.")
    clip_time: str = Field(default="0:00", description="MM:SS within the clip when observed.")
    y: int = Field(description="Normalized 0-1000, top->bottom.")
    x: int = Field(description="Normalized 0-1000, left->right.")
    confidence: float = Field(default=0.0)


GROUNDING_PROMPT = """This is a volleyball SERVE clip. Return normalized image points (y,x in 0-1000) for as many as are visible:
- "serve_contact": the ball at the instant the server strikes it
- "net_crossing": the ball at the instant it passes over the net
- "reception": the ball where the receiving player first contacts it (or where it lands)
- "server": the serving player at contact
- "receiver": the receiving player at reception
Give the clip_time (MM:SS) you observed each. Omit any point you cannot see."""


def estimate_trajectory(clip_path: str, model: str = "gemini-3.1-pro-preview", client=None) -> list[TrajPoint]:
    """Ask Gemini for the ball/player keypoints in a serve clip."""
    from google import genai
    from google.genai import types
    import video_clipper as vc
    client = client or genai.Client()
    data = vc.read_muted_bytes(clip_path)  # video-only: never send audio to the model
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=data, mime_type="video/mp4"), GROUNDING_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[TrajPoint],
            temperature=0.0,
        ),
    )
    return points_from_json(resp.text)


class ServeAnalysis(BaseModel):
    """One Gemini call: image keypoints (for the per-clip arc) AND court-space
    placement (for the camera-independent top-down chart)."""
    keypoints: list[TrajPoint] = Field(default_factory=list)
    serving_team: str = Field(default="unknown", description="3-letter team/country code from the scoreboard (e.g. USA, FRA).")
    server_player: str = ""
    serve_from_lateral: float = Field(default=0.5, description="0-1 across the SERVING half width, 0=left 1=right as seen by the serving team on their endline facing the net.")
    target_depth: float = Field(default=0.5, description="0-1 in the RECEIVING half: 0=at the net, 1=at the receiving endline.")
    target_lateral: float = Field(default=0.5, description="0-1 across the RECEIVING half width, 0=left 1=right as seen by the receiving team on their endline facing the net.")
    target_zone: int = Field(default=0, description="Receiving zone 1-6 (back row 5/6/1 left-to-right from receiver POV, front row 4/3/2), 0 if unknown.")
    confidence: float = 0.0


SERVE_ANALYSIS_PROMPT = GROUNDING_PROMPT + """

ALSO report the serve in COURT coordinates (not image pixels), using the field
descriptions. The lateral axes are defined from each TEAM's own point of view
facing the net, so they must NOT depend on the camera angle. For serving_team, use
the 3-letter team code exactly as shown on the scoreboard (e.g. USA, FRA)."""


def estimate_serve(clip_path: str, model: str = "gemini-3.1-pro-preview", client=None) -> "ServeAnalysis":
    """Single call returning both image keypoints and camera-independent court placement."""
    from google import genai
    from google.genai import types
    import video_clipper as vc
    client = client or genai.Client()
    data = vc.read_muted_bytes(clip_path)  # video-only: never send audio to the model
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=data, mime_type="video/mp4"), SERVE_ANALYSIS_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ServeAnalysis,
            temperature=0.0,
        ),
    )
    return resp.parsed


class SpikeAnalysis(BaseModel):
    """Attack (spike): image keypoints for the per-clip arc + camera-independent
    court placement (where it was hit from, where it landed)."""
    keypoints: list[TrajPoint] = Field(default_factory=list, description="Points labelled 'attack_contact' (ball at the attacker's hand) and 'landing' (ball where it lands or is first dug).")
    attacking_team: str = Field(default="unknown", description="3-letter team code from the scoreboard (e.g. USA, FRA).")
    attacker_player: str = ""
    attack_from_lateral: float = Field(default=0.5, description="0-1 across the ATTACKING team's net width, 0=left 1=right as seen by that team facing the net.")
    attack_zone: int = Field(default=0, description="Front-row attack position: 4=left, 3=middle, 2=right (0 if a back-row attack or unknown).")
    landing_depth: float = Field(default=0.5, description="0-1 in the DEFENDING half: 0=at the net, 1=at the defending endline.")
    landing_lateral: float = Field(default=0.5, description="0-1 across the DEFENDING half width, 0=left 1=right as seen by the defending team facing the net.")
    landing_zone: int = Field(default=0, description="Defending zone 1-6 where the ball lands/is dug (0 if unknown).")
    confidence: float = 0.0


SPIKE_ANALYSIS_PROMPT = """This clip contains a volleyball SPIKE (attack). Judge only from what is VISIBLE (do not use sound).

Return image points (y,x in 0-1000) for:
- "attack_contact": the ball at the instant the attacker's hand strikes it (near/above the net)
- "landing": the ball where it lands in the opponent court, or where a defender first digs it

ALSO report the attack in COURT coordinates (not image pixels), using the field descriptions.
The lateral axes are from each TEAM's own point of view facing the net, so they must NOT depend
on the camera angle. For attacking_team use the 3-letter scoreboard code (e.g. USA, FRA)."""


def estimate_spike(clip_path: str, model: str = "gemini-3.1-pro-preview", client=None) -> "SpikeAnalysis":
    """Single video-only call: attack keypoints + camera-independent court placement."""
    from google import genai
    from google.genai import types
    import video_clipper as vc
    client = client or genai.Client()
    data = vc.read_muted_bytes(clip_path)
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=data, mime_type="video/mp4"), SPIKE_ANALYSIS_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SpikeAnalysis,
            temperature=0.0,
        ),
    )
    return resp.parsed


SPIKE_FLIGHT_LABELS = ["attack_contact", "landing"]


def points_from_json(text: str) -> list[TrajPoint]:
    import json
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("points") or data.get("results") or [data]
    return [TrajPoint.model_validate(d) for d in data]


def fit_arc(flight_px: list[tuple[float, float]], samples: int = 60) -> list[tuple[int, int]]:
    """Smooth parametric curve through ordered flight points (image pixels).

    Fits x(t), y(t) as polynomials (deg 2 for >=3 points, deg 1 for 2). Handles a
    near-vertical path where x barely changes (a plain y=f(x) parabola would fail).
    """
    n = len(flight_px)
    if n < 2:
        return [(int(px), int(py)) for px, py in flight_px]
    t = np.linspace(0.0, 1.0, n)
    xs = np.array([p[0] for p in flight_px], dtype=float)
    ys = np.array([p[1] for p in flight_px], dtype=float)
    deg = 2 if n >= 3 else 1
    cx = np.polyfit(t, xs, deg)
    cy = np.polyfit(t, ys, deg)
    tt = np.linspace(0.0, 1.0, samples)
    return [(int(round(np.polyval(cx, u))), int(round(np.polyval(cy, u)))) for u in tt]


def _to_px(pt: TrajPoint, w: int, h: int) -> tuple[float, float]:
    return (pt.x / 1000.0 * w, pt.y / 1000.0 * h)


def flight_arc_px(points: list[TrajPoint], w: int, h: int, flight_labels: list[str] = None):
    """Return (arc_pixels, ordered_flight_points, by_label) for a set of keypoints."""
    labels = flight_labels or FLIGHT_LABELS
    by_label = {p.label: p for p in points}
    flight = [by_label[l] for l in labels if l in by_label]
    flight_px = [_to_px(p, w, h) for p in flight]
    arc = fit_arc(flight_px) if len(flight_px) >= 2 else []
    return arc, flight, by_label


def grab_frame(video_path: str, frac: float = 0.4):
    """Read a representative BGR frame from a video (default ~40% through)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(total * frac)))
    ok, frame = cap.read()
    if not ok:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"could not read a frame from {video_path}")
    return frame


def render_trajectory(clip_path: str, points: list[TrajPoint], out_video: str,
                      preview_png: Optional[str] = None, flight_labels: list[str] = None) -> dict:
    """Overlay the fitted arc + keypoints on every frame -> annotated mp4.
    Also writes a preview PNG. Returns a small summary dict."""
    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open clip: {clip_path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    # ordered flight points that are present
    arc, flight, by_label = flight_arc_px(points, w, h, flight_labels)

    def annotate(frame):
        # arc
        if len(arc) >= 2:
            for i in range(1, len(arc)):
                cv2.line(frame, arc[i - 1], arc[i], (0, 220, 255), 3, cv2.LINE_AA)
        # flight keypoints (filled circles + labels)
        for p in flight:
            px, py = _to_px(p, w, h)
            cv2.circle(frame, (int(px), int(py)), 7, (0, 0, 255), -1, cv2.LINE_AA)
            cv2.putText(frame, p.label, (int(px) + 8, int(py) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
        # players (open squares)
        for l in PLAYER_LABELS:
            if l in by_label:
                px, py = _to_px(by_label[l], w, h)
                cv2.rectangle(frame, (int(px) - 9, int(py) - 9), (int(px) + 9, int(py) + 9),
                              (0, 255, 0), 2, cv2.LINE_AA)
                cv2.putText(frame, l, (int(px) + 10, int(py) + 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
        return frame

    os.makedirs(os.path.dirname(os.path.abspath(out_video)), exist_ok=True)
    writer = cv2.VideoWriter(out_video, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    preview_saved = False
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = annotate(frame)
        writer.write(frame)
        # preview: a frame ~40% through the clip (mid-flight)
        if preview_png and not preview_saved and frame_idx >= int(cap.get(cv2.CAP_PROP_FRAME_COUNT) * 0.4):
            cv2.imwrite(preview_png, frame)
            preview_saved = True
        frame_idx += 1
    writer.release()
    cap.release()
    if preview_png and not preview_saved and frame_idx:  # very short clip
        cap2 = cv2.VideoCapture(clip_path); ok, frame = cap2.read(); cap2.release()
        if ok:
            cv2.imwrite(preview_png, annotate(frame))

    return {
        "width": w, "height": h,
        "flight_points": [p.label for p in flight],
        "has_arc": len(arc) >= 2,
        "video": out_video, "preview": preview_png,
    }
