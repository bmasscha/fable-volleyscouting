"""Flatten the event log into a queryable list of player *actions* and filter
it. This is the selection engine behind the video-review tool: "all attacks by
#12 Away", "all serve-receive by the Home libero", "all failed serves by #7".

Pure Python, no Qt, no engine dependency (set/rally context is derived in a
single pass). Mirrored to tablet/src/core/query.ts (see tablet/TRANSLATION.md).
"""
from __future__ import annotations

from dataclasses import dataclass

from .events import Event, ServeEvent, SetStartEvent
from .models import Rating, Role, Skill, Team
from .stats import _EVENT_SKILL  # {EventClass: Skill}, the single source of truth

# A skill event carries a player_id; these are the four that become actions.
SKILL_EVENT_TYPES = tuple(_EVENT_SKILL.keys())


@dataclass(frozen=True)
class Action:
    """One player touch, enriched with the context the review UI needs. `ts` is
    the wall-clock unix timestamp the scouting UI stamped (used for video sync);
    it may be None for very old logs that predate timestamping."""
    index: int                       # position in the source event list
    ts: float | None
    set_number: int
    rally_index: int                 # 1-based within the set; 0 before first serve
    team_key: str
    player_id: str
    player_number: int | None        # None if the player is not on the roster
    player_name: str
    role: Role | None
    skill: Skill
    rating: Rating
    overpass: bool = False
    block_touch: tuple | None = None
    trajectory: tuple | None = None


def build_actions(events: list[Event], teams: dict[str, Team]) -> list[Action]:
    """Walk the event log once, emitting an Action per skill event (serve,
    reception, attack, dig) with its set/rally/player context resolved.

    set_number tracks the current SetStartEvent; rally_index increments on each
    serve (so the serve and every touch it triggers share a rally). Non-skill
    events (rally points, subs, timeouts, ...) are context only, not actions.
    """
    actions: list[Action] = []
    set_number = 0
    rally_index = 0
    for i, e in enumerate(events):
        if isinstance(e, SetStartEvent):
            set_number = e.set_number
            rally_index = 0
            continue
        if isinstance(e, ServeEvent):
            rally_index += 1
        skill = _EVENT_SKILL.get(type(e))
        if skill is None:
            continue
        team = teams.get(e.team)
        player = team.player(e.player_id) if team is not None else None
        actions.append(Action(
            index=i,
            ts=e.ts,
            set_number=set_number,
            rally_index=rally_index,
            team_key=e.team,
            player_id=e.player_id,
            player_number=player.number if player is not None else None,
            player_name=player.name if player is not None else "",
            role=player.role if player is not None else None,
            skill=skill,
            rating=e.rating,
            overpass=getattr(e, "overpass", False),
            block_touch=getattr(e, "block_touch", None),
            trajectory=getattr(e, "trajectory", None),
        ))
    return actions


@dataclass(frozen=True)
class ActionFilter:
    """A selection over the action list. Every field is optional; a None field
    does not constrain. All set fields must match (logical AND)."""
    team_key: str | None = None          # HOME / AWAY, or None = either team
    player_id: str | None = None
    player_number: int | None = None
    role: Role | None = None             # e.g. Role.LIBERO -> "the libero"
    skill: Skill | None = None
    rating: Rating | None = None         # None = any rating
    set_number: int | None = None

    def matches(self, a: Action) -> bool:
        if self.team_key is not None and a.team_key != self.team_key:
            return False
        if self.player_id is not None and a.player_id != self.player_id:
            return False
        if self.player_number is not None and a.player_number != self.player_number:
            return False
        if self.role is not None and a.role != self.role:
            return False
        if self.skill is not None and a.skill != self.skill:
            return False
        if self.rating is not None and a.rating != self.rating:
            return False
        if self.set_number is not None and a.set_number != self.set_number:
            return False
        return True


def filter_actions(actions: list[Action], spec: ActionFilter) -> list[Action]:
    """Return the actions matching `spec`, ordered by timestamp (ties and any
    timestamp-less actions keep their original event order)."""
    matched = [a for a in actions if spec.matches(a)]
    matched.sort(key=lambda a: (a.ts is None, a.ts if a.ts is not None else 0.0, a.index))
    return matched
