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
