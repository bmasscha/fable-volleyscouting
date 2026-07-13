"""Match / roster persistence. Plain JSON, crash-safe writes."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .events import Event, event_from_dict, event_to_dict
from .models import MatchConfig, Team

FILE_VERSION = 1


def _atomic_write(path: Path, text: str) -> None:
    """Write via temp file + replace so a crash never corrupts the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_match(path: str | Path, config: MatchConfig,
               teams: dict[str, Team], events: list[Event]) -> None:
    data = {
        "version": FILE_VERSION,
        "config": config.to_dict(),
        "teams": {k: t.to_dict() for k, t in teams.items()},
        "events": [event_to_dict(e) for e in events],
    }
    _atomic_write(Path(path), json.dumps(data, indent=1))


def load_match(path: str | Path):
    """Returns (config, teams, events)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    config = MatchConfig.from_dict(data["config"])
    teams = {k: Team.from_dict(t) for k, t in data["teams"].items()}
    events = [event_from_dict(d) for d in data["events"]]
    return config, teams, events


# ---------------------------------------------------------- live event log
#
# Besides the full-snapshot autosave (save_match), the UI keeps an append-only
# .log.jsonl file: one JSON object per line, flushed and fsynced per event, so
# a crash or power loss never costs more than the line being written. The log
# is self-contained (header line carries config + teams) and replays undos, so
# a match can be rebuilt from the log alone.

def log_path(match_path: str | Path) -> Path:
    """Sidecar live-log path for a match file (match.json -> match.log.jsonl)."""
    return Path(match_path).with_suffix(".log.jsonl")


class EventLogWriter:
    """Append-only realtime event log. (Re)created to mirror the engine's
    current event list, then appended to synchronously per event."""

    def __init__(self, path: str | Path, config: MatchConfig,
                 teams: dict[str, Team], events: list[Event] = ()):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self._path, "w", encoding="utf-8")
        self._write({"type": "header", "version": FILE_VERSION,
                     "config": config.to_dict(),
                     "teams": {k: t.to_dict() for k, t in teams.items()}})
        for e in events:
            self.log_event(e)

    def _write(self, obj: dict) -> None:
        self._f.write(json.dumps(obj) + "\n")
        self._f.flush()
        os.fsync(self._f.fileno())

    def log_event(self, event: Event) -> None:
        self._write(event_to_dict(event))

    def log_undo(self) -> None:
        self._write({"type": "undo"})

    def close(self) -> None:
        try:
            self._f.close()
        except OSError:
            pass


def read_event_log(path: str | Path):
    """Rebuild (config, teams, events) from a live log. Undo records pop the
    last event; unparseable lines (e.g. truncated by a crash) are skipped."""
    config = teams = None
    events: list[Event] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = d.get("type")
        if kind == "header":
            config = MatchConfig.from_dict(d["config"])
            teams = {k: Team.from_dict(v) for k, v in d["teams"].items()}
        elif kind == "undo":
            if events:
                events.pop()
        else:
            try:
                events.append(event_from_dict(d))
            except (KeyError, TypeError, ValueError):
                continue
    if config is None or teams is None:
        raise ValueError(f"{path}: no header record")
    return config, teams, events


def load_match_with_log(path: str | Path):
    """Load a match, recovering from the live log when it is ahead of the
    snapshot (crash between the last event and the last autosave).
    Returns (config, teams, events, recovered_count)."""
    config, teams, events = load_match(path)
    lp = log_path(path)
    if lp.exists():
        try:
            lc, lt, levents = read_event_log(lp)
        except (OSError, ValueError, KeyError):
            return config, teams, events, 0
        if len(levents) > len(events):
            return lc, lt, levents, len(levents) - len(events)
    return config, teams, events, 0


# ------------------------------------------------------------ roster library

def rosters_dir(base: str | Path | None = None) -> Path:
    d = Path(base) if base else Path(__file__).resolve().parent.parent / "rosters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _team_filename(team: Team) -> str:
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in team.name).strip()
    return (safe or "team") + ".json"


def save_team(team: Team, base: str | Path | None = None) -> Path:
    path = rosters_dir(base) / _team_filename(team)
    _atomic_write(path, json.dumps(team.to_dict(), indent=1))
    return path


def load_teams(base: str | Path | None = None) -> list[Team]:
    teams = []
    for p in sorted(rosters_dir(base).glob("*.json")):
        try:
            teams.append(Team.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, KeyError):
            continue
    return teams


def delete_team(team: Team, base: str | Path | None = None) -> None:
    path = rosters_dir(base) / _team_filename(team)
    if path.exists():
        path.unlink()
