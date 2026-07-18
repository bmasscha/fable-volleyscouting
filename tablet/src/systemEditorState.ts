/** Pure state logic for the tablet's graphical playing-system editor.
 *
 * The desktop app has ``ui/system_editor.py``; this is the tablet's
 * unit-testable core of the same idea, with no Preact in it. It edits a
 * deep working copy of a base system's charts, keyed exactly like
 * ``core/systems.ts``: ``working[mode][key][slot] -> [x, y]`` on the LEFT
 * half. ``key`` is the acting setter's slot 0..5 for setter-keyed systems,
 * the single constant 0 for keyless ones (which instead carry a
 * ``fixed_setter_slot``). ``Mode.SERVE_BASE`` holds slots 1..5 only -- slot
 * 0 is the server, pinned at ``serve_xy`` and never stored. ``Mode.GRID``
 * is the rotational fallback and is not editable here.
 *
 * Every token move is clamped live to the deserializer's coordinate box
 * (x in [-13, 0], y in [-2.5, 11.5]) and snapped to the 0.1 m grid the
 * built-in charts are authored on, so a ``serialize_system`` of the
 * working state always passes validation. The id field IS the save
 * target: ``canSave`` is only true for a regex-valid, non-built-in id
 * (built-ins can never be shadowed). The SystemEditor component drives
 * this module and turns its results into a saved user system.
 */
import {
  Mode, _OFFSET_CATEGORY, overlap_violations,
} from "./core/formations";
import { serve_xy } from "./core/rotation";
import { Chart, Charts, SYSTEMS, SystemSpec, get_system } from "./core/systems";
import { BUILTIN_IDS } from "./core/user_systems";

// Modes that carry a stored chart (GRID is the fallback, never stored).
const _STORED_MODES: readonly Mode[] = [
  Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE,
];

// Must agree with core/user_systems.ts's _ID_RE -- the authority that
// actually accepts or rejects the id on save; duplicated here only to
// drive the Save button's enabled state live as the user types.
const _ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/;

// The deserializer's coordinate box (mirrors core/user_systems.ts);
// clamping to it live guarantees a save never fails validation.
export const X_MIN = -13.0;
export const X_MAX = 0.0;
export const Y_MIN = -2.5;
export const Y_MAX = 11.5;

/** Editor working state: a deep copy of a base system's charts plus its
 * editable metadata. Mutated in place by commitMove / copyKey. */
export interface EditorState {
  base_id: string; // the system this working copy was loaded from
  id: string; // the save target (regex-validated, non-built-in to save)
  label: string;
  description: string;
  uses_setter_roles: boolean;
  fixed_setter_slot: number; // 0..5; null coerced to 0 like the desktop
  expected_setters: number;
  working: Partial<Record<Mode, Record<number, Chart>>>;
}

function _copyChart(chart: Chart): Chart {
  const out: Chart = {};
  for (const slot of Object.keys(chart)) {
    const s = Number(slot);
    out[s] = [chart[s][0], chart[s][1]];
  }
  return out;
}

/** Snap a coordinate to the 0.1 m authoring grid, normalising -0 to 0 so
 * the value round-trips byte-stably through JSON. */
function _snap(v: number): number {
  const r = Math.round(v * 10) / 10;
  return r === 0 ? 0 : r;
}

/** Clamp a coordinate to the deserializer's box; used live during drag so
 * a token can never leave the drawable/saveable area. */
export function clampCoord(x: number, y: number): [number, number] {
  return [
    Math.min(Math.max(x, X_MIN), X_MAX),
    Math.min(Math.max(y, Y_MIN), Y_MAX),
  ];
}

/** A deep working copy of ``baseId``'s charts + metadata. Mutating the
 * returned state can never mutate SYSTEMS (every coordinate is copied).
 * fixed_setter_slot follows the desktop's null->0. */
export function createEditorState(baseId: string): EditorState {
  const spec = SYSTEMS[baseId] ?? get_system(baseId);
  const working: Partial<Record<Mode, Record<number, Chart>>> = {};
  for (const mode of _STORED_MODES) {
    const src = spec.charts[mode]!;
    const modeCharts: Record<number, Chart> = {};
    for (const key of Object.keys(src)) {
      const k = Number(key);
      modeCharts[k] = _copyChart(src[k]);
    }
    working[mode] = modeCharts;
  }
  return {
    base_id: spec.id,
    id: spec.id,
    label: spec.label,
    description: spec.description,
    uses_setter_roles: spec.uses_setter_roles,
    fixed_setter_slot: spec.fixed_setter_slot ?? 0,
    expected_setters: spec.expected_setters,
    working,
  };
}

/** Clamp to the bounds box, snap to 0.1 m, and store into the working
 * chart. The serve server (serve mode, slot 0) is pinned off court and is
 * never stored -- a move on it is a no-op. */
