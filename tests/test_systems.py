"""Playing-system registry: chart generation, legality, fallbacks and
MatchConfig persistence."""
import math

import pytest

from core import formations
from core.formations import Mode
from core.models import HOME, AWAY, MatchConfig, Role
from core.rotation import LEFT, RIGHT, position_xy, serve_xy
from core.systems import (DEFAULT_SYSTEM, SYSTEMS, acting_setter_slot_for,
                          chart_key, get_system, system_ids, system_note,
                          system_xy)

S, OH, MB, OPP, L, U = (Role.SETTER, Role.OUTSIDE, Role.MIDDLE,
                        Role.OPPOSITE, Role.LIBERO, Role.UNIVERSAL)

ALL_SLOTS = range(6)
ALL_SIDES = (LEFT, RIGHT)
ALL_MODES = (Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE)

# A textbook 5-1 lineup with the setter starting at P1 (mirrors
# tests/test_formations.py's FIVE_ONE fixture).
FIVE_ONE = {0: S, 1: OH, 2: MB, 3: OPP, 4: OH, 5: L}


def closer_to_net(a, b, side):
    return a[0] > b[0] if side == LEFT else a[0] < b[0]


def right_of(a, b, side):
    return a[1] > b[1] if side == LEFT else a[1] < b[1]


def assert_overlap_legal(pos, side, exempt=()):
    pairs_front = [(1, 0), (2, 5), (3, 4)]
    lateral = [(1, 2), (2, 3), (0, 5), (5, 4)]
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


def roles_with_setter_at(slot):
    """A single-setter lineup with the setter at `slot` -- the only
    thing acting_setter_slot (and hence chart_key) looks at; the other
    five slots' roles are irrelevant to the chart lookup."""
    return {i: (S if i == slot else OH) for i in range(6)}


# --- 1. every registered system, every chart key: legality/geometry ----
def _system_chart_keys(spec):
    if spec.uses_setter_roles:
        return list(ALL_SLOTS)
    return [0]


SYSTEM_KEY_PAIRS = [
    (spec_id, key)
    for spec_id, spec in SYSTEMS.items()
    for key in _system_chart_keys(spec)
]


class TestEveryRegisteredSystem:
    @pytest.mark.parametrize("side", ALL_SIDES)
    @pytest.mark.parametrize("system_id,key", SYSTEM_KEY_PAIRS)
    def test_receive_chart_legal(self, system_id, key, side):
        spec = SYSTEMS[system_id]
        chart = spec.charts[Mode.RECEIVE][key]
        pos = {i: formations.to_side(*chart[i], side) for i in ALL_SLOTS}
        assert_overlap_legal(pos, side)

    @pytest.mark.parametrize("side", ALL_SIDES)
    @pytest.mark.parametrize("system_id,key", SYSTEM_KEY_PAIRS)
    def test_serve_base_legal_server_exempt(self, system_id, key, side):
        spec = SYSTEMS[system_id]
        chart = spec.charts[Mode.SERVE_BASE][key]
        pos = {0: serve_xy(side)}
        for i in range(1, 6):
            pos[i] = formations.to_side(*chart[i], side)
        assert_overlap_legal(pos, side, exempt=(0,))
        assert pos[0] == serve_xy(side)

    @pytest.mark.parametrize("mode", ALL_MODES)
    @pytest.mark.parametrize("system_id,key", SYSTEM_KEY_PAIRS)
    def test_all_six_slots_present(self, system_id, key, mode):
        spec = SYSTEMS[system_id]
        chart = spec.charts[mode][key]
        expected = set(range(6)) if mode is not Mode.SERVE_BASE \
            else set(range(1, 6))
        assert set(chart.keys()) == expected

    @pytest.mark.parametrize(
        "mode", (Mode.RECEIVE, Mode.OFFENSE, Mode.DEFENSE))
    @pytest.mark.parametrize("system_id,key", SYSTEM_KEY_PAIRS)
    def test_pairwise_spacing(self, system_id, key, mode):
        spec = SYSTEMS[system_id]
        chart = spec.charts[mode][key]
        pts = [chart[i] for i in range(6)]
        for i in range(6):
            for j in range(i + 1, 6):
                d = math.dist(pts[i], pts[j])
                assert d >= 1.2, \
                    f"{system_id}/{mode}/{key}: slots too close: {d:.2f}"

    @pytest.mark.parametrize("mode", ALL_MODES)
    @pytest.mark.parametrize("system_id,key", SYSTEM_KEY_PAIRS)
    def test_mirroring_consistency(self, system_id, key, mode):
        spec = SYSTEMS[system_id]
        chart = spec.charts[mode][key]
        slots = range(1, 6) if mode is Mode.SERVE_BASE else range(6)
        for i in slots:
            x, y = chart[i]
            left = formations.to_side(x, y, LEFT)
            right = formations.to_side(x, y, RIGHT)
            assert left == (x, y)
            assert right == pytest.approx((-x, 9 - y))

    @pytest.mark.parametrize("mode", ALL_MODES)
    @pytest.mark.parametrize("system_id,key", SYSTEM_KEY_PAIRS)
    def test_bounds(self, system_id, key, mode):
        spec = SYSTEMS[system_id]
        chart = spec.charts[mode][key]
        for i, (x, y) in chart.items():
            assert -13.0 <= x <= -0.5, \
                f"{system_id}/{mode}/{key} slot {i} off court"
            assert -2.5 <= y <= 11.5, \
                f"{system_id}/{mode}/{key} slot {i} off court"


