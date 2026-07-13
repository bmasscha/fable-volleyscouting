/** Rotation math and position -> court coordinate mapping.
 *
 * Positions are stored as list indices 0..5 meaning P1..P6:
 *   P1 = right back (server), P2 = right front, P3 = middle front,
 *   P4 = left front, P5 = left back, P6 = middle back
 * -- always from the team's own perspective facing the net.
 *
 * Court coordinate system (metres): net at x = 0, court x in [-9, +9],
 * sidelines y = 0 (top of screen / "north") and y = 9 (bottom / "south").
 * A team playing on the LEFT half faces east: its right hand points south,
 * so its P1/P2 column sits at large y. The right half is the 180-degree
 * rotation of the left half.
 */

export const COURT_HALF_LENGTH = 9.0;
export const COURT_WIDTH = 9.0;
export const ATTACK_LINE = 3.0; // distance from net
export const FREE_ZONE_X = 4.0; // free zone depth behind the end lines
export const FREE_ZONE_Y = 2.5; // free zone depth beyond the sidelines

export const FRONT_ROW: readonly number[] = [1, 2, 3]; // indices of P2, P3, P4
export const BACK_ROW: readonly number[] = [0, 5, 4]; // indices of P1, P6, P5

export const LEFT = "left" as const;
export const RIGHT = "right" as const;

// Home-base coordinates for a team on the LEFT half (facing east).
const _LEFT_XY: Record<number, [number, number]> = {
  0: [-6.5, 7.5], // P1 back  right (south)
  1: [-2.2, 7.5], // P2 front right
  2: [-2.2, 4.5], // P3 front middle
  3: [-2.2, 1.5], // P4 front left (north)
  4: [-6.5, 1.5], // P5 back  left
  5: [-6.5, 4.5], // P6 back  middle
};

/** One rotation on gaining serve: P2 becomes the new P1 (server),
 * P3->P2, P4->P3, P5->P4, P6->P5 and the old P1 moves to P6. */
export function rotate_clockwise<T>(lineup: T[]): T[] {
  return [...lineup.slice(1), lineup[0]];
}

/** Map a coordinate authored for the LEFT half to the given side.
 * The right half is the 180-degree rotation of the left half. */
export function to_side(x: number, y: number, side: string): [number, number] {
  if (side === RIGHT) {
    return [-x, COURT_WIDTH - y];
  }
  return [x, y];
}

/** Court coordinates (metres) of position P{pos_index+1} for a team
 * playing on `side` ('left' or 'right'). */
export function position_xy(pos_index: number, side: string): [number, number] {
  return to_side(..._LEFT_XY[pos_index], side);
}

/** Spot behind the end line where the server stands. */
export function serve_xy(side: string): [number, number] {
  return to_side(-(COURT_HALF_LENGTH + 1.2), 7.5, side);
}

export function is_front_row(pos_index: number): boolean {
  return FRONT_ROW.includes(pos_index);
}

export function is_back_row(pos_index: number): boolean {
  return BACK_ROW.includes(pos_index);
}
