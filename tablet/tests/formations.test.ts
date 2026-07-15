import { describe, expect, test } from "vitest";

import {
  Mode, acting_setter_slot, formation_note, formation_xy,
} from "../src/core/formations";
import { Role } from "../src/core/models";
import {
  BACK_ROW, LEFT, RIGHT, position_xy, rotate_clockwise, serve_xy,
} from "../src/core/rotation";

const S = Role.SETTER;
const OH = Role.OUTSIDE;
const MB = Role.MIDDLE;
const OPP = Role.OPPOSITE;
const L = Role.LIBERO;
const U = Role.UNIVERSAL;

const ALL_SLOTS = [0, 1, 2, 3, 4, 5];
const ALL_SIDES = [LEFT, RIGHT];
const ALL_MODES: readonly Mode[] = [
  Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE, Mode.GRID,
];

function closer_to_net(a: [number, number], b: [number, number], side: string): boolean {
  /** Is point a closer to the net than point b, for a team on side? */
  return side === LEFT ? a[0] > b[0] : a[0] < b[0];
}

function right_of(a: [number, number], b: [number, number], side: string): boolean {
  /** Is a to b's right from the team's own perspective? A left-side
   * team faces east (right hand = large y); a right-side team faces
   * west (right hand = small y). */
  return side === LEFT ? a[1] > b[1] : a[1] < b[1];
}

function assert_overlap_legal(
  pos: Record<number, [number, number]>, side: string, exempt: number[] = [],
): void {
  /** FIVB 7.4-7.5 at the instant of serve contact: front-row players
   * in front of their back-row counterpart, lateral order within rows.
   * Slot indices: 0..5 = P1..P6. */
  const pairs_front: [number, number][] = [[1, 0], [2, 5], [3, 4]]; // P2/P1, P3/P6, P4/P5
  const lateral: [number, number][] = [[1, 2], [2, 3], [0, 5], [5, 4]]; // P2>P3>P4, P1>P6>P5
  for (const [front, back] of pairs_front) {
    if (exempt.includes(front) || exempt.includes(back)) {
      continue;
    }
    if (!closer_to_net(pos[front], pos[back], side)) {
      throw new Error(`P${front + 1} must be in front of P${back + 1} (${side})`);
    }
  }
  for (const [right, left] of lateral) {
    if (exempt.includes(right) || exempt.includes(left)) {
      continue;
    }
    if (!right_of(pos[right], pos[left], side)) {
      throw new Error(`P${right + 1} must be right of P${left + 1} (${side})`);
    }
  }
}

// A textbook 5-1 lineup with the setter starting at P1:
// P1=S, P2=OH, P3=MB, P4=OPP, P5=OH, P6=MB (libero swaps in at P6).
const FIVE_ONE: Record<number, Role> = { 0: S, 1: OH, 2: MB, 3: OPP, 4: OH, 5: L };

function zone_of(pos: [number, number], side: string): number {
  /** Rough court zone (1-6) of a point, from the team's perspective. */
  let [x, y] = pos;
  if (side === RIGHT) {
    x = -x;
    y = 9 - y;
  }
  const front = x > -4.5;
  if (y > 6) {
    return front ? 2 : 1;
  }
  if (y < 3) {
    return front ? 4 : 5;
  }
  return front ? 3 : 6;
}

describe("TestOverlapLegality", () => {
  /** The gate tests: every chart shown while a serve is pending must
   * be a legal position under the overlap rules. */
  test.each(ALL_SLOTS.flatMap((setter_slot) => ALL_SIDES.map((side) => [setter_slot, side] as const)))(
    "test_receive_charts_legal(%i, %s)",
    (setter_slot, side) => {
      const pos = formation_xy(setter_slot, Mode.RECEIVE, side);
      assert_overlap_legal(pos, side);
    },
  );

  test.each(ALL_SLOTS.flatMap((setter_slot) => ALL_SIDES.map((side) => [setter_slot, side] as const)))(
    "test_serve_base_legal_server_exempt(%i, %s)",
    (setter_slot, side) => {
      const pos = formation_xy(setter_slot, Mode.SERVE_BASE, side);
      assert_overlap_legal(pos, side, [0]);
      expect(pos[0]).toEqual(serve_xy(side));
    },
  );

  test("test_grid_itself_is_legal", () => {
    for (const side of ALL_SIDES) {
      const pos: Record<number, [number, number]> = {};
      for (const i of ALL_SLOTS) {
        pos[i] = position_xy(i, side);
      }
      assert_overlap_legal(pos, side);
    }
  });
});

