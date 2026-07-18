/** User-authored playing systems: import + registry merge (tablet).
 *
 * Mirrors core/user_systems.py where it makes sense for the tablet. The
 * tablet has no editor -- a coach authors a custom system in the desktop
 * app, which writes one JSON file per system, and imports those files
 * here. `refresh_registry` merges the imported systems into
 * `core/systems.ts`'s SYSTEMS in place, so every consumer of the
 * registry -- the setup screen selects, `system_xy` and friends -- picks
 * them up with no other change. A custom id is stored verbatim in
 * `MatchConfig.systems` exactly like a built-in one.
 *
 * Why this is safe to layer on top of the built-ins:
 *
 *   - `BUILTIN_IDS` freezes the registry's keys at module load, before
 *     any user merge has run. Built-ins can never be overwritten,
 *     shadowed or deleted, and a user file whose id collides with a
 *     built-in is skipped, not honoured.
 *   - `refresh_registry` mutates the *existing* SYSTEMS object (other
 *     modules hold a reference to it) rather than rebinding it: it drops
 *     every non-built-in entry and re-inserts the given user systems in
 *     sorted-id order after the built-ins. It is therefore idempotent.
 *   - A bad file must never stop the app. `parse_import` turns every
 *     parse/validation failure into a human problem string and skips
 *     that entry.
 *   - `get_system` already falls back to the default "5-1" for an
 *     unknown id, so a match saved against a since-deleted custom system
 *     still opens -- it simply shows the default geometry.
 *
 * File schema (format 1), all ints stringified because they are JSON
 * object keys, coordinates as `[x, y]` pairs authored on the LEFT half
 * (net x=0, own end line x=-9) exactly like core/formations.ts. Mode
 * names are the `Mode` enum values; `Mode.GRID` is never stored (it is
 * the rotational fallback, not a chart). `serve_base` holds slots 1..5
 * only -- slot 0 is the server, placed by `serve_xy` at lookup time.
 */
import { Mode } from "./formations";
import { Chart, Charts, SYSTEMS, SystemSpec } from "./systems";

export const FORMAT = 1;

// The registry's keys captured before any user merge -- import-order
// safe because merges only ever happen at runtime via refresh_registry.
export const BUILTIN_IDS: ReadonlySet<string> = new Set(Object.keys(SYSTEMS));

// Modes that carry a stored chart (GRID is the fallback, never stored).
const _STORED_MODES: readonly Mode[] = [
  Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE,
];

const _ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/;

// Authored left half plus the free zone: the coordinate box the app is
// willing to draw a token in (mirrors tests/test_formations.py bounds).
const _X_MIN = -13.0;
const _X_MAX = 0.0;
const _Y_MIN = -2.5;
const _Y_MAX = 11.5;

function _repr(v: unknown): string {
  // Approximates Python's repr() for the human messages: strings quoted,
  // everything else stringified.
  if (typeof v === "string") {
    return `'${v}'`;
  }
  return String(v);
}

function _same_int_set(got: Set<number>, want: Set<number>): boolean {
  if (got.size !== want.size) {
    return false;
  }
  for (const n of want) {
    if (!got.has(n)) {
      return false;
    }
  }
  return true;
}

function _sorted_list(want: Set<number>): string {
  return `[${[...want].sort((a, b) => a - b).join(", ")}]`;
}

// --------------------------------------------------------------- serialize

/** JSON-ready dict for a SystemSpec (schema format 1). */
export function serialize_system(spec: SystemSpec): Record<string, unknown> {
  const charts: Record<string, Record<string, Record<string, [number, number]>>> = {};
  for (const mode of _STORED_MODES) {
    const src = spec.charts[mode]!;
    const modeCharts: Record<string, Record<string, [number, number]>> = {};
    for (const key of Object.keys(src)) {
      const chart = src[Number(key)];
      const slotObj: Record<string, [number, number]> = {};
      for (const slot of Object.keys(chart)) {
        const [x, y] = chart[Number(slot)];
        slotObj[slot] = [x, y];
      }
      modeCharts[key] = slotObj;
    }
    charts[mode] = modeCharts;
  }
  return {
    format: FORMAT,
    id: spec.id,
    label: spec.label,
    description: spec.description,
    uses_setter_roles: spec.uses_setter_roles,
    expected_setters: spec.expected_setters,
    fixed_setter_slot: spec.fixed_setter_slot,
    charts,
  };
}

// ------------------------------------------------------------- deserialize

