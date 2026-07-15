"""Per-player serve / attack trajectory charts.

Trajectories are stored on ServeEvent / AttackEvent exactly as drawn, in
absolute court coordinates -- but teams switch sides between sets (and at
8 points in the deciding set), so raw lines from different sets point in
opposite directions. This module replays the event log through the engine
to know which side the acting team occupied at each touch and mirrors
everything to one canonical orientation: the acting team always plays
LEFT -> RIGHT. That makes all of a player's serves (or attacks) directly
comparable on a single chart.
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import MatchEngine
from .events import AttackEvent, Event, ServeEvent, Trajectory
from .models import MatchConfig, Rating, Skill, Team
from .rotation import RIGHT, to_side


@dataclass(frozen=True)
class TrajectoryStat:
    team: str
    player_id: str
    skill: Skill                 # SERVE or ATTACK
    rating: Rating
    set_number: int
    line: Trajectory             # normalized: acting team plays LEFT -> RIGHT
    # block deflection vertex (attacks only), normalized like `line`
    block_touch: tuple[float, float] | None = None


def outcome(rating: Rating) -> str:
    """Display class of a trajectory: 'error' (fault -> red),
    'point' (ace / kill -> green) or 'neutral' (in play -> white)."""
    if rating == Rating.ERROR:
        return "error"
    if rating == Rating.PERFECT:
        return "point"
    return "neutral"


def _normalize(line: Trajectory, side: str) -> Trajectory:
    """Mirror a line drawn while the acting team was on `side` so the
    team always plays LEFT -> RIGHT (to_side is its own inverse)."""
    x1, y1 = to_side(line[0], line[1], side)
    x2, y2 = to_side(line[2], line[3], side)
    return (x1, y1, x2, y2)


def collect_trajectories(config: MatchConfig, teams: dict[str, Team],
                         events: list[Event]) -> list[TrajectoryStat]:
    """Replay `events` and return every recorded serve / attack trajectory
    in canonical orientation, in match order."""
    engine = MatchEngine(config, teams)
    out: list[TrajectoryStat] = []
    for e in events:
        if isinstance(e, (ServeEvent, AttackEvent)) and e.trajectory:
            # side must be read BEFORE applying the event: an ace or fault
            # in the deciding set can trigger the mid-set side switch
            side = engine.side_of(e.team)
            skill = Skill.SERVE if isinstance(e, ServeEvent) else Skill.ATTACK
            touch = e.block_touch if isinstance(e, AttackEvent) else None
            out.append(TrajectoryStat(
                team=e.team, player_id=e.player_id, skill=skill,
                rating=e.rating, set_number=engine.state.set_number,
                line=_normalize(e.trajectory, side),
                block_touch=(to_side(touch[0], touch[1], side)
                             if touch is not None else None)))
        engine.append(e)
    return out