describe("TestRoleZones", () => {
  /** After the serve: OH -> 4/6, MB -> 3, libero -> 5, S/OPP -> 2/1. */
  test.each(ALL_SIDES)("test_offense_zones_setter_p1(%s)", (side) => {
    const pos = formation_xy(0, Mode.OFFENSE, side);
    expect(zone_of(pos[1], side)).toBe(4); // front OH approaches zone 4
    expect(zone_of(pos[2], side)).toBe(3); // front MB quick, zone 3
    expect(zone_of(pos[3], side)).toBe(2); // front OPP, zone 2
    expect(zone_of(pos[4], side)).toBe(6); // back OH, pipe from 6
    expect(zone_of(pos[5], side)).toBe(5); // libero slot, zone 5
    // back-row setter penetrates to the net, right of centre
    expect(closer_to_net(pos[0], pos[2], side)).toBe(true);
    expect(right_of(pos[0], pos[2], side)).toBe(true);
  });

  test("test_offense_zones_setter_front", () => {
    // setter at P3 (front): sets at the net; the back-row OPP (P6)
    // covers zone 1
    const pos = formation_xy(2, Mode.OFFENSE, LEFT);
    expect(pos[2][0]).toBeGreaterThan(-2.0); // setter at the net
    expect(zone_of(pos[5], LEFT)).toBe(1); // back OPP -> zone 1
    expect(zone_of(pos[3], LEFT)).toBe(4); // front OH -> zone 4
    expect(zone_of(pos[1], LEFT)).toBe(3); // front MB -> zone 3
  });

  test.each(ALL_SLOTS)("test_defense_block_and_perimeter(%i)", (setter_slot) => {
    const pos = formation_xy(setter_slot, Mode.DEFENSE, LEFT);
    const front = ALL_SLOTS.filter((i) => [1, 2, 3].includes(i));
    for (const i of front) { // block at the net
      expect(pos[i][0]).toBeGreaterThan(-2.0);
    }
    const back = ALL_SLOTS.filter((i) => ![1, 2, 3].includes(i));
    for (const i of back) { // perimeter defence
      expect(pos[i][0]).toBeLessThan(-5.5);
    }
  });
});

describe("TestSetterIdentification", () => {
  test("test_single_setter", () => {
    expect(acting_setter_slot(FIVE_ONE)).toBe(0);
  });

  test("test_six_two_back_row_setter_acts", () => {
    // setters at P2 (front) and P5 (back): the back one runs it
    const roles: Record<number, Role> = { 0: OH, 1: S, 2: MB, 3: OH, 4: S, 5: L };
    expect(acting_setter_slot(roles)).toBe(4);
  });

  test("test_two_back_row_setters_ambiguous", () => {
    const roles: Record<number, Role> = { 0: S, 1: OH, 2: MB, 3: OH, 4: S, 5: L };
    expect(acting_setter_slot(roles)).toBeNull();
  });

  test("test_no_setter", () => {
    const roles: Record<number, Role> = {};
    for (const i of ALL_SLOTS) {
      roles[i] = U;
    }
    expect(acting_setter_slot(roles)).toBeNull();
  });
});

describe("TestSixTwo", () => {
  // S1@P1, OH1@P2, MB1@P3, S2@P4, OH2@P5, MB2@P6 -- setters diagonal
  const LINEUP = ["S1", "OH1", "MB1", "S2", "OH2", "MB2"];
  const ROLE: Record<string, Role> = {
    S1: S, S2: S, OH1: OH, OH2: OH, MB1: MB, MB2: MB,
  };

  function rotations(): { lineup: string[]; roles: Record<number, Role> }[] {
    const out = [];
    let lineup = [...LINEUP];
    for (let i = 0; i < 6; i++) {
      const roles: Record<number, Role> = {};
      lineup.forEach((p, idx) => { roles[idx] = ROLE[p]; });
      out.push({ lineup: [...lineup], roles });
      lineup = rotate_clockwise(lineup);
    }
    return out;
  }

  test("test_acting_setter_is_always_the_back_row_one", () => {
    for (const { lineup, roles } of rotations()) {
      const slot = acting_setter_slot(roles);
      expect(slot, `grid fallback in ${lineup}`).not.toBeNull();
      expect(BACK_ROW.includes(slot!)).toBe(true);
      expect(ROLE[lineup[slot!]]).toBe(S);
    }
  });

  test("test_both_setters_take_turns_setting", () => {
    const acting = rotations().map(
      ({ lineup, roles }) => lineup[acting_setter_slot(roles)!]);
    expect(acting.filter((p) => p === "S1")).toHaveLength(3);
    expect(acting.filter((p) => p === "S2")).toHaveLength(3);
  });

  test("test_front_row_setter_never_receives_and_attacks_right", () => {
    for (const { lineup, roles } of rotations()) {
      const slot = acting_setter_slot(roles)!;
      const fs = lineup.findIndex((p, i) => ROLE[p] === S && i !== slot);
      const rec = formation_xy(slot, Mode.RECEIVE, LEFT);
      const off = formation_xy(slot, Mode.OFFENSE, LEFT);
      expect(-rec[fs][0], `front setter passing in ${lineup}`).toBeLessThanOrEqual(2.0);
      expect(off[fs][1], `front setter not right in ${lineup}`).toBeGreaterThan(4.5);
    }
  });

  test("test_acting_setter_penetrates_to_the_net_to_set", () => {
    for (const { roles } of rotations()) {
      const slot = acting_setter_slot(roles)!;
      const off = formation_xy(slot, Mode.OFFENSE, LEFT);
      expect(-off[slot][0]).toBeLessThanOrEqual(2.0);
      expect(off[slot][1]).toBeGreaterThan(4.5);
    }
  });

  test("test_always_three_front_row_attackers", () => {
    for (const { roles } of rotations()) {
      expect([1, 2, 3]).not.toContain(acting_setter_slot(roles)!);
    }
  });

  test("test_only_the_back_row_setter_charts_are_ever_used", () => {
    const used = new Set(rotations().map(({ roles }) => acting_setter_slot(roles)));
    expect([...used].sort()).toEqual([0, 4, 5]);
  });
});