function _is_object(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function _is_number(v: unknown): v is number {
  // JSON true/false is not a coordinate (in JS booleans are their own
  // type, so only a real number qualifies).
  return typeof v === "number";
}

function _int_key(raw: string, what: string): number {
  if (/^[+-]?\d+$/.test(raw)) {
    return Number(raw);
  }
  throw new Error(`${what}: bad key ${_repr(raw)}`);
}

function _parse_chart(raw: unknown, mode: Mode, key: number): Chart {
  const where = `${mode} chart key ${key}`;
  if (!_is_object(raw)) {
    throw new Error(`${where} is not an object`);
  }
  const want = mode === Mode.SERVE_BASE
    ? new Set([1, 2, 3, 4, 5])
    : new Set([0, 1, 2, 3, 4, 5]);
  const chart: Chart = {};
  for (const [s, coord] of Object.entries(raw)) {
    const slot = _int_key(s, where);
    if (!(Array.isArray(coord) && coord.length === 2
        && _is_number(coord[0]) && _is_number(coord[1]))) {
      throw new Error(`${where} slot ${slot}: coordinate must be [x, y]`);
    }
    const x = Number(coord[0]);
    const y = Number(coord[1]);
    if (!(Number.isFinite(x) && Number.isFinite(y))) {
      throw new Error(`${where} slot ${slot}: coordinate must be finite`);
    }
    if (!(_X_MIN <= x && x <= _X_MAX && _Y_MIN <= y && y <= _Y_MAX)) {
      throw new Error(
        `${where} slot ${slot}: (${x}, ${y}) is off the authored area `
        + `(x in [${_X_MIN}, ${_X_MAX}], y in [${_Y_MIN}, ${_Y_MAX}])`);
    }
    chart[slot] = [x, y];
  }
  if (!_same_int_set(new Set(Object.keys(chart).map(Number)), want)) {
    throw new Error(`${where}: slots must be exactly ${_sorted_list(want)}`);
  }
  return chart;
}

/** Build a SystemSpec from a format-1 dict, throwing Error with a human
 * message on any malformed or out-of-range field. The inverse of
 * serialize_system: deserialize_system(serialize_system(spec)) == spec. */
export function deserialize_system(data: unknown): SystemSpec {
  if (!_is_object(data)) {
    throw new Error("not a JSON object");
  }
  if (data.format !== FORMAT) {
    throw new Error(
      `written by a newer version of the app (format `
      + `${_repr(data.format)}, this build reads format ${FORMAT})`);
  }

  const sid = data.id;
  if (!(typeof sid === "string" && _ID_RE.test(sid))) {
    throw new Error(`invalid system id ${_repr(sid)}`);
  }
  const label = data.label;
  const description = data.description;
  if (typeof label !== "string" || typeof description !== "string") {
    throw new Error("label and description must be strings");
  }
  const uses_setter_roles = data.uses_setter_roles;
  if (typeof uses_setter_roles !== "boolean") {
    throw new Error("uses_setter_roles must be a boolean");
  }
  const expected_setters = data.expected_setters;
  if (typeof expected_setters !== "number" || !Number.isInteger(expected_setters)) {
    throw new Error("expected_setters must be an integer");
  }
  const fixed_setter_slot = data.fixed_setter_slot;

  let want_keys: Set<number>;
  if (uses_setter_roles) {
    want_keys = new Set([0, 1, 2, 3, 4, 5]); // one chart per setter slot
  } else {
    want_keys = new Set([0]);                 // single constant key
    if (!(typeof fixed_setter_slot === "number"
        && Number.isInteger(fixed_setter_slot)
        && fixed_setter_slot >= 0 && fixed_setter_slot <= 5)) {
      throw new Error(
        "fixed_setter_slot must be 0..5 for a keyless system");
    }
  }

  const raw_charts = data.charts;
  if (!_is_object(raw_charts)) {
    throw new Error("charts must be an object");
  }
  const charts: Charts = {};
  for (const mode of _STORED_MODES) {
    const raw_mode = raw_charts[mode];
    if (!_is_object(raw_mode)) {
      throw new Error(`missing chart for mode ${_repr(mode)}`);
    }
    const parsed: Record<number, Chart> = {};
    for (const [k, v] of Object.entries(raw_mode)) {
      const ki = _int_key(k, mode);
      parsed[ki] = _parse_chart(v, mode, ki);
    }
    if (!_same_int_set(new Set(Object.keys(parsed).map(Number)), want_keys)) {
      throw new Error(
        `${mode}: chart keys must be exactly ${_sorted_list(want_keys)}`);
    }
    charts[mode] = parsed;
  }

  return {
    id: sid,
    label,
    description,
    uses_setter_roles,
    expected_setters,
    charts,
    fixed_setter_slot: (fixed_setter_slot as number | null) ?? null,
  };
}

// ------------------------------------------------------------------ import

/** Parse imported text holding either ONE serialized system object or an
 * ARRAY of them. Skip-not-fail per entry: every parse/validation failure
 * and every built-in id collision becomes a human problem string, the
 * good ones are kept. */
export function parse_import(
  text: string,
): { specs: SystemSpec[]; problems: string[] } {
  const specs: SystemSpec[] = [];
  const problems: string[] = [];
  let root: unknown;
  try {
    root = JSON.parse(text);
  } catch (e) {
    problems.push(`not valid JSON: ${(e as Error).message}`);
    return { specs, problems };
  }
  const entries = Array.isArray(root) ? root : [root];
  entries.forEach((entry, index) => {
    const where = Array.isArray(root) ? `entry ${index + 1}` : "system";
    let spec: SystemSpec;
    try {
      spec = deserialize_system(entry);
    } catch (e) {
      problems.push(`${where}: ${(e as Error).message}`);
      return;
    }
    if (BUILTIN_IDS.has(spec.id)) {
      problems.push(
        `${where}: id '${spec.id}' collides with a built-in system`);
      return;
    }
    specs.push(spec);
  });
  return { specs, problems };
}

// ---------------------------------------------------------------- registry

/** Re-merge user systems into `core/systems.ts`'s SYSTEMS in place: drop
 * every non-built-in entry, then re-insert the given user systems in
 * sorted-id order after the built-ins. Idempotent; the single runtime
 * entry point for this module. Built-in ids among the input are skipped. */
export function refresh_registry(user: SystemSpec[]): void {
  for (const key of Object.keys(SYSTEMS)) {
    if (!BUILTIN_IDS.has(key)) {
      delete SYSTEMS[key];
    }
  }
  const byId = new Map<string, SystemSpec>();
  for (const spec of user) {
    if (!BUILTIN_IDS.has(spec.id)) {
      byId.set(spec.id, spec);
    }
  }
  for (const sid of [...byId.keys()].sort()) {
    SYSTEMS[sid] = byId.get(sid)!;
  }
}
