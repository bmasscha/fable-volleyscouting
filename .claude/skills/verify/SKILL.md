---
name: verify
description: How to drive the real fable_scouter apps (desktop PyQt6 + tablet PWA) to verify changes end-to-end, beyond the test suites.
---

# Verifying fable_scouter changes at the real surfaces

Two surfaces: desktop PyQt6 app (`main.py`, `ui/`) and tablet PWA (`tablet/`).
Tests alone are not verification — drive the app.

## Tablet PWA (Playwright, headless msedge)

1. `npm --prefix tablet run build`
2. `npm --prefix tablet run preview -- --host 127.0.0.1 --port 4173` (background;
   `vite preview` binds IPv6-only without `--host`). App URL:
   `http://127.0.0.1:4173/fable-volleyscouting/` (vite `base`).
3. Playwright is a devDependency of `tablet/` — the drive script must RESOLVE
   from there: copy it into `tablet\` (e.g. `.verify_drive.mjs`, delete after)
   or run node with cwd-independent resolution. `chromium.launch({ channel:
   "msedge", headless: true })` — no browser download needed.
4. UI flow: landing screen → "New match" → setup screen (all defaults are
   valid: HOME serves, HOME left) → "Start match".
5. Court drags: the SVG is `svg.court-svg`, viewBox `-13 -2.5 26 14`
   (metres, net at x=0, LEFT half x<0). Map court→client:
   `scale = min(bbox.w/26, bbox.h/14)`, content centered in the bbox
   (preserveAspectRatio meet). Use `mouse.down/move(×several)/up`.
6. Read back recorded events from
   `localStorage["fable-scouter.tablet.autosave"]` → `.events`.
7. Kill the server: TaskStop only kills the npm wrapper — kill the vite child
   via `Get-NetTCPConnection -LocalPort 4173` → `Stop-Process`.

## Desktop PyQt6 (offscreen QTest)

- `QT_QPA_PLATFORM=offscreen`, run with `.venv\Scripts\python.exe` from repo
  root (`sys.path` needs the repo; `tests` is a package —
  `from tests.test_engine import make_teams, set_start_event`).
- Build a running match like the `win` fixture in `tests/test_ui_blocks.py`
  (MainWindow + engine + SetStart/Serve/Reception events), `w.show()`,
  `w.refresh()`, `app.processEvents()`.
- Real drags: `CourtView` is a QGraphicsView; scene metres × `ui.court_view.M`
  = scene px. `QTest.mousePress/mouseMove/mouseRelease` on `w.court.viewport()`
  at `w.court.mapFromScene(QPointF(x*M, y*M))`; several intermediate moves,
  distance must exceed the tap threshold.
- Real button clicks: `w.rating_bar.findChildren(QPushButton)` and match text.
- Evidence: `w.grab().save(path)` — offscreen renders ALL text as tofu boxes
  (font artifact on this machine, not a bug); arrows/tokens/colors are real.
- `PYTHONIOENCODING=utf-8` when printing ratings/warnings (cp1252 console).

## Gotchas

- Conformance goldens (`tablet/conformance/`) are regenerated only via
  `.venv\Scripts\python.exe tools\gen_conformance.py`; after a core change,
  verify existing goldens moved only in intended fields (compare
  `git show HEAD:<file>` vs new JSON per step).
