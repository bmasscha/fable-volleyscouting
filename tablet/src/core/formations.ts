/** Realistic (game-like) court positions per rally situation.
 *
 * The rotation order P1..P6 only fixes the service order and the overlap
 * rules at the instant of serve contact (FIVB 7.4-7.5): each front-row
 * player must be closer to the net than their back-row counterpart
 * (P2/P1, P3/P6, P4/P5) and the lateral order within each row must hold
 * (P2 right of P3 right of P4; P1 right of P6 right of P5). The moment
 * the serve is contacted all constraints vanish and players switch to
 * role-based positions. This module places tokens the way a real 5-1
 * team stands.
 *
 * Everything is keyed by the *acting setter's* lineup slot: in a 5-1 the
 * personnel at each rotational offset from the setter is fixed by the
 * diagonals (offset 0 = setter, 3 = opposite, 1/4 = outside hitters,
 * 2/5 = middles, with the libero standing in the back-row middle slot).
 * That makes the charts independent of how carefully roles were entered:
 * only the setter needs to be identifiable. No setter -> rotational grid.
 *
 * Coordinates are authored for the LEFT half (net x=0, own end line
 * x=-9, own right hand at y=9) and mirrored for the right half.
 */
import { Role } from "./models";
import { BACK_ROW, position_xy, serve_xy, to_side } from "./rotation";

export const Mode = {
  RECEIVE: "receive", // opponent about to serve / serving
  SERVE_BASE: "serve_base", // own team serving, pre-contact
  OFFENSE: "offense", // own team building the attack
  DEFENSE: "defense", // opponent attacking, block + perimeter
  GRID: "grid", // rotational grid (fallback / off)
} as const;
export type Mode = (typeof Mode)[keyof typeof Mode];

/** Lineup slot (0..5) of the acting setter, or None if no setter is
 * identifiable. With two setters on court (a 6-2) the back-row one
 * runs the offence; two back-row setters are ambiguous -> None. */
export function acting_setter_slot(roles: Record<number, Role>): number | null {
  const setters = Object.entries(roles)
    .filter(([, r]) => r === Role.SETTER)
    .map(([i]) => Number(i));
  if (setters.length === 1) {
    return setters[0];
  }
  if (setters.length === 2) {
    const back = setters.filter((i) => BACK_ROW.includes(i));
    if (back.length === 1) {
      return back[0];
    }
  }
  return null;
}

/** Why the realistic charts are unavailable, for the UIs to show, or
 * null while they are in use.
 *
 * Only a real misconfiguration is reported: two or more setters on
 * court without exactly one of them in the back row. A 6-2 keeps its
 * setters diagonal (3 apart), so exactly one is always back row and
 * the acting one is decidable; setters sharing a row make it
 * ambiguous. No setter at all is a supported fallback (roles simply
 * were not entered), not a mistake -- it is never flagged. */
export function formation_note(roles: Record<number, Role>): string | null {
  if (acting_setter_slot(roles) !== null) {
    return null;
  }
  const setters = Object.values(roles).filter((r) => r === Role.SETTER);
  if (setters.length >= 2) {
    return "setters in the same row - a 6-2 needs them diagonal "
      + "(3 apart); showing the rotational grid";
  }
  return null;
}

