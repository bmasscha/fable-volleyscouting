"""Where an attack landed, and what that means.

A blocked attack is drawn in two strokes: attacker -> block touch (at the
net), then block touch -> where the deflected ball ended up. Only the final
landing point decides the outcome. All functions are pure so the engine,
the desktop UI and the tablet port share a single definition.

The same three landing zones also settle an *unblocked* attack, with the
opposite verdict -- see `unblocked_attack_is_error`.
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


def is_block_touch(attacker_side: str, x: float, y: float) -> bool:
    """True when an attack arrow ending at (x, y) can be a block contact:
    it must sit in the BLOCKERS' court -- the ball actually crossed -- and
    within BLOCK_NET_ZONE of the net. A tip on the attacker's own side of
    the net means the attack never made it over, which is an error, not a
    block; that arrow is scored '!' instead of priming a second stroke.
    """
    return (classify_block_deflection(attacker_side, x, y) == IN_PLAY
            and abs(x) <= BLOCK_NET_ZONE)


def unblocked_attack_is_error(attacker_side: str, x: float, y: float) -> bool:
    """True when an attack drawn WITHOUT a block touch is the attacker's own
    fault, because the ball never legally reached the opponents' court: it
    landed beyond the lines (out), or short on the attacker's own half (hit
    into the net). Only IN_PLAY -- in bounds, on the blockers' side -- keeps
    the rally alive and still needs a rating.

    This is the mirror image of the blocked case: for the very same landing
    a block touch makes it '#' (block-out) or '-' (covered), while no block
    touch makes it '!'.
    """
    return classify_block_deflection(attacker_side, x, y) != IN_PLAY
