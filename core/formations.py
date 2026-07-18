"""Realistic (game-like) court positions per rally situation.

The rotation order P1..P6 only fixes the service order and the overlap
rules at the instant of serve contact (FIVB 7.4-7.5): each front-row
player must be closer to the net than their back-row counterpart
(P2/P1, P3/P6, P4/P5) and the lateral order within each row must hold
(P2 right of P3 right of P4; P1 right of P6 right of P5). The moment
the serve is contacted all constraints vanish and players switch to
role-based positions. This module places tokens the way a real 5-1
team stands.

Everything is keyed by the *acting setter's* lineup slot: in a 5-1 the
personnel at each rotational offset from the setter is fixed by the
diagonals (offset 0 = setter, 3 = opposite, 1/4 = outside hitters,
2/5 = middles, with the libero standing in the back-row middle slot).
That makes the charts independent of how carefully roles were entered:
only the setter needs to be identifiable. No setter -> rotational grid.

Coordinates are authored for the LEFT half (net x=0, own end line
x=-9, own right hand at y=9) and mirrored for the right half.
"""
from __future__ import annotations

from enum import Enum

from core.models import Role
from core.rotation import BACK_ROW, position_xy, serve_xy, to_side


class Mode(Enum):
    RECEIVE = "receive"        # opponent about to serve / serving
    SERVE_BASE = "serve_base"  # own team serving, pre-contact
    OFFENSE = "offense"        # own team building the attack
    DEFENSE = "defense"        # opponent attacking, block + perimeter
    GRID = "grid"              # rotational grid (fallback / off)


def acting_setter_slot(roles: dict[int, Role]) -> int | None:
    """Lineup slot (0..5) of the acting setter, or None if no setter is
    identifiable. With two setters on court (a 6-2) the back-row one
    runs the offence; two back-row setters are ambiguous -> None."""
    setters = [i for i, r in roles.items() if r == Role.SETTER]
    if len(setters) == 1:
        return setters[0]
    if len(setters) == 2:
        back = [i for i in setters if i in BACK_ROW]
        if len(back) == 1:
            return back[0]
    return None


def formation_note(roles: dict[int, Role]) -> str | None:
    """Why the realistic charts are unavailable, for the UIs to show, or
    None while they are in use.

    Only a real misconfiguration is reported: two or more setters on
    court without exactly one of them in the back row. A 6-2 keeps its
    setters diagonal (3 apart), so exactly one is always back row and
    the acting one is decidable; setters sharing a row make it
    ambiguous. No setter at all is a supported fallback (roles simply
    were not entered), not a mistake -- it is never flagged."""
    if acting_setter_slot(roles) is not None:
        return None
    if len([i for i, r in roles.items() if r == Role.SETTER]) >= 2:
        return ("setters in the same row - a 6-2 needs them diagonal "
                "(3 apart); showing the rotational grid")
    return None


# --- serve receive, keyed by the setter's slot -------------------------
# Six classic 5-1 reception charts: three passers (both outside hitters
# + the libero in the back-row middle slot) in a passing line ~6.5 m off
# the net, front middle at the net for the quick, opposite out of the
# passing lanes, setter hiding as close to the setting target (net,
# right of centre) as the overlap rules allow. Every chart satisfies
# every overlap constraint (pinned by tests/test_formations.py).
# Values: slot index 0..5 (= P1..P6) -> (x, y) on the LEFT half.
_RECEIVE = {
    0: {0: (-6.8, 8.2),   # S    hides in the right-back corner...
        1: (-5.2, 7.0),   # OH   ...behind the P2 passer, pulled short
        2: (-1.2, 4.5),   # MB   net, quick
        3: (-1.6, 1.6),   # OPP  net left, switches right after contact
        4: (-6.5, 1.8),   # OH   passer, left lane
        5: (-6.5, 4.5)},  # L    passer, middle lane
    1: {0: (-6.5, 7.2),   # L    passer, right lane
        1: (-1.0, 7.0),   # S    front right: already at the net
        2: (-5.6, 2.0),   # OH   passer, middle lane
        3: (-1.4, 1.0),   # MB   net, slides to the middle
        4: (-8.0, 1.0),   # OPP  tucked short left, out of the lanes
        5: (-6.7, 4.5)},  # OH   passer, left lane
    2: {0: (-5.4, 7.4),   # OH   passer, right lane
        1: (-1.4, 7.4),   # MB   net right, switches to the middle
        2: (-0.9, 5.6),   # S    front middle: at the net, slides right
        3: (-5.2, 1.8),   # OH   passer, left lane
        4: (-6.6, 4.5),   # L    passer, middle lane
        5: (-7.5, 6.6)},  # OPP  short mid-right, out of the lanes
    3: {0: (-7.4, 8.3),   # OPP  short in the zone-1 corner
        1: (-5.4, 1.5),   # OH   passer, right lane
        2: (-2.5, 1.0),   # MB   net right, switches to the middle
        3: (-1.0, 0.5),   # S    front left: stacked right at the net
        4: (-6.5, 4.5),   # OH   passer, left lane
        5: (-5.5, 7.5)},  # L    passer, middle lane
    4: {0: (-6.5, 7.6),   # L    passer, right lane
        1: (-1.4, 7.2),   # OPP  net right
        2: (-5.6, 2.0),   # OH   passer, middle lane
        3: (-1.4, 1.8),   # MB   net, slides to the middle
        4: (-3.0, 3.0),   # S    stacked short left, releases at contact
        5: (-6.9, 4.5)},  # OH   passer, left lane
    5: {0: (-5.5, 7.4),   # OH   passer, right lane
        1: (-2.0, 7.2),   # MB   net right, switches to the middle
        2: (-0.9, 5.5),   # OPP  net, switches right after contact
        3: (-5.0, 1.6),   # OH   passer, left lane
        4: (-6.5, 4.5),   # L    passer, middle-left lane
        5: (-2.5, 5.4)},  # S    pushed up mid-right, releases at contact
}

