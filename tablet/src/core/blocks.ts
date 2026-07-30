/** Where an attack landed, and what that means.
 * Mirrors core/blocks.py (see TRANSLATION.md).
 *
 * A blocked attack is drawn in two strokes: attacker -> block touch (at the
 * net), then block touch -> where the deflected ball ended up. Only the final
 * landing point decides the outcome. All functions are pure so the engine,
 * the desktop UI and the tablet port share a single definition.
 *
 * The same three landing zones also settle an *unblocked* attack, with the
 * opposite verdict -- see `unblocked_attack_is_error`.
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

/** True when an attack arrow ending at (x, y) can be a block contact: it
 * must sit in the BLOCKERS' court -- the ball actually crossed -- and within
 * BLOCK_NET_ZONE of the net. A tip on the attacker's own side of the net
 * means the attack never made it over, which is an error, not a block; that
 * arrow is scored '!' instead of priming a second stroke. */
export function is_block_touch(attacker_side: string, x: number, y: number): boolean {
  return classify_block_deflection(attacker_side, x, y) === IN_PLAY
    && Math.abs(x) <= BLOCK_NET_ZONE;
}

/** True when an attack drawn WITHOUT a block touch is the attacker's own
 * fault, because the ball never legally reached the opponents' court: it
 * landed beyond the lines (out), or short on the attacker's own half (hit
 * into the net). Only IN_PLAY -- in bounds, on the blockers' side -- keeps
 * the rally alive and still needs a rating.
 *
 * This is the mirror image of the blocked case: for the very same landing
 * a block touch makes it '#' (block-out) or '-' (covered), while no block
 * touch makes it '!'. */
export function unblocked_attack_is_error(attacker_side: string, x: number, y: number): boolean {
  return classify_block_deflection(attacker_side, x, y) !== IN_PLAY;
}
