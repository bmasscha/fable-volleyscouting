"""Immutable match events. The event log is the single source of truth:
current match state is always derived by replaying events (see engine.py),
which makes undo trivially correct (drop last event, replay)."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import ClassVar

from .models import Rating

# (x1, y1, x2, y2) in court metres; net at x=0, sidelines y=0 and y=9.
Trajectory = tuple[float, float, float, float]

_REGISTRY: dict[str, type] = {}


def _register(cls):
    _REGISTRY[cls.TYPE] = cls
    return cls


@dataclass(frozen=True)
class Event:
    TYPE: ClassVar[str] = "event"


@_register
@dataclass(frozen=True)
class SetStartEvent(Event):
    TYPE: ClassVar[str] = "set_start"
    set_number: int
    lineups: dict            # team_key -> [player_id P1..P6]
    liberos: dict            # team_key -> [player_id, ...]
    serving_team: str
    left_team: str


@_register
@dataclass(frozen=True)
class ServeEvent(Event):
    TYPE: ClassVar[str] = "serve"
    team: str
    player_id: str
    rating: Rating = Rating.GOOD          # '+' is the default serve score
    trajectory: Trajectory | None = None


@_register
@dataclass(frozen=True)
class ReceptionEvent(Event):
    TYPE: ClassVar[str] = "reception"
    team: str
    player_id: str
    rating: Rating


@_register
@dataclass(frozen=True)
class AttackEvent(Event):
    TYPE: ClassVar[str] = "attack"
    team: str
    player_id: str
    rating: Rating
    trajectory: Trajectory | None = None


@_register
@dataclass(frozen=True)
class DigEvent(Event):
    TYPE: ClassVar[str] = "dig"
    team: str
    player_id: str
    rating: Rating


@_register
@dataclass(frozen=True)
class RallyPointEvent(Event):
    """Manual rally termination: net fault, referee decision, penalty point,
    or anything the scouter could not follow. Awards the point to `team`."""
    TYPE: ClassVar[str] = "rally_point"
    team: str
    reason: str = "manual"


@_register
@dataclass(frozen=True)
class SubstitutionEvent(Event):
    TYPE: ClassVar[str] = "substitution"
    team: str
    player_out: str
    player_in: str


@_register
@dataclass(frozen=True)
class LiberoSwapEvent(Event):
    """Toggles the libero: if off court, enters for partner; if on court,
    partner returns. Not a substitution (unlimited, not counted)."""
    TYPE: ClassVar[str] = "libero_swap"
    team: str
    libero_id: str
    partner_id: str


@_register
@dataclass(frozen=True)
class ManualScoreEvent(Event):
    """Score correction. Does NOT touch serve possession or rotation."""
    TYPE: ClassVar[str] = "manual_score"
    team: str
    delta: int


@_register
@dataclass(frozen=True)
class ServeOverrideEvent(Event):
    """Manually hand serve possession to `team` without a point/rotation."""
    TYPE: ClassVar[str] = "serve_override"
    team: str


@_register
@dataclass(frozen=True)
class TimeoutEvent(Event):
    TYPE: ClassVar[str] = "timeout"
    team: str


def event_to_dict(e: Event) -> dict:
    d = {"type": e.TYPE}
    for f in fields(e):
        v = getattr(e, f.name)
        if isinstance(v, Rating):
            v = v.value
        elif isinstance(v, tuple):
            v = list(v)
        d[f.name] = v
    return d


def event_from_dict(d: dict) -> Event:
    d = dict(d)
    cls = _REGISTRY[d.pop("type")]
    kwargs = {}
    for f in fields(cls):
        if f.name not in d:
            continue
        v = d[f.name]
        if f.name == "rating" and v is not None:
            v = Rating(v)
        elif f.name == "trajectory" and v is not None:
            v = tuple(v)
        kwargs[f.name] = v
    return cls(**kwargs)