# --- 2. regression: 5-1 / 6-2 reproduce formations.formation_xy --------
class TestFiveOneRegression:
    @pytest.mark.parametrize("side", ALL_SIDES)
    @pytest.mark.parametrize("setter_slot", ALL_SLOTS)
    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_matches_formation_xy(self, mode, setter_slot, side):
        spec = SYSTEMS["5-1"]
        roles = roles_with_setter_at(setter_slot)
        got = system_xy(spec, roles, mode, side)
        want = formations.formation_xy(setter_slot, mode, side)
        assert got == want

    def test_six_two_shares_charts_with_five_one(self):
        five_one = SYSTEMS["5-1"]
        six_two = SYSTEMS["6-2"]
        assert five_one.charts is six_two.charts


# --- 3. 6-6: keyless system -------------------------------------------
class TestSixSix:
    def test_chart_key_always_zero(self):
        spec = SYSTEMS["6-6"]
        all_universal = {i: U for i in ALL_SLOTS}
        with_setters = {0: S, 1: OH, 2: MB, 3: OPP, 4: OH, 5: L}
        assert chart_key(spec, all_universal) == 0
        assert chart_key(spec, with_setters) == 0
        assert chart_key(spec, {}) == 0

    def test_note_always_none(self):
        spec = SYSTEMS["6-6"]
        all_universal = {i: U for i in ALL_SLOTS}
        two_setters_same_row = {0: S, 1: OH, 2: MB, 3: OH, 4: S, 5: L}
        assert system_note(spec, all_universal) is None
        assert system_note(spec, two_setters_same_row) is None
        assert system_note(spec, {}) is None

    def test_acting_setter_slot_is_p3(self):
        spec = SYSTEMS["6-6"]
        all_universal = {i: U for i in ALL_SLOTS}
        assert acting_setter_slot_for(spec, all_universal) == 2
        assert acting_setter_slot_for(spec, {}) == 2

    def test_all_universal_gets_the_w_chart_not_the_grid(self):
        spec = SYSTEMS["6-6"]
        all_universal = {i: U for i in ALL_SLOTS}
        pos = system_xy(spec, all_universal, Mode.RECEIVE, LEFT)
        grid = {i: position_xy(i, LEFT) for i in ALL_SLOTS}
        assert pos != grid
        want = {i: formations.to_side(*spec.charts[Mode.RECEIVE][0][i],
                                      LEFT) for i in ALL_SLOTS}
        assert pos == want

    def test_grid_mode_still_falls_back(self):
        spec = SYSTEMS["6-6"]
        all_universal = {i: U for i in ALL_SLOTS}
        pos = system_xy(spec, all_universal, Mode.GRID, LEFT)
        assert pos == {i: position_xy(i, LEFT) for i in ALL_SLOTS}


