import { describe, expect, test } from "vitest";

import { Mode, formation_xy } from "../src/core/formations";
import {
  AWAY, HOME, Role, config_from_dict, config_to_dict, default_config,
} from "../src/core/models";
import { LEFT, RIGHT, position_xy, serve_xy, to_side } from "../src/core/rotation";
import {
  DEFAULT_SYSTEM,
  SYSTEMS,
  acting_setter_slot_for,
  chart_key,
  get_system,
  system_ids,
  system_note,
  system_xy,
} from "../src/core/systems";

const S = Role.SETTER;
const OH = Role.OUTSIDE;
const MB = Role.MIDDLE;
const OPP = Role.OPPOSITE;
const L = Role.LIBERO;
const U = Role.UNIVERSAL;

const ALL_SLOTS = [0, 1, 2, 3, 4, 5];
const ALL_SIDES = [LEFT, RIGHT];
const ALL_MODES: readonly Mode[] = [Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE];

// A textbook 5-1 lineup with the setter starting at P1 (mirrors
// formations.test.ts's FIVE_ONE fixture).
const FIVE_ONE: Record<number, Role> = { 0: S, 1: OH, 2: MB, 3: OPP, 4: OH, 5: L };

function closer_to_net(a: [number, number], b: [number, number], side: string): boolean {
  return side === LEFT ? a[0] > b[0] : a[0] < b[0];
}

function right_of(a: [number, number], b: [number, number], side: string): boolean {
  return side === LEFT ? a[1] > b[1] : a[1] < b[1];
}

function assert_overlap_legal(
  pos: Record<number, [number, number]>, side: string, exempt: number[] = [],
): void {
  const pairs_front: [number, number][] = [[1, 0], [2, 5], [3, 4]];
  const lateral: [number, number][] = [[1, 2], [2, 3], [0, 5], [5, 4]];
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

/** A single-setter lineup with the setter at `slot` -- the only thing
 * acting_setter_slot (and hence chart_key) looks at; the other five
 * slots' roles are irrelevant to the chart lookup. */
function rolesWithSetterAt(slot: number): Record<number, Role> {
  const roles: Record<number, Role> = {};
  for (const i of ALL_SLOTS) {
    roles[i] = i === slot ? S : OH;
  }
  return roles;
}

// --- 1. every registered system, every chart key: legality/geometry ----
function systemChartKeys(spec: (typeof SYSTEMS)[string]): number[] {
  return spec.uses_setter_roles ? ALL_SLOTS : [0];
}

const SYSTEM_KEY_PAIRS: [string, number][] = Object.entries(SYSTEMS).flatMap(
  ([systemId, spec]) => systemChartKeys(spec).map((key) => [systemId, key] as [string, number]),
);

describe("TestEveryRegisteredSystem", () => {
  test.each(SYSTEM_KEY_PAIRS.flatMap(([systemId, key]) => ALL_SIDES.map((side) => [systemId, key, side] as const)))(
    "test_receive_chart_legal(%s, %i, %s)",
    (systemId, key, side) => {
      const spec = SYSTEMS[systemId];
      const chart = spec.charts[Mode.RECEIVE]![key];
      const pos: Record<number, [number, number]> = {};
      for (const i of ALL_SLOTS) {
        pos[i] = to_side(chart[i][0], chart[i][1], side);
      }
      assert_overlap_legal(pos, side);
    },
  );

  test.each(SYSTEM_KEY_PAIRS.flatMap(([systemId, key]) => ALL_SIDES.map((side) => [systemId, key, side] as const)))(
    "test_serve_base_legal_server_exempt(%s, %i, %s)",
    (systemId, key, side) => {
      const spec = SYSTEMS[systemId];
      const chart = spec.charts[Mode.SERVE_BASE]![key];
      const pos: Record<number, [number, number]> = { 0: serve_xy(side) };
      for (let i = 1; i < 6; i += 1) {
        pos[i] = to_side(chart[i][0], chart[i][1], side);
      }
      assert_overlap_legal(pos, side, [0]);
      expect(pos[0]).toEqual(serve_xy(side));
    },
  );

  test.each(SYSTEM_KEY_PAIRS.flatMap(([systemId, key]) => ALL_MODES.map((mode) => [systemId, key, mode] as const)))(
    "test_all_six_slots_present(%s, %i, %s)",
    (systemId, key, mode) => {
      const spec = SYSTEMS[systemId];
      const chart = spec.charts[mode]![key];
      const expected = mode === Mode.SERVE_BASE ? [1, 2, 3, 4, 5] : ALL_SLOTS;
      expect(Object.keys(chart).map(Number).sort()).toEqual(expected.sort());
    },
  );

  test.each(
    SYSTEM_KEY_PAIRS.flatMap(
      ([systemId, key]) => [Mode.RECEIVE, Mode.OFFENSE, Mode.DEFENSE].map((mode) => [systemId, key, mode] as const),
    ),
  )("test_pairwise_spacing(%s, %i, %s)", (systemId, key, mode) => {
    const spec = SYSTEMS[systemId];
    const chart = spec.charts[mode]![key];
    const pts = ALL_SLOTS.map((i) => chart[i]);
    for (let i = 0; i < 6; i += 1) {
      for (let j = i + 1; j < 6; j += 1) {
        const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]);
        expect(d, `${systemId}/${mode}/${key}: slots too close: ${d.toFixed(2)}`).toBeGreaterThanOrEqual(1.2);
      }
    }
  });

  test.each(SYSTEM_KEY_PAIRS.flatMap(([systemId, key]) => ALL_MODES.map((mode) => [systemId, key, mode] as const)))(
    "test_mirroring_consistency(%s, %i, %s)",
    (systemId, key, mode) => {
      const spec = SYSTEMS[systemId];
      const chart = spec.charts[mode]![key];
      const slots = mode === Mode.SERVE_BASE ? [1, 2, 3, 4, 5] : ALL_SLOTS;
      for (const i of slots) {
        const [x, y] = chart[i];
        const left = to_side(x, y, LEFT);
        const right = to_side(x, y, RIGHT);
        expect(left).toEqual([x, y]);
        expect(right[0]).toBeCloseTo(-x);
        expect(right[1]).toBeCloseTo(9 - y);
      }
    },
  );

  test.each(SYSTEM_KEY_PAIRS.flatMap(([systemId, key]) => ALL_MODES.map((mode) => [systemId, key, mode] as const)))(
    "test_bounds(%s, %i, %s)",
    (systemId, key, mode) => {
      const spec = SYSTEMS[systemId];
      const chart = spec.charts[mode]![key];
      for (const [i, [x, y]] of Object.entries(chart)) {
        expect(x, `${systemId}/${mode}/${key} slot ${i} off court`).toBeGreaterThanOrEqual(-13.0);
        expect(x, `${systemId}/${mode}/${key} slot ${i} off court`).toBeLessThanOrEqual(-0.5);
        expect(y, `${systemId}/${mode}/${key} slot ${i} off court`).toBeGreaterThanOrEqual(-2.5);
        expect(y, `${systemId}/${mode}/${key} slot ${i} off court`).toBeLessThanOrEqual(11.5);
      }
    },
  );
});

