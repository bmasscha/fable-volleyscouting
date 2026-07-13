/** Official-rule checks: set/match win conditions, substitution legality,
 * libero legality. All functions are pure and take primitives, so they are
 * trivially unit-testable and reusable by the engine and the UI.
 *
 * The app is a scouting tool, not a referee: legality checks return WARNING
 * strings instead of raising, and the engine applies the event anyway --
 * what happened on court is the ground truth.
 */
import { MatchConfig } from "./models";
import { is_back_row } from "./rotation";

export function is_deciding_set(config: MatchConfig, set_number: number): boolean {
  return set_number === 2 * config.sets_to_win - 1;
}

export function set_target(config: MatchConfig, set_number: number): number {
  return is_deciding_set(config, set_number)
    ? config.points_deciding_set
    : config.points_per_set;
}

/** Return 0 if side A won the set, 1 if side B, null if it continues.
 * A set is won at the target with at least `min_lead` difference (no cap). */
export function set_winner(
  config: MatchConfig, set_number: number, score_a: number, score_b: number,
): 0 | 1 | null {
  const target = set_target(config, set_number);
  if (score_a >= target && score_a - score_b >= config.min_lead) {
    return 0;
  }
  if (score_b >= target && score_b - score_a >= config.min_lead) {
    return 1;
  }
  return null;
}

export function match_winner(
  config: MatchConfig, sets_a: number, sets_b: number,
): 0 | 1 | null {
  if (sets_a >= config.sets_to_win) {
    return 0;
  }
  if (sets_b >= config.sets_to_win) {
    return 1;
  }
  return null;
}

/** Warnings for a proposed substitution (player_in replaces player_out).
 *
 * Rules: max `subs_per_set` per team per set; a player and their
 * substitute form an exclusive pair -- the starter may re-enter once,
 * only for the player who replaced them, and that closes the pair.
 */
export function validate_substitution(
  lineup: string[],
  liberos: string[],
  subs_used: number,
  sub_pairs: [string, string][],
  player_out: string,
  player_in: string,
  config: MatchConfig,
): string[] {
  const w: string[] = [];
  if (subs_used >= config.subs_per_set) {
    w.push(`substitution limit (${config.subs_per_set}) already reached`);
  }
  if (!lineup.includes(player_out)) {
    w.push("player going out is not on court");
  }
  if (lineup.includes(player_in)) {
    w.push("player coming in is already on court");
  }
  if (liberos.includes(player_in)) {
    w.push("a libero cannot enter through a substitution");
  }

  const forward = sub_pairs.filter(
    ([out_id, in_id]) => out_id === player_out && in_id === player_in,
  ).length;
  const reverse = sub_pairs.filter(
    ([out_id, in_id]) => out_id === player_in && in_id === player_out,
  ).length;
  if (forward + reverse >= 2) {
    w.push("this exchange pair has already used its re-entry");
  }
  for (const [out_id, in_id] of sub_pairs) {
    if (player_in === in_id && out_id !== player_out) {
      w.push("substitute already entered for a different player this set");
      break;
    }
    if (player_in === out_id && in_id !== player_out) {
      w.push("player may only re-enter for the substitute who replaced them");
      break;
    }
  }
  return w;
}

/** Warnings for the libero entering the court in place of partner_id. */
export function validate_libero_entry(
  lineup: string[],
  partner_id: string,
  team_is_serving: boolean,
  config: MatchConfig,
): string[] {
  const w: string[] = [];
  if (!lineup.includes(partner_id)) {
    w.push("replaced player is not on court");
    return w;
  }
  const slot = lineup.indexOf(partner_id);
  if (!is_back_row(slot)) {
    w.push("libero may only replace a back-row player");
  }
  if (slot === 0 && team_is_serving && !config.libero_may_serve) {
    w.push("libero may not serve (position P1 while team is serving)");
  }
  return w;
}

export function validate_libero_exit(
  recorded_partner: string, partner_id: string,
): string[] {
  if (recorded_partner !== partner_id) {
    return ["libero must be exchanged back with the player they replaced"];
  }
  return [];
}
