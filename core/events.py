"""Immutable match events. The event log is the single source of truth:
current match state is always derived by replaying events (see engine.py),
which makes undo trivially correct (drop last event, replay)."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import ClassVar

from .models import Rating

# (x1, y1, x2, y2) in court metres; net at x=0, sidelines y=0 and y=9.
Trajectory = tuple[float, float, float, float]
# (x, y) court metres of the block contact that deflected an attack.
BlockTouch = tuple[float, float]

_REGISTRY: dict[str, type] = {}


def _register(cls):
    _REGISTRY[cls.TYPE] = cls
    return cls


@dataclass(frozen=True)
class Event:
    TYPE: ClassVar[str] = "event"
    # Wall-clock unix timestamp stamped by the UI when the event is entered.
    # Purely informational (video sync): replay/state never depends on it.
    ts: float | None = field(default=None, kw_only=True)


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
    """`overpass=True`: the received ball crossed straight back over the net;
    the rally continues with the serving team in the attack phase."""
    TYPE: ClassVar[str] = "reception"
    team: str
    player_id: str
    rating: Rating
    overpass: bool = False


@_register
@dataclass(frozen=True)
class AttackEvent(Event):
    """`block_touch` set = the attack was deflected by the block: the drawn
    path is attacker -> block_touch -> trajectory end (the final landing).
    `trajectory` keeps meaning start -> landing either way."""
    TYPE: ClassVar[str] = "attack"
    team: str
    player_id: str
    rating: Rating
    trajectory: Trajectory | None = None
    block_touch: BlockTouch | None = None


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
    partner returns. Not a substitution (unlimited, not counted).
    `auto=True` marks an exchange the app entered on the scouter's behalf
    (forced front-row exit or learned serve-receive re-entry); the UIs
    undo it together with the event that triggered it."""
    TYPE: ClassVar[str] = "libero_swap"
    team: str
    libero_id: str
    partner_id: str
    auto: bool = False


@_register
@dataclass(frozen=True)
class RotationAdjustEvent(Event):
    """Manual rotation correction: rotates `team`'s lineup `steps` positions
    clockwise (negative = counter-clockwise). Does NOT touch score or serve
    possession -- the coach simply starts / stands in another rotation."""
    TYPE: ClassVar[str] = "rotation_adjust"
    team: str
    steps: int = 1


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
        elif f.name in ("trajectory", "block_touch") and v is not None:
            v = tuple(v)
        kwargs[f.name] = v
    return cls(**kwargs)
