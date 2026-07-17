/** Registry of playing systems (5-1, 6-2, 6-6, ...). Mirrors core/systems.py.
 *
 * Engine semantics (rotation, scoring, libero exchanges) never depend on
 * which system a team plays -- that is a contract kept elsewhere. A
 * system only changes three display/assist concerns:
 *
 *   - which formation chart is shown for a given rally situation
 *     (`system_xy`), since a 6-2's two setters and a 6-6's keyless
 *     rotation stand differently than a 5-1;
 *   - who the "acting setter" is for UI assists like the setter-tracker
 *     highlight (`acting_setter_slot_for`);
 *   - a soft expectation of how many setters a lineup should carry, for
 *     setup-time validation (`SystemSpec.expected_setters`).
 *
 * A `SystemSpec.id` is stored verbatim in `MatchConfig.systems` and is
 * therefore a stable, persisted contract: renaming or removing an id
 * would strand saved matches. Adding a new system is one registration
 * in `SYSTEMS`; nothing else in this module changes.
 *
 * Chart shape, uniform across every system: `charts[mode][key][slot] ->
 * [x, y]`, authored on the LEFT half (net x=0, own end line x=-9, y=0
 * own left sideline, y=9 own right) exactly like core/formations.ts.
 * `key` is the acting setter's lineup slot 0..5 for systems that key off
 * the setter (`uses_setter_roles=true`); systems that do not (6-6) use
 * the single constant key 0. Mode.SERVE_BASE charts hold slots 1..5
 * only -- slot 0 is always the server, placed by `serve_xy(side)` at
 * lookup time. Mode.GRID has no chart: it is always the rotational
 * grid.
 *
 * 5-1 and 6-2 differ only in label/description/expected_setters; their
 * charts are generated at module load from core/formations.ts's private
 * tables so the two modules can never drift apart. 6-6 has no setter
 * role at all -- the player standing at the net in zone 3 (P3) sets,
 * so its charts are authored directly (see `_SIX_SIX_*` below).
 */
import {
  Mode, _DEFENSE, _OFFENSE, _OFFSET_CATEGORY, _RECEIVE, _SERVE_BASE,
  acting_setter_slot, formation_note,
} from "./formations";
import { Role } from "./models";
import { BACK_ROW, position_xy, serve_xy, to_side } from "./rotation";

export type Chart = Record<number, [number, number]>;
export type Charts = Partial<Record<Mode, Record<number, Chart>>>;

export interface SystemSpec {
  id: string; // "5-1" -- stored in MatchConfig, stable
  label: string; // e.g. "5-1 (one setter)"
  description: string; // one-liner for setup UI tooltips
  uses_setter_roles: boolean; // false => roles ignored, chart key is 0
  expected_setters: number; // soft setup validation (0 for 6-6)
  charts: Charts;
}

// --- 5-1 / 6-2: generated from core/formations.ts's private tables -----
// formation_xy's math, reproduced exactly per setter slot (the "key"):
// RECEIVE is that key's row of _RECEIVE verbatim; for OFFENSE/DEFENSE
// each slot's role is its offset from the setter (_OFFSET_CATEGORY)
// combined with whether it is front row; SERVE_BASE is the same
// slots-1..5 chart regardless of key. 5-1 and 6-2 share this object --
// they never need different geometry, only different setup
// expectations (1 setter vs 2).
function _generateSetterKeyedCharts(): Charts {
  const serveBase: Chart = {};
  for (let i = 1; i < 6; i += 1) {
    serveBase[i] = _SERVE_BASE[i]!;
  }
  const receive: Record<number, Chart> = {};
  const offense: Record<number, Chart> = {};
  const defense: Record<number, Chart> = {};
  const serveBaseByKey: Record<number, Chart> = {};
  for (let key = 0; key < 6; key += 1) {
    receive[key] = { ..._RECEIVE[key] };
    const off: Chart = {};
    const dfn: Chart = {};
    for (let i = 0; i < 6; i += 1) {
      const offset = (((i - key) % 6) + 6) % 6; // Python's `%`
      const cat = _OFFSET_CATEGORY[offset];
      const front = !BACK_ROW.includes(i);
      off[i] = _OFFENSE[`${cat}|${front}`]!;
      dfn[i] = _DEFENSE[`${cat}|${front}`]!;
    }
    offense[key] = off;
    defense[key] = dfn;
    serveBaseByKey[key] = { ...serveBase };
  }
  return {
    [Mode.RECEIVE]: receive,
    [Mode.SERVE_BASE]: serveBaseByKey,
    [Mode.OFFENSE]: offense,
    [Mode.DEFENSE]: defense,
  };
}

const _SETTER_KEYED_CHARTS = _generateSetterKeyedCharts();