# --- 3b. 6-6-p1: keyless system, P1 sets ---------------------------
class TestSixSixP1:
    def test_chart_key_always_zero(self):
        spec = SYSTEMS["6-6-p1"]
        all_universal = {i: U for i in ALL_SLOTS}
        with_setters = {0: S, 1: OH, 2: MB, 3: OPP, 4: OH, 5: L}
        assert chart_key(spec, all_universal) == 0
        assert chart_key(spec, with_setters) == 0
        assert chart_key(spec, {}) == 0

    def test_note_always_none(self):
        spec = SYSTEMS["6-6-p1"]
        all_universal = {i: U for i in ALL_SLOTS}
        two_setters_same_row = {0: S, 1: OH, 2: MB, 3: OH, 4: S, 5: L}
        assert system_note(spec, all_universal) is None
        assert system_note(spec, two_setters_same_row) is None
        assert system_note(spec, {}) is None

    def test_acting_setter_slot_is_p1(self):
        spec = SYSTEMS["6-6-p1"]
        all_universal = {i: U for i in ALL_SLOTS}
        assert acting_setter_slot_for(spec, all_universal) == 0
        assert acting_setter_slot_for(spec, {}) == 0

    def test_all_universal_gets_the_w_chart_not_the_grid(self):
        spec = SYSTEMS["6-6-p1"]
        all_universal = {i: U for i in ALL_SLOTS}
        pos = system_xy(spec, all_universal, Mode.RECEIVE, LEFT)
        grid = {i: position_xy(i, LEFT) for i in ALL_SLOTS}
        assert pos != grid
        want = {i: formations.to_side(*spec.charts[Mode.RECEIVE][0][i],
                                      LEFT) for i in ALL_SLOTS}
        assert pos == want
        assert spec.charts[Mode.RECEIVE][0][0] == (-6.8, 8.2)

    def test_grid_mode_still_falls_back(self):
        spec = SYSTEMS["6-6-p1"]
        all_universal = {i: U for i in ALL_SLOTS}
        pos = system_xy(spec, all_universal, Mode.GRID, LEFT)
        assert pos == {i: position_xy(i, LEFT) for i in ALL_SLOTS}

    def test_six_six_still_reports_acting_setter_slot_two(self):
        # Regression on the fixed_setter_slot refactor: plain 6-6 keeps
        # its P3-sets behaviour unchanged.
        spec = SYSTEMS["6-6"]
        assert acting_setter_slot_for(spec, {i: U for i in ALL_SLOTS}) == 2


# --- 4. registry lookups -------------------------------------------
class TestRegistry:
    def test_known_ids(self):
        for system_id in ("5-1", "6-2", "6-6", "6-6-p1"):
            assert get_system(system_id).id == system_id

    def test_unknown_id_falls_back_to_default(self):
        assert get_system("7-0").id == DEFAULT_SYSTEM

    def test_none_falls_back_to_default(self):
        assert get_system(None).id == DEFAULT_SYSTEM

    def test_system_ids_order(self):
        assert system_ids() == ["5-1", "6-2", "6-6", "6-6-p1"]


# --- 5. MatchConfig round-trip -------------------------------------
class TestMatchConfigSystems:
    def test_default(self):
        cfg = MatchConfig()
        assert cfg.systems == {HOME: "5-1", AWAY: "5-1"}

    def test_round_trip(self):
        cfg = MatchConfig(systems={HOME: "6-2", AWAY: "6-6"})
        d = cfg.to_dict()
        assert d["systems"] == {HOME: "6-2", AWAY: "6-6"}
        restored = MatchConfig.from_dict(d)
        assert restored.systems == {HOME: "6-2", AWAY: "6-6"}

    def test_from_dict_without_systems_defaults_both(self):
        d = MatchConfig().to_dict()
        del d["systems"]
        restored = MatchConfig.from_dict(d)
        assert restored.systems == {HOME: "5-1", AWAY: "5-1"}

    def test_from_dict_partial_systems_defaults_the_rest(self):
        d = MatchConfig().to_dict()
        d["systems"] = {"home": "6-6"}
        restored = MatchConfig.from_dict(d)
        assert restored.systems == {HOME: "6-6", AWAY: "5-1"}

    def test_from_dict_ignores_unknown_team_keys(self):
        d = MatchConfig().to_dict()
        d["systems"] = {"home": "6-2", "referee": "6-6"}
        restored = MatchConfig.from_dict(d)
        assert restored.systems == {HOME: "6-2", AWAY: "5-1"}
