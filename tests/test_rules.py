"""Unit tests for core.rules: set/match win conditions, substitution
legality and libero legality (pure functions, warnings-not-exceptions)."""
import pytest

from core import rules
from core.models import MatchConfig


@pytest.fixture
def config():
    return MatchConfig()  # FIVB defaults: best of 5, 25/15, lead 2, 6 subs


# ---------------------------------------------------------- deciding set

class TestIsDecidingSet:
    @pytest.mark.parametrize("set_number,expected", [
        (1, False), (2, False), (3, False), (4, False), (5, True), (6, False),
    ])
    def test_best_of_five(self, config, set_number, expected):
        assert rules.is_deciding_set(config, set_number) is expected

    @pytest.mark.parametrize("set_number,expected", [
        (1, False), (2, False), (3, True),
    ])
    def test_best_of_three(self, set_number, expected):
        cfg = MatchConfig(sets_to_win=2)
        assert rules.is_deciding_set(cfg, set_number) is expected

    def test_single_set_match(self):
        cfg = MatchConfig(sets_to_win=1)
        assert rules.is_deciding_set(cfg, 1) is True


class TestSetTarget:
    @pytest.mark.parametrize("set_number", [1, 2, 3, 4])
    def test_regular_sets_go_to_25(self, config, set_number):
        assert rules.set_target(config, set_number) == 25

    def test_deciding_set_goes_to_15(self, config):
        assert rules.set_target(config, 5) == 15

    def test_configurable_targets(self):
        cfg = MatchConfig(sets_to_win=2, points_per_set=21, points_deciding_set=11)
        assert rules.set_target(cfg, 1) == 21
        assert rules.set_target(cfg, 3) == 11


# ------------------------------------------------------------ set winner

class TestSetWinner:
    @pytest.mark.parametrize("set_number,a,b,expected", [
        # regular set to 25, 2-point lead
        (1, 0, 0, None),
        (1, 24, 0, None),          # one short of target
        (1, 25, 0, 0),
        (1, 0, 25, 1),
        (1, 25, 23, 0),
        (1, 23, 25, 1),
        (1, 25, 24, None),         # lead only 1 -> continues
        (1, 24, 25, None),
        (1, 24, 24, None),
        (1, 25, 25, None),
        (1, 26, 24, 0),            # no cap: 26-24 valid
        (1, 24, 26, 1),
        (1, 31, 29, 0),            # no cap: 31-29 valid
        (1, 29, 31, 1),
        (1, 30, 29, None),         # deuce marathon continues
        # deciding (5th) set to 15
        (5, 15, 13, 0),
        (5, 13, 15, 1),
        (5, 15, 14, None),
        (5, 14, 14, None),
        (5, 16, 14, 0),
        (5, 14, 16, 1),
        (5, 20, 18, 0),            # no cap in the deciding set either
        (5, 15, 0, 0),
    ])
    def test_set_winner(self, config, set_number, a, b, expected):
        assert rules.set_winner(config, set_number, a, b) == expected

    def test_custom_min_lead(self):
        cfg = MatchConfig(min_lead=1)
        assert rules.set_winner(cfg, 1, 25, 24) == 0


class TestMatchWinner:
    @pytest.mark.parametrize("a,b,expected", [
        (0, 0, None), (1, 0, None), (2, 2, None), (2, 1, None),
        (3, 0, 0), (3, 1, 0), (3, 2, 0),
        (0, 3, 1), (1, 3, 1), (2, 3, 1),
    ])
    def test_best_of_five(self, config, a, b, expected):
        assert rules.match_winner(config, a, b) == expected

    def test_best_of_three(self):
        cfg = MatchConfig(sets_to_win=2)
        assert rules.match_winner(cfg, 2, 0) == 0
        assert rules.match_winner(cfg, 1, 1) is None
        assert rules.match_winner(cfg, 0, 2) == 1


# ---------------------------------------------------------- substitutions

LINEUP = ["p1", "p2", "p3", "p4", "p5", "p6"]
LIBEROS = ["lib"]


