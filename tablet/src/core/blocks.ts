/** Block deflection classification for two-segment attack trajectories.
 * Mirrors core/blocks.py (see TRANSLATION.md).
 *
 * A blocked attack is drawn in two strokes: attacker -> block touch (at the
 * net), then block touch -> where the deflected ball ended up. Only the final
 * landing point decides the outcome. All functions are pure so the engine,
 * the desktop UI and the tablet port share a single definition.
 */
import { COURT_HALF_LENGTH, COURT_WIDTH, LEFT } from "./rotation";

// Landing this far beyond the lines still counts as in (same tolerance the
// UIs apply to out-served balls).
export const OUT_TOLERANCE = 0.4;
// A pending attack arrow must end within this distance of the net for a
// follow-up drag to count as the block deflection...
export const BLOCK_NET_ZONE = 1.5;
// ...and that follow-up drag must start within this radius of the arrow tip.
export const BLOCK_GRAB_RADIUS = 1.0;

export const BLOCK_OUT = "block_out"; // deflected out of bounds -> point for the attackers
export const COVERED = "covered"; // back into the attacker's court, still in play
export const IN_PLAY = "in_play"; // stays on the blockers' side, still in play

export function landing_in_bounds(x: number, y: number,
  tolerance: number = OUT_TOLERANCE): boolean {
  return (-COURT_HALF_LENGTH - tolerance <= x && x <= COURT_HALF_LENGTH + tolerance
    && -tolerance <= y && y <= COURT_WIDTH + tolerance);
}

/** Outcome of a block deflection landing at (x, y) for an attacker
 * playing on `attacker_side` (LEFT = the x < 0 half). A landing exactly
 * on the net plane (x == 0) counts as the blockers' side. */
export function classify_block_deflection(attacker_side: string, x: number, y: number): string {
  if (!landing_in_bounds(x, y)) {
    return BLOCK_OUT;
  }
  const on_attacker_half = attacker_side === LEFT ? x < 0 : x > 0;
  return on_attacker_half ? COVERED : IN_PLAY;
}
