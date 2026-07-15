"""Block deflection classification for two-segment attack trajectories.

A blocked attack is drawn in two strokes: attacker -> block touch (at the
net), then block touch -> where the deflected ball ended up. Only the final
landing point decides the outcome. All functions are pure so the engine,
the desktop UI and the tablet port share a single definition.
"""
from __future__ import annotations

from .rotation import COURT_HALF_LENGTH, COURT_WIDTH, LEFT

# Landing this far beyond the lines still counts as in (same tolerance the
# UIs apply to out-served balls).
OUT_TOLERANCE = 0.4
# A pending attack arrow must end within this distance of the net for a
# follow-up drag to count as the block deflection...
BLOCK_NET_ZONE = 1.5
# ...and that follow-up drag must start within this radius of the arrow tip.
BLOCK_GRAB_RADIUS = 1.0

BLOCK_OUT = "block_out"  # deflected out of bounds -> point for the attackers
COVERED = "covered"      # back into the attacker's court, still in play
IN_PLAY = "in_play"      # stays on the blockers' side, still in play


def landing_in_bounds(x: float, y: float,
                      tolerance: float = OUT_TOLERANCE) -> bool:
    return (-COURT_HALF_LENGTH - tolerance <= x <= COURT_HALF_LENGTH + tolerance
            and -tolerance <= y <= COURT_WIDTH + tolerance)


def classify_block_deflection(attacker_side: str, x: float, y: float) -> str:
    """Outcome of a block deflection landing at (x, y) for an attacker
    playing on `attacker_side` (LEFT = the x < 0 half). A landing exactly
    on the net plane (x == 0) counts as the blockers' side."""
    if not landing_in_bounds(x, y):
        return BLOCK_OUT
    on_attacker_half = x < 0 if attacker_side == LEFT else x > 0
    return COVERED if on_attacker_half else IN_PLAY