export function commitMove(
  state: EditorState, mode: Mode, key: number, slot: number, x: number, y: number,
): void {
  if (mode === Mode.SERVE_BASE && slot === 0) {
    return;
  }
  const [cx, cy] = clampCoord(x, y);
  state.working[mode]![key][slot] = [_snap(cx), _snap(cy)];
}

/** Copy another key's chart of ``mode`` onto ``toKey`` -- a fast way to
 * author six similar rotations. Only setter-keyed systems have >1 key;
 * for keyless systems this is a no-op. Only the current mode's chart is
 * touched. */
export function copyKey(
  state: EditorState, mode: Mode, fromKey: number, toKey: number,
): void {
  if (!state.uses_setter_roles) {
    return;
  }
  state.working[mode]![toKey] = _copyChart(state.working[mode]![fromKey]);
}

/** The overlap violations for the current chart, or [] when the mode has
 * no serve-contact overlap rules (Offense/Defense). Receive checks all
 * six positions; Serve checks slots 1..5 plus the pinned server at slot 0
 * (which is exempt). */
export function currentViolations(
  state: EditorState, mode: Mode, key: number,
): string[] {
  if (mode === Mode.RECEIVE) {
    const chart = state.working[mode]![key];
    const pos: Record<number, [number, number]> = {};
    for (let i = 0; i < 6; i += 1) {
      pos[i] = chart[i];
    }
    return overlap_violations(pos, "left");
  }
  if (mode === Mode.SERVE_BASE) {
    const chart = state.working[mode]![key];
    const pos: Record<number, [number, number]> = { 0: serve_xy("left") };
    for (let i = 1; i < 6; i += 1) {
      pos[i] = chart[i];
    }
    return overlap_violations(pos, "left", [0]);
  }
  return [];
}

/** A SystemSpec from the working state, coordinates snapped to the 0.1 m
 * grid so the stored file is clean and byte-stable. label falls back to
 * the id; fixed_setter_slot is null for a setter-keyed system. */
export function buildSpec(state: EditorState): SystemSpec {
  const sid = state.id.trim();
  const charts: Charts = {};
  for (const mode of _STORED_MODES) {
    const src = state.working[mode]!;
    const modeCharts: Record<number, Chart> = {};
    for (const key of Object.keys(src)) {
      const k = Number(key);
      const chart: Chart = {};
      for (const slot of Object.keys(src[k])) {
        const s = Number(slot);
        chart[s] = [_snap(src[k][s][0]), _snap(src[k][s][1])];
      }
      modeCharts[k] = chart;
    }
    charts[mode] = modeCharts;
  }
  return {
    id: sid,
    label: state.label.trim() || sid,
    description: state.description.trim(),
    uses_setter_roles: state.uses_setter_roles,
    expected_setters: state.expected_setters,
    charts,
    fixed_setter_slot: state.uses_setter_roles ? null : state.fixed_setter_slot,
  };
}

/** Save is enabled only for a regex-valid id that is not a built-in
 * (built-ins can never be shadowed). */
export function canSave(state: EditorState): boolean {
  const sid = state.id.trim();
  return _ID_RE.test(sid) && !BUILTIN_IDS.has(sid);
}

/** The hint line under the id field: mirrors the desktop's wording. */
export function saveHint(state: EditorState): string {
  const sid = state.id.trim();
  if (BUILTIN_IDS.has(sid)) {
    return "change the id to save your own copy";
  }
  if (sid && !_ID_RE.test(sid)) {
    return "id must start alphanumeric, then letters/digits/-/_ (max 32)";
  }
  return "";
}

/** The slot painted as the acting setter: the current chart key for
 * setter-keyed systems, the fixed setting slot for keyless ones. */
export function actingSetterSlot(state: EditorState, key: number): number {
  return state.uses_setter_roles ? key : state.fixed_setter_slot;
}

/** The small hint under a token: the offset-category role ("S"/"OH"/
 * "MB"/"OPP") for setter-keyed systems, or "sets"/"" for keyless ones. */
export function roleHint(state: EditorState, key: number, slot: number): string {
  if (state.uses_setter_roles) {
    return _OFFSET_CATEGORY[(((slot - key) % 6) + 6) % 6]; // Python's `%`
  }
  return slot === state.fixed_setter_slot ? "sets" : "";
}

/** Replace the entry with ``spec.id`` in-place, or append it if absent --
 * the stored-list update a save performs (and the same semantics the
 * import flow uses when an imported id already exists). */
export function replaceOrAppend(list: SystemSpec[], spec: SystemSpec): SystemSpec[] {
  let found = false;
  const out = list.map((s) => {
    if (s.id === spec.id) {
      found = true;
      return spec;
    }
    return s;
  });
  if (!found) {
    out.push(spec);
  }
  return out;
}