class TestValidateSubstitution:
    def test_clean_substitution_has_no_warnings(self, config):
        w = rules.validate_substitution(LINEUP, LIBEROS, 0, [],
                                        "p1", "s1", config)
        assert w == []

    def test_sixth_substitution_still_legal(self, config):
        pairs = [(f"p{i}", f"s{i}") for i in range(1, 6)]
        w = rules.validate_substitution(LINEUP, LIBEROS, 5, pairs,
                                        "p6", "s6", config)
        assert w == []

    def test_seventh_substitution_warns_limit(self, config):
        pairs = [(f"p{i}", f"s{i}") for i in range(1, 7)]
        w = rules.validate_substitution(LINEUP, LIBEROS, 6, pairs,
                                        "p1", "s7", config)
        assert any("limit" in x for x in w)

    def test_configurable_sub_limit(self):
        cfg = MatchConfig(subs_per_set=2)
        w = rules.validate_substitution(LINEUP, LIBEROS, 2, [], "p1", "s1", cfg)
        assert any("limit (2)" in x for x in w)

    def test_player_out_not_on_court_warns(self, config):
        w = rules.validate_substitution(LINEUP, LIBEROS, 0, [],
                                        "ghost", "s1", config)
        assert any("not on court" in x for x in w)

    def test_player_in_already_on_court_warns(self, config):
        w = rules.validate_substitution(LINEUP, LIBEROS, 0, [],
                                        "p1", "p2", config)
        assert any("already on court" in x for x in w)

    def test_libero_cannot_enter_via_substitution(self, config):
        w = rules.validate_substitution(LINEUP, LIBEROS, 0, [],
                                        "p1", "lib", config)
        assert any("libero" in x for x in w)

    def test_reentry_for_original_partner_is_legal(self, config):
        # p1 left for s1; p1 may come back exactly for s1.
        lineup = ["s1", "p2", "p3", "p4", "p5", "p6"]
        w = rules.validate_substitution(lineup, LIBEROS, 1, [("p1", "s1")],
                                        "s1", "p1", config)
        assert w == []

    def test_exhausted_pair_warns_on_third_exchange(self, config):
        # p1 -> s1, s1 -> p1 closed the pair; a third exchange warns.
        pairs = [("p1", "s1"), ("s1", "p1")]
        w = rules.validate_substitution(LINEUP, LIBEROS, 2, pairs,
                                        "p1", "s1", config)
        assert any("re-entry" in x for x in w)

    def test_substitute_cannot_enter_for_a_different_player(self, config):
        # s1 already entered for p1 (and left again); now proposed for p2.
        pairs = [("p1", "s1"), ("s1", "p1")]
        w = rules.validate_substitution(LINEUP, LIBEROS, 2, pairs,
                                        "p2", "s1", config)
        assert any("different player" in x for x in w)

    def test_starter_may_only_reenter_for_own_substitute(self, config):
        # p1 was replaced by s1; p1 tries to come back for p2 instead.
        lineup = ["s1", "p2", "p3", "p4", "p5", "p6"]
        w = rules.validate_substitution(lineup, LIBEROS, 1, [("p1", "s1")],
                                        "p2", "p1", config)
        assert any("re-enter" in x for x in w)

    def test_multiple_warnings_accumulate(self, config):
        w = rules.validate_substitution(LINEUP, LIBEROS, 6, [],
                                        "ghost", "p2", config)
        assert len(w) >= 3  # limit + out-not-on-court + in-already-on-court


# ----------------------------------------------------------------- libero

class TestValidateLiberoEntry:
    def test_partner_not_on_court_is_the_only_warning(self, config):
        w = rules.validate_libero_entry(LINEUP, "ghost", False, config)
        assert w == ["replaced player is not on court"]

    @pytest.mark.parametrize("slot", [4, 5])  # P5, P6
    def test_back_row_entry_is_legal(self, config, slot):
        w = rules.validate_libero_entry(LINEUP, LINEUP[slot], False, config)
        assert w == []

    @pytest.mark.parametrize("slot", [1, 2, 3])  # P2, P3, P4
    def test_front_row_entry_warns(self, config, slot):
        w = rules.validate_libero_entry(LINEUP, LINEUP[slot], False, config)
        assert any("back-row" in x for x in w)

    def test_p1_while_team_serving_warns_by_default(self, config):
        w = rules.validate_libero_entry(LINEUP, LINEUP[0], True, config)
        assert any("may not serve" in x for x in w)

    def test_p1_while_team_serving_ok_if_federation_allows(self):
        cfg = MatchConfig(libero_may_serve=True)
        w = rules.validate_libero_entry(LINEUP, LINEUP[0], True, cfg)
        assert w == []

    def test_p1_while_team_receiving_is_legal(self, config):
        w = rules.validate_libero_entry(LINEUP, LINEUP[0], False, config)
        assert w == []

    def test_back_row_entry_while_serving_is_legal_off_p1(self, config):
        w = rules.validate_libero_entry(LINEUP, LINEUP[4], True, config)
        assert w == []


class TestValidateLiberoExit:
    def test_correct_partner_is_legal(self):
        assert rules.validate_libero_exit("p5", "p5") == []

    def test_wrong_partner_warns(self):
        w = rules.validate_libero_exit("p5", "p4")
        assert w == ["libero must be exchanged back with the player they replaced"]
