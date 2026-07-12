"""Unit tests for core.rotation: rotation math, row classification and
position -> court coordinate mapping (left/right mirroring)."""
import pytest

from core.rotation import (ATTACK_LINE, BACK_ROW, COURT_HALF_LENGTH,
                           COURT_WIDTH, FRONT_ROW, LEFT, RIGHT, is_back_row,
                           is_front_row, position_xy, rotate_clockwise,
                           serve_xy)

LINEUP = ["p1", "p2", "p3", "p4", "p5", "p6"]  # index i = position P(i+1)


# --------------------------------------------------------------- rotation

class TestRotateClockwise:
    def test_basic_mapping(self):
        assert rotate_clockwise(LINEUP) == ["p2", "p3", "p4", "p5", "p6", "p1"]

    def test_p2_becomes_new_server(self):
        rotated = rotate_clockwise(LINEUP)
        assert rotated[0] == LINEUP[1]  # old P2 is the new P1 (server)

    def test_old_p1_moves_to_p6(self):
        rotated = rotate_clockwise(LINEUP)
        assert rotated[5] == LINEUP[0]

    def test_every_position_shift(self):
        rotated = rotate_clockwise(LINEUP)
        # P3->P2, P4->P3, P5->P4, P6->P5
        for old_idx in range(1, 6):
            assert rotated[old_idx - 1] == LINEUP[old_idx]

    def test_returns_new_list_and_does_not_mutate_input(self):
        original = list(LINEUP)
        rotated = rotate_clockwise(original)
        assert rotated is not original
        assert original == LINEUP

    def test_six_rotations_are_identity(self):
        lineup = list(LINEUP)
        for _ in range(6):
            lineup = rotate_clockwise(lineup)
        assert lineup == LINEUP

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
    def test_fewer_than_six_rotations_are_not_identity(self, n):
        lineup = list(LINEUP)
        for _ in range(n):
            lineup = rotate_clockwise(lineup)
        assert lineup != LINEUP

    def test_all_six_rotation_states_are_distinct(self):
        seen = set()
        lineup = list(LINEUP)
        for _ in range(6):
            seen.add(tuple(lineup))
            lineup = rotate_clockwise(lineup)
        assert len(seen) == 6

    def test_twelve_rotations_are_identity(self):
        lineup = list(LINEUP)
        for _ in range(12):
            lineup = rotate_clockwise(lineup)
        assert lineup == LINEUP

    def test_works_with_arbitrary_elements(self):
        assert rotate_clockwise([1, 2, 3, 4, 5, 6]) == [2, 3, 4, 5, 6, 1]


# ------------------------------------------------------------------- rows

class TestRows:
    @pytest.mark.parametrize("idx", [1, 2, 3])   # P2, P3, P4
    def test_front_row_indices(self, idx):
        assert is_front_row(idx)
        assert not is_back_row(idx)

    @pytest.mark.parametrize("idx", [0, 4, 5])   # P1, P5, P6
    def test_back_row_indices(self, idx):
        assert is_back_row(idx)
        assert not is_front_row(idx)

    def test_front_and_back_row_partition_all_six_positions(self):
        assert set(FRONT_ROW) | set(BACK_ROW) == {0, 1, 2, 3, 4, 5}
        assert set(FRONT_ROW) & set(BACK_ROW) == set()

    def test_server_position_is_back_row(self):
        assert is_back_row(0)  # P1 = server


# ---------------------------------------------------------- court mapping

# Expected coordinates for a team on the LEFT half (facing east).
LEFT_EXPECTED = {
    0: (-6.5, 7.5),  # P1 back right
    1: (-2.2, 7.5),  # P2 front right
    2: (-2.2, 4.5),  # P3 front middle
    3: (-2.2, 1.5),  # P4 front left
    4: (-6.5, 1.5),  # P5 back left
    5: (-6.5, 4.5),  # P6 back middle
}


class TestPositionXY:
    @pytest.mark.parametrize("idx", range(6))
    def test_left_side_coordinates(self, idx):
        assert position_xy(idx, LEFT) == pytest.approx(LEFT_EXPECTED[idx])

    @pytest.mark.parametrize("idx", range(6))
    def test_right_side_is_180_degree_rotation_of_left(self, idx):
        lx, ly = position_xy(idx, LEFT)
        assert position_xy(idx, RIGHT) == pytest.approx((-lx, COURT_WIDTH - ly))

    def test_left_positions_all_in_left_half(self):
        for idx in range(6):
            x, y = position_xy(idx, LEFT)
            assert -COURT_HALF_LENGTH <= x < 0
            assert 0 <= y <= COURT_WIDTH

    def test_right_positions_all_in_right_half(self):
        for idx in range(6):
            x, y = position_xy(idx, RIGHT)
            assert 0 < x <= COURT_HALF_LENGTH
            assert 0 <= y <= COURT_WIDTH

    def test_front_row_is_closer_to_net_than_back_row(self):
        for side in (LEFT, RIGHT):
            front = [abs(position_xy(i, side)[0]) for i in FRONT_ROW]
            back = [abs(position_xy(i, side)[0]) for i in BACK_ROW]
            assert max(front) < min(back)

    def test_front_row_inside_attack_line(self):
        for side in (LEFT, RIGHT):
            for i in FRONT_ROW:
                assert abs(position_xy(i, side)[0]) <= ATTACK_LINE

    def test_p1_and_p2_share_the_right_hand_column(self):
        # From the team's own perspective, P1 (back) and P2 (front) share y.
        for side in (LEFT, RIGHT):
            assert position_xy(0, side)[1] == position_xy(1, side)[1]

    def test_mirroring_swaps_north_south(self):
        # P4 is the team's front-left: north (small y) on the left half,
        # south (large y) on the right half.
        assert position_xy(3, LEFT)[1] == pytest.approx(1.5)
        assert position_xy(3, RIGHT)[1] == pytest.approx(7.5)


class TestServeXY:
    def test_left_server_stands_behind_left_end_line(self):
        x, y = serve_xy(LEFT)
        assert x == pytest.approx(-(COURT_HALF_LENGTH + 1.2))
        assert y == pytest.approx(7.5)

    def test_right_is_mirror_of_left(self):
        lx, ly = serve_xy(LEFT)
        assert serve_xy(RIGHT) == pytest.approx((-lx, COURT_WIDTH - ly))

    def test_server_is_outside_the_court(self):
        assert serve_xy(LEFT)[0] < -COURT_HALF_LENGTH
        assert serve_xy(RIGHT)[0] > COURT_HALF_LENGTH