// --- 2. regression: 5-1 / 6-2 reproduce formation_xy --------------------
describe("TestFiveOneRegression", () => {
  test.each(
    ALL_MODES.flatMap(
      (mode) => ALL_SLOTS.flatMap(
        (setterSlot) => ALL_SIDES.map((side) => [mode, setterSlot, side] as const),
      ),
    ),
  )("test_matches_formation_xy(%s, %i, %s)", (mode, setterSlot, side) => {
    const spec = SYSTEMS["5-1"];
    const roles = rolesWithSetterAt(setterSlot);
    const got = system_xy(spec, roles, mode, side);
    const want = formation_xy(setterSlot, mode, side);
    expect(got).toEqual(want);
  });

  test("test_six_two_shares_charts_with_five_one", () => {
    const fiveOne = SYSTEMS["5-1"];
    const sixTwo = SYSTEMS["6-2"];
    expect(fiveOne.charts).toBe(sixTwo.charts);
  });
});

// --- 3. 6-6: keyless system ----------------------------------------------
describe("TestSixSix", () => {
  test("test_chart_key_always_zero", () => {
    const spec = SYSTEMS["6-6"];
    const allUniversal: Record<number, Role> = {};
    for (const i of ALL_SLOTS) allUniversal[i] = U;
    const withSetters: Record<number, Role> = { 0: S, 1: OH, 2: MB, 3: OPP, 4: OH, 5: L };
    expect(chart_key(spec, allUniversal)).toBe(0);
    expect(chart_key(spec, withSetters)).toBe(0);
    expect(chart_key(spec, {})).toBe(0);
  });

  test("test_note_always_none", () => {
    const spec = SYSTEMS["6-6"];
    const allUniversal: Record<number, Role> = {};
    for (const i of ALL_SLOTS) allUniversal[i] = U;
    const twoSettersSameRow: Record<number, Role> = { 0: S, 1: OH, 2: MB, 3: OH, 4: S, 5: L };
    expect(system_note(spec, allUniversal)).toBeNull();
    expect(system_note(spec, twoSettersSameRow)).toBeNull();
    expect(system_note(spec, {})).toBeNull();
  });

  test("test_acting_setter_slot_is_p3", () => {
    const spec = SYSTEMS["6-6"];
    const allUniversal: Record<number, Role> = {};
    for (const i of ALL_SLOTS) allUniversal[i] = U;
    expect(acting_setter_slot_for(spec, allUniversal)).toBe(2);
    expect(acting_setter_slot_for(spec, {})).toBe(2);
  });

  test("test_all_universal_gets_the_w_chart_not_the_grid", () => {
    const spec = SYSTEMS["6-6"];
    const allUniversal: Record<number, Role> = {};
    for (const i of ALL_SLOTS) allUniversal[i] = U;
    const pos = system_xy(spec, allUniversal, Mode.RECEIVE, LEFT);
    const grid: Record<number, [number, number]> = {};
    for (const i of ALL_SLOTS) grid[i] = position_xy(i, LEFT);
    expect(pos).not.toEqual(grid);

    const want: Record<number, [number, number]> = {};
    for (const i of ALL_SLOTS) {
      const [x, y] = spec.charts[Mode.RECEIVE]![0][i];
      want[i] = [x, y];
    }
    expect(pos).toEqual(want);
  });

  test("test_grid_mode_still_falls_back", () => {
    const spec = SYSTEMS["6-6"];
    const allUniversal: Record<number, Role> = {};
    for (const i of ALL_SLOTS) allUniversal[i] = U;
    const pos = system_xy(spec, allUniversal, Mode.GRID, LEFT);
    const expected: Record<number, [number, number]> = {};
    for (const i of ALL_SLOTS) expected[i] = position_xy(i, LEFT);
    expect(pos).toEqual(expected);
  });
});