// --- 6-6: no setter role -- whoever rotates through P3 sets ------------
// Classic youth "W" reception, authored directly (not generated): five
// passers, P3 up at the net to set. Coordinates satisfy the FIVB
// overlap rules like every other chart in this module.
const _SIX_SIX_RECEIVE: Chart = {
  0: [-7.5, 7.5], // P1 deep right
  1: [-4.0, 7.0], // P2 mid right passer
  2: [-1.0, 4.7], // P3 at the net (sets)
  3: [-4.0, 2.0], // P4 mid left passer
  4: [-7.5, 1.5], // P5 deep left
  5: [-7.5, 4.5], // P6 deep middle
};
const _SIX_SIX_OFFENSE: Chart = {
  0: [-6.8, 7.4], 1: [-3.4, 7.4], 2: [-0.9, 5.8],
  3: [-3.4, 1.6], 4: [-6.8, 1.6], 5: [-6.8, 4.5],
};
const _SIX_SIX_DEFENSE: Chart = {
  0: [-6.0, 7.5], 1: [-1.4, 7.4], 2: [-1.2, 4.5],
  3: [-1.4, 1.6], 4: [-6.0, 1.8], 5: [-7.8, 4.5],
};
const _SIX_SIX_CHARTS: Charts = {
  [Mode.RECEIVE]: { 0: _SIX_SIX_RECEIVE },
  [Mode.SERVE_BASE]: {
    0: (() => {
      const chart: Chart = {};
      for (let i = 1; i < 6; i += 1) {
        chart[i] = _SERVE_BASE[i]!;
      }
      return chart;
    })(),
  },
  [Mode.OFFENSE]: { 0: _SIX_SIX_OFFENSE },
  [Mode.DEFENSE]: { 0: _SIX_SIX_DEFENSE },
};

// --- registry -----------------------------------------------------------
export const SYSTEMS: Record<string, SystemSpec> = {
  "5-1": {
    id: "5-1",
    label: "5-1 (one setter)",
    description: "One setter plays every rotation; the opposite "
      + "always lines up across from them.",
    uses_setter_roles: true,
    expected_setters: 1,
    charts: _SETTER_KEYED_CHARTS,
  },
  "6-2": {
    id: "6-2",
    label: "6-2 (two setters)",
    description: "Two setters, diagonal from each other; whichever "
      + "one is back row runs the offence.",
    uses_setter_roles: true,
    expected_setters: 2,
    charts: _SETTER_KEYED_CHARTS,
  },
  "6-6": {
    id: "6-6",
    label: "6-6 (no dedicated setter)",
    description: "No setter role: whoever rotates through zone 3 "
      + "sets that rally.",
    uses_setter_roles: false,
    expected_setters: 0,
    charts: _SIX_SIX_CHARTS,
  },
};
export const DEFAULT_SYSTEM = "5-1";

/** Look up a system by id, falling back to the default for an unknown
 * or missing id -- forward compat with save files written by a newer
 * version that added a system this build does not know. */
export function get_system(system_id: string | null | undefined): SystemSpec {
  if (system_id == null) {
    return SYSTEMS[DEFAULT_SYSTEM];
  }
  return SYSTEMS[system_id] ?? SYSTEMS[DEFAULT_SYSTEM];
}

/** Registered system ids in registry (menu) order. */
export function system_ids(): string[] {
  return Object.keys(SYSTEMS);
}

/** Which chart row to use for this lineup: the acting setter's slot for
 * setter-keyed systems, or the constant 0 for keyless ones. */
export function chart_key(spec: SystemSpec, roles: Record<number, Role>): number | null {
  if (!spec.uses_setter_roles) {
    return 0;
  }
  return acting_setter_slot(roles);
}

/** Court coordinates (metres) for lineup slots 0..5 (= P1..P6) of a team
 * on `side`, playing `spec`, in the given rally situation. */
export function system_xy(
  spec: SystemSpec, roles: Record<number, Role>, mode: Mode, side: string,
): Record<number, [number, number]> {
  const key = mode === Mode.GRID ? null : chart_key(spec, roles);
  if (key === null) {
    const grid: Record<number, [number, number]> = {};
    for (let i = 0; i < 6; i += 1) {
      grid[i] = position_xy(i, side);
    }
    return grid;
  }
  const chart = spec.charts[mode]![key];
  if (mode === Mode.SERVE_BASE) {
    const out: Record<number, [number, number]> = { 0: serve_xy(side) };
    for (let i = 1; i < 6; i += 1) {
      out[i] = to_side(...chart[i], side);
    }
    return out;
  }
  const out: Record<number, [number, number]> = {};
  for (let i = 0; i < 6; i += 1) {
    out[i] = to_side(...chart[i], side);
  }
  return out;
}

/** Why the realistic charts are unavailable, or null while they are in
 * use. Keyless systems have no setter to misidentify, so they never
 * produce a note. */
export function system_note(spec: SystemSpec, roles: Record<number, Role>): string | null {
  if (!spec.uses_setter_roles) {
    return null;
  }
  return formation_note(roles);
}

/** Lineup slot of whoever is setting this rally. Setter-keyed systems
 * delegate to role identification; a keyless 6-6 always has the player
 * standing at P3 (zone 3, at the net) set. */
export function acting_setter_slot_for(
  spec: SystemSpec, roles: Record<number, Role>,
): number | null {
  if (!spec.uses_setter_roles) {
    return 2;
  }
  return acting_setter_slot(roles);
}