# --- role-based spots (by offset from the setter + front/back row) -----
# After the serve is contacted: OH -> 4 (front) / 6 (back, pipe),
# MB -> 3 (front) / 5 (back = libero), S/OPP -> 2 (front) / 1 (back);
# a back-row setter penetrates to the setting target at the net.
#   offset category: 0 = S, 3 = OPP, 1/4 = OH, 2/5 = MB.
_OFFENSE = {
    ("S", True): (-0.9, 5.8),    # setting target, right of centre
    ("S", False): (-1.6, 6.2),   # penetrated from the back row
    ("OPP", True): (-3.4, 7.4),  # zone 2 approach
    ("OPP", False): (-6.8, 7.4), # zone 1, D-ball / defence
    ("OH", True): (-3.4, 1.6),   # zone 4 approach
    ("OH", False): (-6.8, 4.5),  # zone 6, pipe / defence
    ("MB", True): (-2.6, 4.4),   # zone 3, quick approach
    ("MB", False): (-6.8, 1.6),  # zone 5 (the libero)
}
_DEFENSE = {
    ("S", True): (-1.4, 7.4),    # block, zone 2
    ("S", False): (-6.0, 7.5),   # perimeter, zone 1
    ("OPP", True): (-1.4, 7.4),
    ("OPP", False): (-6.0, 7.5),
    ("OH", True): (-1.4, 1.6),   # block, zone 4
    ("OH", False): (-7.8, 4.5),  # deep zone 6
    ("MB", True): (-1.2, 4.5),   # block, middle
    ("MB", False): (-6.0, 1.8),  # zone 5 (the libero)
}
_OFFSET_CATEGORY = {0: "S", 1: "OH", 2: "MB", 3: "OPP", 4: "OH", 5: "MB"}

# --- serving team, pre-contact (overlap applies; server exempt) --------
# Rotational order, front row tight to the net ready to block, back row
# spread; the switch to role-based defence happens after contact.
_SERVE_BASE = {
    0: None,          # server: serve_xy(side)
    1: (-1.6, 7.4),
    2: (-1.6, 4.5),
    3: (-1.6, 1.6),
    4: (-6.5, 1.8),
    5: (-6.5, 4.6),
}

def overlap_violations(pos: dict[int, tuple[float, float]], side: str,
                       exempt: tuple[int, ...] = ()) -> list[str]:
    """FIVB 7.4-7.5 legality of a serve-contact position, as a list of
    human-readable violation strings (empty list = legal).

    This is the non-asserting twin of tests/test_formations.py's
    ``assert_overlap_legal`` and MUST agree with it exactly, so any
    chart the tests accept this reports as legal. Each front/back pair
    (P2/P1, P3/P6, P4/P5) needs the front player strictly closer to the
    net; each lateral pair (P2>P3>P4, P1>P6>P5) needs the first strictly
    to the team's own right. "Closer" and "right" both depend on the
    half: a left-side team faces east (net = larger x, right = larger
    y), a right-side team faces west (both reversed). A pair with either
    slot in `exempt` is skipped -- used for the server (slot 0), who is
    off court behind the end line and outside the overlap at contact."""
    def closer_to_net(a, b):
        return a[0] > b[0] if side == "left" else a[0] < b[0]

    def right_of(a, b):
        return a[1] > b[1] if side == "left" else a[1] < b[1]

    out: list[str] = []
    for front, back in [(1, 0), (2, 5), (3, 4)]:      # P2/P1, P3/P6, P4/P5
        if front in exempt or back in exempt:
            continue
        if not closer_to_net(pos[front], pos[back]):
            out.append(f"P{front + 1} must be in front of P{back + 1}")
    for right, left in [(1, 2), (2, 3), (0, 5), (5, 4)]:  # P2>P3>P4, P1>P6>P5
        if right in exempt or left in exempt:
            continue
        if not right_of(pos[right], pos[left]):
            out.append(f"P{right + 1} must be right of P{left + 1}")
    return out


def formation_xy(setter_slot: int | None, mode: Mode,
                 side: str) -> dict[int, tuple[float, float]]:
    """Court coordinates (metres) for lineup slots 0..5 (= P1..P6) of a
    team playing on `side`, standing like a real 5-1 team in the given
    situation. Falls back to the rotational grid without a setter."""
    if mode is Mode.GRID or setter_slot is None:
        return {i: position_xy(i, side) for i in range(6)}
    if mode is Mode.RECEIVE:
        chart = _RECEIVE[setter_slot]
        return {i: to_side(*chart[i], side) for i in range(6)}
    if mode is Mode.SERVE_BASE:
        out = {0: serve_xy(side)}
        for i in range(1, 6):
            out[i] = to_side(*_SERVE_BASE[i], side)
        return out
    # OFFENSE / DEFENSE: diagonal pairs (offsets 3 apart) always land on
    # slots 3 apart, i.e. one front row + one back row -- so each pair
    # takes its front and back spot and positions can never collide.
    spots = _OFFENSE if mode is Mode.OFFENSE else _DEFENSE
    xy = {}
    for i in range(6):
        cat = _OFFSET_CATEGORY[(i - setter_slot) % 6]
        xy[i] = spots[(cat, i not in BACK_ROW)]
    return {i: to_side(*xy[i], side) for i in range(6)}
