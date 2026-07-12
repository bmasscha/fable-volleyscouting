"""Formation charts: FIVB overlap legality, role->zone placement,
setter identification, fallbacks and mirroring."""
import math

import pytest

from core.formations import Mode, acting_setter_slot, formation_xy
from core.models import Role
from core.rotation import LEFT, RIGHT, position_xy, serve_xy

S, OH, MB, OPP, L, U = (Role.SETTER, Role.OUTSIDE, Role.MIDDLE,
                        Role.OPPOSITE, Role.LIBERO, Role.UNIVERSAL)

ALL_SLOTS = range(6)
ALL_SIDES = (LEFT, RIGHT)


def closer_to_net(a, b, side):
    """Is point a closer to the net than point b, for a team on side?"""
    return a[0] > b[0] if side == LEFT else a[0] < b[0]


def right_of(a, b, side):
    """Is a to b's right from the team's own perspective? A left-side
    team faces east (right hand = large y); a right-side team faces
    west (right hand = small y)."""
    return a[1] > b[1] if side == LEFT else a[1] < b[1]


def assert_overlap_legal(pos, side, exempt=()):
    """FIVB 7.4-7.5 at the instant of serve contact: front-row players
    in front of their back-row counterpart, lateral order within rows.
    Slot indices: 0..5 = P1..P6."""
    pairs_front = [(1, 0), (2, 5), (3, 4)]           # P2/P1, P3/P6, P4/P5
    lateral = [(1, 2), (2, 3), (0, 5), (5, 4)]       # P2>P3>P4, P1>P6>P5
    for front, back in pairs_front:
        if front in exempt or back in exempt:
            continue
        assert closer_to_net(pos[front], pos[back], side), \
            f"P{front + 1} must be in front of P{back + 1} ({side})"
    for right, left in lateral:
        if right in exempt or left in exempt:
            continue
        assert right_of(pos[right], pos[left], side), \
            f"P{right + 1} must be right of P{left + 1} ({side})"


class TestOverlapLegality:
    """The gate tests: every chart shown while a serve is pending must
    be a legal position under the overlap rules."""

    @pytest.mark.parametrize("setter_slot", ALL_SLOTS)
    @pytest.mark.parametrize("side", ALL_SIDES)
    def test_receive_charts_legal(self, setter_slot, side):
        pos = formation_xy(setter_slot, Mode.RECEIVE, side)
        assert_overlap_legal(pos, side)

    @pytest.mark.parametrize("setter_slot", ALL_SLOTS)
    @pytest.mark.parametrize("side", ALL_SIDES)
    def test_serve_base_legal_server_exempt(self, setter_slot, side):
        pos = formation_xy(setter_slot, Mode.SERVE_BASE, side)
        assert_overlap_legal(pos, side, exempt=(0,))
        assert pos[0] == serve_xy(side)

    def test_grid_itself_is_legal(self):
        for side in ALL_SIDES:
            pos = {i: position_xy(i, side) for i in ALL_SLOTS}
            assert_overlap_legal(pos, side)


# A textbook 5-1 lineup with the setter starting at P1:
# P1=S, P2=OH, P3=MB, P4=OPP, P5=OH, P6=MB (libero swaps in at P6).
FIVE_ONE = {0: S, 1: OH, 2: MB, 3: OPP, 4: OH, 5: L}


def zone_of(pos, side):
    """Rough court zone (1-6) of a point, from the team's perspective."""
    x, y = pos
    if side == RIGHT:
        x, y = -x, 9 - y
    front = x > -4.5
    if y > 6:
        return 2 if front else 1
    if y < 3:
        return 4 if front else 5
    return 3 if front else 6


