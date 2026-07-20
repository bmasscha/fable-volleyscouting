# Video review tool — link scouting JSON to match video, filter & clip actions

> **Handoff spec for AI coding agents.** This is an approved implementation plan
> for a new, standalone application in the `fable_scouter` repo. It references
> real files/functions in this codebase — read `core/events.py`,
> `core/models.py`, `core/stats.py`, `core/persistence.py`, and
> `tablet/TRANSLATION.md` before starting. Do **not** change the rules engine or
> match semantics; the pytest suite (`tests/`) and the tablet conformance
> contract (`tablet/conformance/`) must stay green. Build in the order in
> "Build order & critical files". Verify at the real surfaces per
> `.claude/skills/verify/SKILL.md`, not just with unit tests.

## Context

fable_scouter produces an event log where **every action carries a wall-clock
`ts`** (unix seconds): the tablet stamps `Date.now()/1000`, the desktop stamps
`time.time()` (`ui/main_window.py:558,589`). Each skill event also carries its
`team`, `player_id`, and `rating`, and every player carries a `Role` (incl.
`LIBERO`). That is everything needed to line the scouting up against a video of
the same match and pull out exactly the touches a coach wants to watch.

**Goal:** a standalone review application (desktop PyQt6 + tablet PWA, sharing a
new pure core) that loads an exported match `.json` and a video, lets the user
filter actions ("all attacks by #12 Away", "all serve-receive by the Home
libero", "all failed serves by #7"), and **plays** the matching 7-second
fragments back-to-back. The **desktop** additionally **exports** fragments as
`.mp4` files and highlight reels; the **tablet** is playback/review only.

**Decisions (confirmed with Bert):**
- **Standalone app, shared core** — separate desktop window + tablet route, both
  loading the exported JSON; a new pure-Python query/sync core mirrored to TS.
- **Tablet = playback only** (no file export). Desktop = full export.
- **Fixed clip window: 2 s before → 5 s after each event** (7 s; absorbs small
  sync mismatch and shows enough rally). Named constants `PRE_ROLL=2.0`,
  `POST_ROLL=5.0`.
- **Two video sources: a local file (mp4/avi/mkv/…) OR a YouTube video.** Both
  are reviewable on both platforms; desktop export works for both.
- No engine/rules change → **conformance fixtures untouched**.

## Video sources: local file and YouTube

The same anchor-based sync and 7 s clip windows apply to both; only the
player and the export path differ. `VideoLink` carries `source_kind`
(`"file" | "youtube"`) and `source_ref` (a path/handle, or a YouTube video id),
so filtering, sync, and the clip list are source-agnostic — a single control
interface `seek(t) / play() / pause() / currentTime()` sits over both.

- **YouTube playback** uses the **YouTube IFrame Player API** (`seekTo`,
  `playVideo`, `pauseVideo`, `getCurrentTime`, `onStateChange`) — a natural fit
  in a browser and controllable from Qt via an embedded web view. Clip playback
  = `seekTo(start); play()`, poll `getCurrentTime() >= end → pause()`, identical
  to the file path.
- **YouTube export (desktop only)** uses **`yt-dlp --download-sections
  "*start-end"`** (with ffmpeg) to fetch just the 7 s window, then the same
  naming/concat as local export. This downloads from YouTube (needs network;
  intended for the user's own match footage) — surfaced in the UI, and skipped
  entirely on the tablet, which never exports.

## Core problem: synchronization

Events are wall-clock; the video has its own 0-based timeline. Map with
**anchors** — one `(event_ts, video_seconds)` pairing the user sets by seeking
the video to a known action and clicking "Sync here".

- **1 anchor** → global offset: `video_t(ts) = ts - (anchor.event_ts - anchor.video_seconds)`.
- **≥2 anchors** → piecewise-linear interpolation between the surrounding
  anchors (also corrects clock-rate drift); clamp to the nearest anchor's offset
  outside the anchored range. This is what handles **recording gaps** (camera
  paused between sets/timeouts) — the user drops one anchor per continuous
  segment (typically one per set).
- **Auto-suggest** an initial offset from the video file's modification time
  (`video_mtime - duration ≈ recording start`) so the first anchor is close;
  the user nudges from there.
- The 2 s pre-roll makes the review forgiving of a rough single anchor.

## New shared core (pure, mirrored TS ↔ Python)

**`core/query.py`** (+ `tablet/src/core/query.ts`): flatten events into an
`Action` list and filter it.
- `build_actions(events, teams) -> list[Action]` where `Action` = index, `ts`,
  `set_number` (tracked from `SetStartEvent`), `rally_index` (increment on each
  `ServeEvent`), `team_key`, `player_id`, `player_number`, `player_name`,
  `role`, `skill`, `rating`, plus `overpass`/`block_touch`/`trajectory`. Reuses
  `core/stats.py::_EVENT_SKILL`, `Skill`, `Rating`, and `Team.player()`.
- `filter_actions(actions, spec)` where `spec` selects by team (home/away/any),
  player (id or number), **role** (e.g. `Role.LIBERO` → the libero filter),
  skill, rating (or "any"), and set. Returns matches sorted by `ts`.
- Convenience: the three worked examples map to specs directly (attack+away+#12;
  reception+home+role=libero; serve+rating=ERROR+#7).
- No engine dependency (set/rally derived in one pass) → cheap and testable.

**`core/video_sync.py`** (+ `tablet/src/core/videoSync.ts`):
- `VideoLink` = `{ source_kind, source_ref, anchors: [(event_ts,
  video_seconds)], pre_roll, post_roll }`.
- `event_to_video_time(link, ts) -> float | None` (piecewise as above);
  `clip_window(link, ts) -> (start, end)` = `(video_t - pre_roll, max(...,
  video_t + post_roll))`, clamped `>= 0`.
- `suggest_offset(video_mtime, duration)`.

## Desktop review app (PyQt6)

- **Entry** `video_main.py` (mirrors `main.py`: dark palette from `ui/theme.py`,
  registry init). Opens `ui/video_review.py::VideoReviewWindow`.
- **Load**: "Open match…" (reuse `core/persistence.load_match` → config, teams,
  events) + "Open video…" (local file) / "Use YouTube URL…". Persist the link in
  a **sidecar** next to the match file (`<match>.videolink.json`: source_kind,
  source_ref, anchors) so it reopens ready.
- **Playback (unified web-view player).** To support YouTube alongside local
  files with **one** control model, host an HTML player page in a
  `QWebEngineView` (`PyQt6-WebEngine`): a local file plays via an HTML5
  `<video>` (served from a tiny local origin), a YouTube video via the IFrame
  API `<iframe>`. Python drives `seek/play/pause` and reads `currentTime` over
  **`QWebChannel`** — the exact same interface the tablet uses, maximizing shared
  logic. Transport bar, timeline scrubber, playback-speed + frame-step (film
  study), and a translucent caption overlay showing the current action
  (player/skill/rating/set) live in the HTML player. *(Alternative if WebEngine
  proves heavy: `QMediaPlayer`+`QVideoWidget` for local files and WebEngine only
  for YouTube — decided in step 2; the plan assumes the unified WebEngine path.)*
- **Filter panel** (left): team, player dropdown, role, skill, rating selects →
  drives `filter_actions`; the result is the **clip list** (ts, set, score-ish
  label). Selecting a clip seeks to its window start, plays, auto-pauses at the
  end (poll `positionChanged`); "Play all" runs the list sequentially. Keyboard
  rapid-review: next/prev clip, replay, space = play/pause.
- **Sync controls**: "Sync here" adds an anchor from the current action + video
  position; an anchor list allows edit/delete; live readout of the mapping.
- **Export** (`core/video_export.py`, subprocess). **Local file**: per-clip and
  "Export all matching" via ffmpeg — default stream-copy
  (`ffmpeg -ss <start> -to <end> -i in -c copy out.mp4`), "frame-accurate
  (re-encode)" toggle. **YouTube**: same windows via
  `yt-dlp --download-sections "*start-end" --force-keyframes-at-cuts` (+ffmpeg).
  **Filename** `{name_slug}_{team}_{skill}[_{rating}]_ts{unix_seconds}.mp4`
  (e.g. `player_x_away_attack_ts12458965.mp4`). **Highlight reel**: concat all
  matches into one `.mp4` (ffmpeg concat demuxer). Also "Export action list"
  (CSV/JSON with video timecodes). Prefer **bundled `ffmpeg.exe`** + a resolved
  `yt-dlp`, fall back to PATH (note for later PyInstaller packaging; neither is
  on the engine path).

## Tablet review route (Preact) — playback only

- New `tablet/src/VideoReview.tsx`, reached from the startup / Saved-matches
  screen; loads a match from the IndexedDB archive (`matchStore.getMatch`).
- **Source**: pick a local video via `<input type=file>` (object URL) / File
  System Access, **or** paste a **YouTube URL**. Persist `source_kind` +
  `source_ref` (+ anchors) in IndexedDB keyed by match id (reusing the
  `matchStore` pattern); for a file handle, re-request permission per session
  with a graceful "re-select video" fallback.
- **Player** behind one control interface: local file → `<video>`; YouTube →
  IFrame Player API `<iframe>`. Same mirrored `query.ts` filter panel + clip
  list. Tap a clip → `seek(start); play()`, stop when `currentTime >= end`
  (`timeupdate` for `<video>`, a poll for the iframe); "Play all" chains them.
  "Sync here" sets an anchor from the current action + `currentTime`. **No
  export.**

## Extra ideas folded in (beyond the ask)

- Piecewise multi-anchor sync (per-set anchors) — in the core design above.
- Auto-suggested initial offset from video mtime.
- Highlight-reel concat + action-list CSV/JSON export (desktop).
- In-player caption overlay (both) and playback-speed/frame-step (desktop).
- Optional **burned-in labels** on exported clips (ffmpeg `drawtext`) — deferred
  to a phase-2 toggle (needs a bundled font); not in v1.

## Build order & critical files

1. **Shared core** — `core/query.py`, `core/video_sync.py` (+ `tests/test_query.py`,
   `tests/test_video_sync.py`); then TS mirrors `tablet/src/core/query.ts`,
   `tablet/src/core/videoSync.ts` (+ vitest) per `tablet/TRANSLATION.md`.
2. **Desktop** — `video_main.py`, `ui/video_review.py`, HTML player page
   (`ui/player/…` served to `QWebEngineView`), export helper
   `core/video_export.py` (ffmpeg + yt-dlp subprocess wrapper; pure logic
   testable without Qt). New deps: `PyQt6-WebEngine`, `yt-dlp` (dev/runtime),
   bundled `ffmpeg`.
3. **Tablet** — `tablet/src/VideoReview.tsx`, video-link storage in
   `tablet/src/matchStore.ts`, route wiring in `App.tsx`.

## Verification

- **Core**: `.venv\Scripts\python.exe -m pytest tests -q` (query + sync round-trips,
  libero/rating/team specs, piecewise anchor math, clip-window clamping);
  `npm --prefix tablet test` for the TS mirrors. Full suites stay green;
  **no conformance regen** (new modules aren't in the engine snapshot).
- **ffmpeg export**: generate a throwaway clip (`ffmpeg -f lavfi -i testsrc=30`),
  export a window, assert the output exists and is ~7 s. YouTube export path is
  exercised with a short public test video when network is available (skipped
  offline; the command-builder logic is unit-tested without network).
- **Desktop UI** (per `.claude/skills/verify`): offscreen `QT_QPA_PLATFORM=offscreen`,
  load a sample match + generated video, apply a filter, assert the clip list
  matches expected actions and a "Sync here" anchor maps a known action to the
  right video second; `w.grab().save(...)` for evidence.
- **Tablet** (Playwright msedge on `vite preview`): load an archived match +
  a generated video, apply "attacks by away #N", assert the clip list and that
  tapping a clip seeks `<video>.currentTime` into the expected window.

## Out of scope / notes

- Reads matches; never edits the scouting log (review is non-destructive).
- Desktop-native saves lack the tablet's match `id`; the desktop sidecar is
  keyed by match **file path**, the tablet by archive **id** — no shared id needed.
- **YouTube playback needs network**; a chosen YouTube video that later goes
  private/removed can't be reviewed — surfaced as a clear error, and the user can
  re-point the link at a local file. YouTube export downloads via `yt-dlp`
  (network + the source's terms; intended for the user's own footage).
- `PyQt6-WebEngine` is a new, heavier dependency (matters for later PyInstaller
  packaging); the step-2 fallback keeps `QMediaPlayer` for local files if
  WebEngine is problematic, with WebEngine used only for YouTube.
- Burned-in labels, cloud sharing, and auto-detecting sync from audio/scoreboard
  OCR are future phases.
