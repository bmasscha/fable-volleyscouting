# Fable Scouter — real-time volleyball match scouting

Touch-first PyQt6 app for scouting volleyball matches: live rally entry with
ball trajectories and `! - + #` ratings, automatic score / rotation / side
switching per official rules, and per-player statistics reports.

## Run

```
.venv\Scripts\python.exe main.py
```

(First time: `python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`)

## Scouting workflow (one screen, tap + drag)

| Phase | Gesture |
|---|---|
| **Serve** | Drag from behind the end line to the landing spot. Auto-rated `+`; a drag ending out of court is auto-rated `!` (fault). The small chips above the buttons re-rate the serve (`#` = ace). |
| **Reception** | The receiver nearest the landing spot is preselected (tap another player to override). Tap one of the big `! - + #` buttons. `!` = aced. |
| **Attack** | Drag the attack trajectory — the attacker is picked from the drag start — then rate it. `#` = kill (point), `!` = error. You may also skip the reception rating and drag the attack directly (reception logs as `+`). |
| **Defense** | The digger nearest the attack landing is preselected; rate the dig, or directly drag the counter-attack. |
| **Point / chaos** | `◀ point` / `point ▶` award the rally manually (net faults, referee calls). |
| **Undo** | `⟲` undoes any number of steps (also `Ctrl+Z`). Keys `1-4` = `! - + #`. |

Substitution: tap a bench player, then the court player they replace.
Libero exchanges work the same (not counted as subs); the app prompts when
the libero must leave (front row / serving rotation). Setter tokens are
blue, libero red.

**Formations:** tokens stand where a real 5-1 team stands, not on a
rotational grid — serve receive (both outside hitters + libero passing,
setter hiding legally per rotation, middle at the net), then attack
positions after the reception (OH → 4/6, MB → 3, libero → 5,
setter/opposite → 2/1, back-row setter penetrating), block + perimeter
on defence. All six receive charts satisfy the FIVB overlap rules.
Teams without an identifiable setter (or with the toolbar *Formations*
toggle off) fall back to the rotational grid; a 6-2 is handled by
treating the back-row setter as the acting setter.

Scores, side-out rotation (clockwise when a team wins serve back), set ends
(25 pts / 2-point lead; deciding set to 15 with the side switch at 8) and
the automatic side switch between sets are all handled by the engine.
Manual score/serve corrections: toolbar → *Adjust*. Timeouts: the `T`
buttons.

## Reports

Toolbar → *Report*: per-player serve / reception / attack / dig counts,
efficiency and points, plus the team points breakdown. Export as CSV or
printable HTML.

## Files

- Matches autosave after every rally to `matches\` (JSON; crash-safe,
  reload via *Load* — the full event log replays).
- Team rosters live in `rosters\` (toolbar → *Rosters* to edit).

## Architecture

- `core\` — pure-Python rules engine (no Qt): event-sourced match log,
  rotation math, rule validation, stats. `tests\` covers it with 256 tests
  (`.venv\Scripts\python.exe -m pytest tests -q`), including a scripted
  full 5-set match simulation.
- `ui\` — PyQt6 widgets: court scene, tokens, rating bar, benches, dialogs.