class TestRoleZones:
    """After the serve: OH -> 4/6, MB -> 3, libero -> 5, S/OPP -> 2/1."""

    @pytest.mark.parametrize("side", ALL_SIDES)
    def test_offense_zones_setter_p1(self, side):
        pos = formation_xy(0, Mode.OFFENSE, side)
        assert zone_of(pos[1], side) == 4     # front OH approaches zone 4
        assert zone_of(pos[2], side) == 3     # front MB quick, zone 3
        assert zone_of(pos[3], side) == 2     # front OPP, zone 2
        assert zone_of(pos[4], side) == 6     # back OH, pipe from 6
        assert zone_of(pos[5], side) == 5     # libero slot, zone 5
        # back-row setter penetrates to the net, right of centre
        assert closer_to_net(pos[0], pos[2], side)
        assert right_of(pos[0], pos[2], side)

    def test_offense_zones_setter_front(self):
        # setter at P3 (front): sets at the net; the back-row OPP (P6)
        # covers zone 1
        pos = formation_xy(2, Mode.OFFENSE, LEFT)
        assert pos[2][0] > -2.0               # setter at the net
        assert zone_of(pos[5], LEFT) == 1     # back OPP -> zone 1
        assert zone_of(pos[3], LEFT) == 4     # front OH -> zone 4
        assert zone_of(pos[1], LEFT) == 3     # front MB -> zone 3

    @pytest.mark.parametrize("setter_slot", ALL_SLOTS)
    def test_defense_block_and_perimeter(self, setter_slot):
        pos = formation_xy(setter_slot, Mode.DEFENSE, LEFT)
        front = [i for i in ALL_SLOTS if i in (1, 2, 3)]
        for i in front:                       # block at the net
            assert pos[i][0] > -2.0
        back = [i for i in ALL_SLOTS if i not in (1, 2, 3)]
        for i in back:                        # perimeter defence
            assert pos[i][0] < -5.5


class TestSetterIdentification:
    def test_single_setter(self):
        assert acting_setter_slot(FIVE_ONE) == 0

    def test_six_two_back_row_setter_acts(self):
        # setters at P2 (front) and P5 (back): the back one runs it
        roles = {0: OH, 1: S, 2: MB, 3: OH, 4: S, 5: L}
        assert acting_setter_slot(roles) == 4

    def test_two_back_row_setters_ambiguous(self):
        roles = {0: S, 1: OH, 2: MB, 3: OH, 4: S, 5: L}
        assert acting_setter_slot(roles) is None

    def test_no_setter(self):
        assert acting_setter_slot({i: U for i in ALL_SLOTS}) is None


class TestFallbacks:
    @pytest.mark.parametrize("mode", list(Mode))
    @pytest.mark.parametrize("side", ALL_SIDES)
    def test_no_setter_falls_back_to_grid(self, mode, side):
        pos = formation_xy(None, mode, side)
        assert pos == {i: position_xy(i, side) for i in ALL_SLOTS}

    def test_grid_mode_ignores_setter(self):
        pos = formation_xy(2, Mode.GRID, LEFT)
        assert pos == {i: position_xy(i, LEFT) for i in ALL_SLOTS}


class TestGeometry:
    @pytest.mark.parametrize("setter_slot", ALL_SLOTS)
    @pytest.mark.parametrize(
        "mode", [Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE])
    def test_mirroring(self, setter_slot, mode):
        left = formation_xy(setter_slot, mode, LEFT)
        right = formation_xy(setter_slot, mode, RIGHT)
        for i in ALL_SLOTS:
            x, y = left[i]
            assert right[i] == pytest.approx((-x, 9 - y))

    @pytest.mark.parametrize("setter_slot", ALL_SLOTS)
    @pytest.mark.parametrize(
        "mode", [Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE])
    def test_bounds_and_spacing(self, setter_slot, mode):
        pos = formation_xy(setter_slot, mode, LEFT)
        for i, (x, y) in pos.items():
            assert -13.0 <= x <= -0.5, f"slot {i} off the playable area"
            assert -2.5 <= y <= 11.5, f"slot {i} off the playable area"
        pts = list(pos.values())
        for i in range(6):
            for j in range(i + 1, 6):
                d = math.dist(pts[i], pts[j])
                assert d >= 1.2, \
                    f"slots too close to stay tappable: {d:.2f} m"
