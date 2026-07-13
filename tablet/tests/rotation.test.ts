import { describe, expect, test } from "vitest";

import {
  ATTACK_LINE,
  BACK_ROW,
  COURT_HALF_LENGTH,
  COURT_WIDTH,
  FRONT_ROW,
  LEFT,
  RIGHT,
  is_back_row,
  is_front_row,
  position_xy,
  rotate_clockwise,
  serve_xy,
} from "../src/core/rotation";

const LINEUP = ["p1", "p2", "p3", "p4", "p5", "p6"]; // index i = position P(i+1)

// --------------------------------------------------------------- rotation

describe("TestRotateClockwise", () => {
  test("test_basic_mapping", () => {
    expect(rotate_clockwise(LINEUP)).toEqual(["p2", "p3", "p4", "p5", "p6", "p1"]);
  });

  test("test_p2_becomes_new_server", () => {
    const rotated = rotate_clockwise(LINEUP);
    expect(rotated[0]).toBe(LINEUP[1]); // old P2 is the new P1 (server)
  });

  test("test_old_p1_moves_to_p6", () => {
    const rotated = rotate_clockwise(LINEUP);
    expect(rotated[5]).toBe(LINEUP[0]);
  });

  test("test_every_position_shift", () => {
    const rotated = rotate_clockwise(LINEUP);
    // P3->P2, P4->P3, P5->P4, P6->P5
    for (let old_idx = 1; old_idx < 6; old_idx += 1) {
      expect(rotated[old_idx - 1]).toBe(LINEUP[old_idx]);
    }
  });

  test("test_returns_new_list_and_does_not_mutate_input", () => {
    const original = [...LINEUP];
    const rotated = rotate_clockwise(original);
    expect(rotated).not.toBe(original);
    expect(original).toEqual(LINEUP);
  });

  test("test_six_rotations_are_identity", () => {
    let lineup = [...LINEUP];
    for (let i = 0; i < 6; i += 1) {
      lineup = rotate_clockwise(lineup);
    }
    expect(lineup).toEqual(LINEUP);
  });

  test.each([1, 2, 3, 4, 5])(
    "test_fewer_than_six_rotations_are_not_identity(%i)",
    (n) => {
      let lineup = [...LINEUP];
      for (let i = 0; i < n; i += 1) {
        lineup = rotate_clockwise(lineup);
      }
      expect(lineup).not.toEqual(LINEUP);
    },
  );

  test("test_all_six_rotation_states_are_distinct", () => {
    const seen = new Set<string>();
    let lineup = [...LINEUP];
    for (let i = 0; i < 6; i += 1) {
      seen.add(JSON.stringify(lineup));
      lineup = rotate_clockwise(lineup);
    }
    expect(seen.size).toBe(6);
  });

  test("test_twelve_rotations_are_identity", () => {
    let lineup = [...LINEUP];
    for (let i = 0; i < 12; i += 1) {
      lineup = rotate_clockwise(lineup);
    }
    expect(lineup).toEqual(LINEUP);
  });

  test("test_works_with_arbitrary_elements", () => {
    expect(rotate_clockwise([1, 2, 3, 4, 5, 6])).toEqual([2, 3, 4, 5, 6, 1]);
  });
});

// ------------------------------------------------------------------- rows

describe("TestRows", () => {
  test.each([1, 2, 3])("test_front_row_indices(%i)", (idx) => {
    expect(is_front_row(idx)).toBe(true);
    expect(is_back_row(idx)).toBe(false);
  });

  test.each([0, 4, 5])("test_back_row_indices(%i)", (idx) => {
    expect(is_back_row(idx)).toBe(true);
    expect(is_front_row(idx)).toBe(false);
  });

  test("test_front_and_back_row_partition_all_six_positions", () => {
    expect(new Set([...FRONT_ROW, ...BACK_ROW])).toEqual(new Set([0, 1, 2, 3, 4, 5]));
    expect(new Set(FRONT_ROW.filter((idx) => BACK_ROW.includes(idx)))).toEqual(new Set());
  });

  test("test_server_position_is_back_row", () => {
    expect(is_back_row(0)).toBe(true); // P1 = server
  });
});

