# Volleyball Video Action Detector

A PyQt6 desktop app (PC only) that finds volleyball actions in a video and extracts
a short clip around each one, using Gemini's native video+audio understanding.
Started as a serve-only proof of concept; now a general, extensible app.

![flow](docs-not-included) <!-- source → model+actions → chunked detection → clips -->

## What works today

- **Source**: a **local mp4** (uploaded to the Gemini File API) **or** a YouTube /
  public URL (analyzed by reference).
- **Model selection**: dropdown (Pro 3.1 recommended, Flash 2.5 cheapest, …) — editable
  for custom ids.
- **Action selection**: checkboxes. **Serve is validated** (referee-whistle audio cue
  makes it reliable); Spike / Block / Reception / Dig are included but **experimental**
  (no whistle anchor → expect lower accuracy until tuned).
- **Long videos**: automatic **chunking** into ≤5-min windows with overlap, so recall
  stays high; runs on a **background thread** with a progress bar + live log.
- **Clips**: one mp4 per detection (configurable seconds before/after, with audio) into
  a folder you choose, plus an `_actions.json` manifest. Double-click a results row to
  play its clip.

### Validated accuracy (serve)

On a human-reviewed 5-min window (France–USA VNL 2025): **gemini-3.1-pro-preview = 7/7
correct**, gemini-2.5-flash = 6/7 (one false positive, one miss). Pro 3.1 is the
default/recommended model.

## Why this approach (vs a classic CV pipeline)

Feeding the video straight to a model with **native video + audio** removes the
brittle download→frame-extract→pose/ball-track→classify pipeline. For **serves** the
audio channel is decisive: a **referee whistle precedes every serve**, giving a
near-unambiguous cue a frames-only system throws away. Output is a Gemini
structured-JSON array (Pydantic schema) — no fragile text parsing.

## Setup

Needs a Google Gemini API key (`GOOGLE_API_KEY` env var, or paste it into the app).
No system ffmpeg/yt-dlp needed — a static ffmpeg ships via `imageio-ffmpeg`.

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

## Run the app

```bash
./.venv/Scripts/python.exe run_gui.py
```

1. Pick a local mp4 (or paste a URL).
2. Choose a model and tick the actions (Serve on by default).
3. Optionally set start/end and clip folder + lengths.
4. **Detect actions** → watch the log; results fill the table; clips land in the folder.

## Cost (measured)

~6k input tokens per minute of video at low resolution. A full ~2h match ≈ 720k input
tokens per pass → **~$1.60 on Pro 3.1**, **~$0.13 on Flash 2.5**. Pro models are
paid-only (no free tier). Output tokens are negligible.

## Project layout

| File | Purpose |
|---|---|
| `run_gui.py` / `gui.py` | Entry point + PyQt6 UI and the background `DetectionWorker`. |
| `action_detector.py` | `VideoAnalyzer` (upload/URL), multi-action prompt, JSON parse, chunking, merge. |
| `actions_registry.py` | Action types + prompt cues (serve validated; others experimental). |
| `video_clipper.py` | ffmpeg clip cutting, duration probe, URL window download. |
| `gemini_models.py` | Curated model dropdown list. |
| `serve_detector.py` | Original validated serve-only prototype + CLI (kept). |
| `tools/` | CLI scripts: `run_live.py`, `extract_serve_clips.py`. |
| `tests/` | 50 offline unit tests (no network/API key). |

Run tests: `./.venv/Scripts/python.exe -m pytest tests -q`

## Serve trajectories (add-on)

Tick **"Estimate serve trajectories + placement chart"** in section 3 (or run
`tools/trajectories.py <clips_dir>`). For each serve clip it asks Gemini for a few
**keypoints it localizes well** — ball at serve contact, at the net, and at reception —
then fits a smooth arc through them and overlays it (`trajectory.py`). Right-click a
result row to open the clip, the annotated trajectory video, or its image.

It also builds a **top-down placement chart** (`serve_placement.png`, "Open placement
chart" button, `court_chart.py`): every serve drawn on one canonical court, **camera-
independent**, serving team always at the bottom, receiving zones 1-6 marked, arrows
origin→target, colored by server. One glance shows where each server places the ball.

**Why top-down and not an overlay on the video frame?** A broadcast cuts between cameras
(behind-baseline, sideline, replays), so image-space points from different serves aren't
comparable — overlaying them on one frame is misleading. Instead, `estimate_serve` asks
Gemini for the serve in **court coordinates defined relative to each team's own
orientation** (so they don't depend on the camera), and the chart plots those. Verified:
the same reference frame comes back whether the clip was shot from behind the court or the
sideline.

This gives serve **placement/direction**, not physical speed/height. Why Gemini keypoints
and not frame-by-frame ball tracking? A broadcast volleyball is ~5px and motion-blurred —
the hard case for detectors — while the server/receiver/zone are big and easy, so we lean
on Gemini's strength. A dense tracker (TrackNet / vball-net) can drop in later for a
physically accurate arc/speed.

## Persistent results + filters

Every run's detections are appended to a persistent store (`results/results_db.json`,
`results_store.py`) that survives between sessions. The **filter bar** above the results
table slices the whole history by **Team / Player / Action**; the table and the placement
chart both follow the current filter. **Color by team** (France vs USA) or **player**. So
after a full match you can ask "show only USA #8's serves" or "France serves to zone 5"
and the chart redraws for just that slice — the answer to keeping 80+ serves readable.
"Clear stored results" empties the store. Team labels are normalized (scoreboard 3-letter
code, upper-cased) so 'FRA'/'France' don't fragment the grouping.

**Chart modes** (`court_chart.py`, chosen in the "Chart" dropdown; all follow the filter):
- **Arrows** — one origin→target arrow per serve, colored by team or player.
- **Heatmap** — smooth density of where serves land over the receiving half, with per-zone
  counts. The scouting payoff over a whole match.
- **Split by team** — one arrow panel per serving team, side by side, for comparison.

## Video-only (no audio)

Analysis never uses the video's sound. Real game footage has no commentary and no reliable
whistle, so depending on audio would be a deployment trap. Local uploads and grounding
clips are audio-stripped before they reach the model (`video_clipper.strip_audio`), and the
prompts use visual cues only. Verified: video-only serve detection found the same serves as
the earlier audio-aided run — the whistle was a bonus, not a dependency. (The YouTube-URL
detection path still lets Gemini fetch audio by reference; local-file use is fully muted.)

## Known limits / next steps

- **Spikes**: *detection* is validated as mostly-correct and usable (select the Spike action
  → detections + clips). *Placement* is intentionally NOT shipped — spikes are fast and
  happen in a crowded net area, and the keypoint grounding proved too noisy (unstable
  player/team, landings stuck at the net). `trajectory.estimate_spike` exists as a
  foundation but isn't wired; a dense tracker (TrackNet) would likely be needed for a
  trustworthy spike chart. Block/reception/dig remain experimental/unvalidated.
- Serve trajectory/placement is placement-level (not speed/height). A true top-down court
  plot via court-corner homography, and a dense tracker for physical arcs, are the upgrades.
- Recall on a full match isn't formally measured; chunking + optional multi-pass consensus
  (run 2 models, keep agreements) is the lever if recall proves low.