// --- serve receive, keyed by the setter's slot -------------------------
// Six classic 5-1 reception charts: three passers (both outside hitters
// + the libero in the back-row middle slot) in a passing line ~6.5 m off
// the net, front middle at the net for the quick, opposite out of the
// passing lanes, setter hiding as close to the setting target (net,
// right of centre) as the overlap rules allow. Every chart satisfies
// every overlap constraint (pinned by tests/test_formations.py).
// Values: slot index 0..5 (= P1..P6) -> (x, y) on the LEFT half.
export const _RECEIVE: Record<number, Record<number, [number, number]>> = {
  0: { 0: [-6.8, 8.2], // S    hides in the right-back corner...
    1: [-5.2, 7.0], // OH   ...behind the P2 passer, pulled short
    2: [-1.2, 4.5], // MB   net, quick
    3: [-1.6, 1.6], // OPP  net left, switches right after contact
    4: [-6.5, 1.8], // OH   passer, left lane
    5: [-6.5, 4.5] }, // L    passer, middle lane
  1: { 0: [-6.5, 7.2], // L    passer, right lane
    1: [-1.0, 7.0], // S    front right: already at the net
    2: [-5.6, 2.0], // OH   passer, middle lane
    3: [-1.4, 1.0], // MB   net, slides to the middle
    4: [-8.0, 1.0], // OPP  tucked short left, out of the lanes
    5: [-6.7, 4.5] }, // OH   passer, left lane
  2: { 0: [-5.4, 7.4], // OH   passer, right lane
    1: [-1.4, 7.4], // MB   net right, switches to the middle
    2: [-0.9, 5.6], // S    front middle: at the net, slides right
    3: [-5.2, 1.8], // OH   passer, left lane
    4: [-6.6, 4.5], // L    passer, middle lane
    5: [-7.5, 6.6] }, // OPP  short mid-right, out of the lanes
  3: { 0: [-7.4, 8.3], // OPP  short in the zone-1 corner
    1: [-5.4, 1.5], // OH   passer, right lane
    2: [-2.5, 1.0], // MB   net right, switches to the middle
    3: [-1.0, 0.5], // S    front left: stacked right at the net
    4: [-6.5, 4.5], // OH   passer, left lane
    5: [-5.5, 7.5] }, // L    passer, middle lane
  4: { 0: [-6.5, 7.6], // L    passer, right lane
    1: [-1.4, 7.2], // OPP  net right
    2: [-5.6, 2.0], // OH   passer, middle lane
    3: [-1.4, 1.8], // MB   net, slides to the middle
    4: [-3.0, 3.0], // S    stacked short left, releases at contact
    5: [-6.9, 4.5] }, // OH   passer, left lane
  5: { 0: [-5.5, 7.4], // OH   passer, right lane
    1: [-2.0, 7.2], // MB   net right, switches to the middle
    2: [-0.9, 5.5], // OPP  net, switches right after contact
    3: [-5.0, 1.6], // OH   passer, left lane
    4: [-6.5, 4.5], // L    passer, middle-left lane
    5: [-2.5, 5.4] }, // S    pushed up mid-right, releases at contact
};

export type _OffsetCategory = "S" | "OPP" | "OH" | "MB";

export function _spot_key(cat: _OffsetCategory, front: boolean): string {
  return `${cat}|${front}`;
}

// --- role-based spots (by offset from the setter + front/back row) -----
// After the serve is contacted: OH -> 4 (front) / 6 (back, pipe),
// MB -> 3 (front) / 5 (back = libero), S/OPP -> 2 (front) / 1 (back);
// a back-row setter penetrates to the setting target at the net.
//   offset category: 0 = S, 3 = OPP, 1/4 = OH, 2/5 = MB.
export const _OFFENSE: Record<string, [number, number]> = {
  [_spot_key("S", true)]: [-0.9, 5.8], // setting target, right of centre
  [_spot_key("S", false)]: [-1.6, 6.2], // penetrated from the back row
  [_spot_key("OPP", true)]: [-3.4, 7.4], // zone 2 approach
  [_spot_key("OPP", false)]: [-6.8, 7.4], // zone 1, D-ball / defence
  [_spot_key("OH", true)]: [-3.4, 1.6], // zone 4 approach
  [_spot_key("OH", false)]: [-6.8, 4.5], // zone 6, pipe / defence
  [_spot_key("MB", true)]: [-2.6, 4.4], // zone 3, quick approach
  [_spot_key("MB", false)]: [-6.8, 1.6], // zone 5 (the libero)
};
export const _DEFENSE: Record<string, [number, number]> = {
  [_spot_key("S", true)]: [-1.4, 7.4], // block, zone 2
  [_spot_key("S", false)]: [-6.0, 7.5], // perimeter, zone 1
  [_spot_key("OPP", true)]: [-1.4, 7.4],
  [_spot_key("OPP", false)]: [-6.0, 7.5],
  [_spot_key("OH", true)]: [-1.4, 1.6], // block, zone 4
  [_spot_key("OH", false)]: [-7.8, 4.5], // deep zone 6
  [_spot_key("MB", true)]: [-1.2, 4.5], // block, middle
  [_spot_key("MB", false)]: [-6.0, 1.8], // zone 5 (the libero)
};
export const _OFFSET_CATEGORY: Record<number, _OffsetCategory> = {
  0: "S", 1: "OH", 2: "MB", 3: "OPP", 4: "OH", 5: "MB",
};