// ---------------------------------------------------------- court mapping

// Expected coordinates for a team on the LEFT half (facing east).
const LEFT_EXPECTED: Record<number, [number, number]> = {
  0: [-6.5, 7.5], // P1 back right
  1: [-2.2, 7.5], // P2 front right
  2: [-2.2, 4.5], // P3 front middle
  3: [-2.2, 1.5], // P4 front left
  4: [-6.5, 1.5], // P5 back left
  5: [-6.5, 4.5], // P6 back middle
};

describe("TestPositionXY", () => {
  test.each([0, 1, 2, 3, 4, 5])("test_left_side_coordinates(%i)", (idx) => {
    expect(position_xy(idx, LEFT)).toEqual(LEFT_EXPECTED[idx]);
  });

  test.each([0, 1, 2, 3, 4, 5])(
    "test_right_side_is_180_degree_rotation_of_left(%i)",
    (idx) => {
      const [lx, ly] = position_xy(idx, LEFT);
      expect(position_xy(idx, RIGHT)).toEqual([-lx, COURT_WIDTH - ly]);
    },
  );

  test("test_left_positions_all_in_left_half", () => {
    for (let idx = 0; idx < 6; idx += 1) {
      const [x, y] = position_xy(idx, LEFT);
      expect(x).toBeGreaterThanOrEqual(-COURT_HALF_LENGTH);
      expect(x).toBeLessThan(0);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(COURT_WIDTH);
    }
  });

  test("test_right_positions_all_in_right_half", () => {
    for (let idx = 0; idx < 6; idx += 1) {
      const [x, y] = position_xy(idx, RIGHT);
      expect(x).toBeGreaterThan(0);
      expect(x).toBeLessThanOrEqual(COURT_HALF_LENGTH);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(COURT_WIDTH);
    }
  });

  test("test_front_row_is_closer_to_net_than_back_row", () => {
    for (const side of [LEFT, RIGHT]) {
      const front = FRONT_ROW.map((i) => Math.abs(position_xy(i, side)[0]));
      const back = BACK_ROW.map((i) => Math.abs(position_xy(i, side)[0]));
      expect(Math.max(...front)).toBeLessThan(Math.min(...back));
    }
  });

  test("test_front_row_inside_attack_line", () => {
    for (const side of [LEFT, RIGHT]) {
      for (const i of FRONT_ROW) {
        expect(Math.abs(position_xy(i, side)[0])).toBeLessThanOrEqual(ATTACK_LINE);
      }
    }
  });

  test("test_p1_and_p2_share_the_right_hand_column", () => {
    // From the team's own perspective, P1 (back) and P2 (front) share y.
    for (const side of [LEFT, RIGHT]) {
      expect(position_xy(0, side)[1]).toBe(position_xy(1, side)[1]);
    }
  });

  test("test_mirroring_swaps_north_south", () => {
    // P4 is the team's front-left: north (small y) on the left half,
    // south (large y) on the right half.
    expect(position_xy(3, LEFT)[1]).toBe(1.5);
    expect(position_xy(3, RIGHT)[1]).toBe(7.5);
  });
});

describe("TestServeXY", () => {
  test("test_left_server_stands_behind_left_end_line", () => {
    const [x, y] = serve_xy(LEFT);
    expect(x).toBe(-(COURT_HALF_LENGTH + 1.2));
    expect(y).toBe(7.5);
  });

  test("test_right_is_mirror_of_left", () => {
    const [lx, ly] = serve_xy(LEFT);
    expect(serve_xy(RIGHT)).toEqual([-lx, COURT_WIDTH - ly]);
  });

  test("test_server_is_outside_the_court", () => {
    expect(serve_xy(LEFT)[0]).toBeLessThan(-COURT_HALF_LENGTH);
    expect(serve_xy(RIGHT)[0]).toBeGreaterThan(COURT_HALF_LENGTH);
  });
});