// --- 4. registry lookups --------------------------------------------
describe("TestRegistry", () => {
  test("test_known_ids", () => {
    for (const systemId of ["5-1", "6-2", "6-6"]) {
      expect(get_system(systemId).id).toBe(systemId);
    }
  });

  test("test_unknown_id_falls_back_to_default", () => {
    expect(get_system("7-0").id).toBe(DEFAULT_SYSTEM);
  });

  test("test_none_falls_back_to_default", () => {
    expect(get_system(null).id).toBe(DEFAULT_SYSTEM);
    expect(get_system(undefined).id).toBe(DEFAULT_SYSTEM);
  });

  test("test_system_ids_order", () => {
    expect(system_ids()).toEqual(["5-1", "6-2", "6-6"]);
  });
});

// --- 5. MatchConfig round-trip ---------------------------------------
describe("TestMatchConfigSystems", () => {
  test("test_default", () => {
    const cfg = default_config();
    expect(cfg.systems).toEqual({ [HOME]: "5-1", [AWAY]: "5-1" });
  });

  test("test_round_trip", () => {
    const cfg = { ...default_config(), systems: { [HOME]: "6-2", [AWAY]: "6-6" } };
    const d = config_to_dict(cfg);
    expect(d.systems).toEqual({ [HOME]: "6-2", [AWAY]: "6-6" });
    const restored = config_from_dict(d);
    expect(restored.systems).toEqual({ [HOME]: "6-2", [AWAY]: "6-6" });
  });

  test("test_from_dict_without_systems_defaults_both", () => {
    const d = config_to_dict(default_config());
    delete d.systems;
    const restored = config_from_dict(d);
    expect(restored.systems).toEqual({ [HOME]: "5-1", [AWAY]: "5-1" });
  });

  test("test_from_dict_partial_systems_defaults_the_rest", () => {
    const d = config_to_dict(default_config());
    d.systems = { home: "6-6" };
    const restored = config_from_dict(d);
    expect(restored.systems).toEqual({ [HOME]: "6-6", [AWAY]: "5-1" });
  });

  test("test_from_dict_ignores_unknown_team_keys", () => {
    const d = config_to_dict(default_config());
    d.systems = { home: "6-2", referee: "6-6" };
    const restored = config_from_dict(d);
    expect(restored.systems).toEqual({ [HOME]: "6-2", [AWAY]: "5-1" });
  });
});