// --- serving team, pre-contact (overlap applies; server exempt) --------
// Rotational order, front row tight to the net ready to block, back row
// spread; the switch to role-based defence happens after contact.
export const _SERVE_BASE: Record<number, [number, number] | null> = {
  0: null, // server: serve_xy(side)
  1: [-1.6, 7.4],
  2: [-1.6, 4.5],
  3: [-1.6, 1.6],
  4: [-6.5, 1.8],
  5: [-6.5, 4.6],
};

/** FIVB 7.4-7.5 legality of a serve-contact position, as a list of
 * human-readable violation strings (empty list = legal).
 *
 * This is the non-asserting twin of tests/test_formations.py's
 * ``assert_overlap_legal`` and MUST agree with it exactly, so any
 * chart the tests accept this reports as legal. Each front/back pair
 * (P2/P1, P3/P6, P4/P5) needs the front player strictly closer to the
 * net; each lateral pair (P2>P3>P4, P1>P6>P5) needs the first strictly
 * to the team's own right. "Closer" and "right" both depend on the
 * half: a left-side team faces east (net = larger x, right = larger
 * y), a right-side team faces west (both reversed). A pair with either
 * slot in `exempt` is skipped -- used for the server (slot 0), who is
 * off court behind the end line and outside the overlap at contact. */
export function overlap_violations(
  pos: Record<number, [number, number]>, side: string, exempt: number[] = [],
): string[] {
  const closer_to_net = (a: [number, number], b: [number, number]): boolean => (
    side === "left" ? a[0] > b[0] : a[0] < b[0]);
  const right_of = (a: [number, number], b: [number, number]): boolean => (
    side === "left" ? a[1] > b[1] : a[1] < b[1]);

  const out: string[] = [];
  for (const [front, back] of [[1, 0], [2, 5], [3, 4]] as [number, number][]) { // P2/P1, P3/P6, P4/P5
    if (exempt.includes(front) || exempt.includes(back)) {
      continue;
    }
    if (!closer_to_net(pos[front], pos[back])) {
      out.push(`P${front + 1} must be in front of P${back + 1}`);
    }
  }
  for (const [right, left] of [[1, 2], [2, 3], [0, 5], [5, 4]] as [number, number][]) { // P2>P3>P4, P1>P6>P5
    if (exempt.includes(right) || exempt.includes(left)) {
      continue;
    }
    if (!right_of(pos[right], pos[left])) {
      out.push(`P${right + 1} must be right of P${left + 1}`);
    }
  }
  return out;
}

/** Court coordinates (metres) for lineup slots 0..5 (= P1..P6) of a
 * team playing on `side`, standing like a real 5-1 team in the given
 * situation. Falls back to the rotational grid without a setter. */
export function formation_xy(setter_slot: number | null, mode: Mode,
  side: string): Record<number, [number, number]> {
  if (mode === Mode.GRID || setter_slot === null) {
    const grid: Record<number, [number, number]> = {};
    for (let i = 0; i < 6; i += 1) {
      grid[i] = position_xy(i, side);
    }
    return grid;
  }
  if (mode === Mode.RECEIVE) {
    const chart = _RECEIVE[setter_slot];
    const out: Record<number, [number, number]> = {};
    for (let i = 0; i < 6; i += 1) {
      out[i] = to_side(...chart[i], side);
    }
    return out;
  }
  if (mode === Mode.SERVE_BASE) {
    const out: Record<number, [number, number]> = { 0: serve_xy(side) };
    for (let i = 1; i < 6; i += 1) {
      out[i] = to_side(..._SERVE_BASE[i]!, side);
    }
    return out;
  }
  // OFFENSE / DEFENSE: diagonal pairs (offsets 3 apart) always land on
  // slots 3 apart, i.e. one front row + one back row -- so each pair
  // takes its front and back spot and positions can never collide.
  const spots = mode === Mode.OFFENSE ? _OFFENSE : _DEFENSE;
  const xy: Record<number, [number, number]> = {};
  for (let i = 0; i < 6; i += 1) {
    const offset = ((i - setter_slot) % 6 + 6) % 6; // Python's `%`
    const cat = _OFFSET_CATEGORY[offset];
    xy[i] = spots[_spot_key(cat, !BACK_ROW.includes(i))];
  }
  const out: Record<number, [number, number]> = {};
  for (let i = 0; i < 6; i += 1) {
    out[i] = to_side(...xy[i], side);
  }
  return out;
}