describe("TestFormationNote", () => {
  test("test_no_note_for_a_valid_six_two", () => {
    const roles: Record<number, Role> = { 0: S, 1: OH, 2: MB, 3: S, 4: OH, 5: MB };
    expect(formation_note(roles)).toBeNull();
  });

  test("test_no_note_for_a_five_one", () => {
    expect(formation_note(FIVE_ONE)).toBeNull();
  });

  test("test_note_when_both_setters_share_the_back_row", () => {
    const roles: Record<number, Role> = { 0: S, 1: OH, 2: MB, 3: OH, 4: S, 5: L };
    const note = formation_note(roles);
    expect(note).not.toBeNull();
    expect(note).toContain("diagonal");
  });

  test("test_note_when_both_setters_share_the_front_row", () => {
    const roles: Record<number, Role> = { 0: OH, 1: S, 2: S, 3: OH, 4: MB, 5: L };
    expect(formation_note(roles)).not.toBeNull();
  });

  test("test_no_note_without_a_setter", () => {
    const roles: Record<number, Role> = {};
    for (const i of ALL_SLOTS) {
      roles[i] = U;
    }
    expect(formation_note(roles)).toBeNull();
  });
});

describe("TestFallbacks", () => {
  test.each(ALL_MODES.flatMap((mode) => ALL_SIDES.map((side) => [mode, side] as const)))(
    "test_no_setter_falls_back_to_grid(%s, %s)",
    (mode, side) => {
      const pos = formation_xy(null, mode, side);
      const expected: Record<number, [number, number]> = {};
      for (const i of ALL_SLOTS) {
        expected[i] = position_xy(i, side);
      }
      expect(pos).toEqual(expected);
    },
  );

  test("test_grid_mode_ignores_setter", () => {
    const pos = formation_xy(2, Mode.GRID, LEFT);
    const expected: Record<number, [number, number]> = {};
    for (const i of ALL_SLOTS) {
      expected[i] = position_xy(i, LEFT);
    }
    expect(pos).toEqual(expected);
  });
});

describe("TestGeometry", () => {
  test.each(
    ALL_SLOTS.flatMap((setter_slot) => [Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE]
      .map((mode) => [setter_slot, mode] as const)),
  )("test_mirroring(%i, %s)", (setter_slot, mode) => {
    const left = formation_xy(setter_slot, mode, LEFT);
    const right = formation_xy(setter_slot, mode, RIGHT);
    for (const i of ALL_SLOTS) {
      const [x, y] = left[i];
      expect(right[i]).toEqual([-x, 9 - y]);
    }
  });

  test.each(
    ALL_SLOTS.flatMap((setter_slot) => [Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE]
      .map((mode) => [setter_slot, mode] as const)),
  )("test_bounds_and_spacing(%i, %s)", (setter_slot, mode) => {
    const pos = formation_xy(setter_slot, mode, LEFT);
    for (const i of ALL_SLOTS) {
      const [x, y] = pos[i];
      expect(x).toBeGreaterThanOrEqual(-13.0);
      expect(x).toBeLessThanOrEqual(-0.5);
      expect(y).toBeGreaterThanOrEqual(-2.5);
      expect(y).toBeLessThanOrEqual(11.5);
    }
    for (let i = 0; i < 6; i += 1) {
      for (let j = i + 1; j < 6; j += 1) {
        const a = pos[i];
        const b = pos[j];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        expect(d).toBeGreaterThanOrEqual(1.2);
      }
    }
  });
});
