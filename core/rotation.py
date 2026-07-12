"""Rotation math and position -> court coordinate mapping.

Positions are stored as list indices 0..5 meaning P1..P6:
  P1 = right back (server), P2 = right front, P3 = middle front,
  P4 = left front, P5 = left back, P6 = middle back
-- always from the team's own perspective facing the net.

Court coordinate system (metres): net at x = 0, court x in [-9, +9],
sidelines y = 0 (top of screen / "north") and y = 9 (bottom / "south").
A team playing on the LEFT half faces east: its right hand points south,
so its P1/P2 column sits at large y. The right half is the 180-degree
rotation of the left half.
"""
from __future__ import annotations

COURT_HALF_LENGTH = 9.0
COURT_WIDTH = 9.0
ATTACK_LINE = 3.0          # distance from net
FREE_ZONE_X = 4.0          # free zone depth behind the end lines
FREE_ZONE_Y = 2.5          # free zone depth beyond the sidelines

FRONT_ROW = (1, 2, 3)      # indices of P2, P3, P4
BACK_ROW = (0, 5, 4)       # indices of P1, P6, P5

LEFT = "left"
RIGHT = "right"

# Home-base coordinates for a team on the LEFT half (facing east).
_LEFT_XY = {
    0: (-6.5, 7.5),  # P1 back  right (south)
    1: (-2.2, 7.5),  # P2 front right
    2: (-2.2, 4.5),  # P3 front middle
    3: (-2.2, 1.5),  # P4 front left (north)
    4: (-6.5, 1.5),  # P5 back  left
    5: (-6.5, 4.5),  # P6 back  middle
}


def rotate_clockwise(lineup: list) -> list:
    """One rotation on gaining serve: P2 becomes the new P1 (server),
    P3->P2, P4->P3, P5->P4, P6->P5 and the old P1 moves to P6."""
    return list(lineup[1:]) + [lineup[0]]


def position_xy(pos_index: int, side: str) -> tuple[float, float]:
    """Court coordinates (metres) of position P{pos_index+1} for a team
    playing on `side` ('left' or 'right')."""
    x, y = _LEFT_XY[pos_index]
    if side == RIGHT:
        return (-x, COURT_WIDTH - y)
    return (x, y)


def serve_xy(side: str) -> tuple[float, float]:
    """Spot behind the end line where the server stands."""
    x = -(COURT_HALF_LENGTH + 1.2)
    y = 7.5
    if side == RIGHT:
        return (-x, COURT_WIDTH - y)
    return (x, y)


def is_front_row(pos_index: int) -> bool:
    return pos_index in FRONT_ROW


def is_back_row(pos_index: int) -> bool:
    return pos_index in BACK_ROW
