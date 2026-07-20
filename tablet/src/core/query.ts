/** Flatten the event log into a queryable list of player *actions* and filter
 * it -- the selection engine behind the video-review tool ("all attacks by #12
 * Away", "all serve-receive by the Home libero", "all failed serves by #7").
 *
 * Mirrors core/query.py (see TRANSLATION.md). No engine dependency: set/rally
 * context is derived in a single pass. */

import { MatchEvent } from "./events";
import { Rating, Role, Skill, Team, TeamKey, team_player } from "./models";

// The four skill events that carry a player_id and become actions.
const EVENT_SKILL: Partial<Record<MatchEvent["type"], Skill>> = {
  serve: Skill.SERVE,
  reception: Skill.RECEPTION,
  attack: Skill.ATTACK,
  dig: Skill.DIG,
};

export interface Action {
  index: number;                 // position in the source event list
  ts: number | null;             // wall-clock unix seconds (for video sync)
  set_number: number;
  rally_index: number;           // 1-based within the set; 0 before first serve
  team_key: TeamKey;
  player_id: string;
  player_number: number | null;  // null if the player is not on the roster
  player_name: string;
  role: Role | null;
  skill: Skill;
  rating: Rating;
  overpass: boolean;
  block_touch: [number, number] | null;
  trajectory: [number, number, number, number] | null;
}

// A skill event, once EVENT_SKILL has confirmed its type carries these fields.
type SkillEvent = Extract<
  MatchEvent,
  { team: TeamKey; player_id: string; rating: Rating }
>;

/** Walk the event log once, emitting an Action per skill event with its
 * set/rally/player context resolved. Non-skill events are context only. */
export function build_actions(
  events: MatchEvent[],
  teams: Record<TeamKey, Team>,
): Action[] {
  const actions: Action[] = [];
  let set_number = 0;
  let rally_index = 0;
  events.forEach((e, index) => {
    if (e.type === "set_start") {
      set_number = e.set_number;
      rally_index = 0;
      return;
    }
    if (e.type === "serve") {
      rally_index += 1;
    }
    const skill = EVENT_SKILL[e.type];
    if (skill == null) {
      return;
    }
    const ev = e as SkillEvent;
    const team = teams[ev.team] ?? null;
    const player = team != null ? team_player(team, ev.player_id) : null;
    actions.push({
      index,
      ts: e.ts ?? null,
      set_number,
      rally_index,
      team_key: ev.team,
      player_id: ev.player_id,
      player_number: player != null ? player.number : null,
      player_name: player != null ? player.name : "",
      role: player != null ? player.role : null,
      skill,
      rating: ev.rating,
      overpass: (ev as { overpass?: boolean }).overpass ?? false,
      block_touch: (ev as { block_touch?: [number, number] | null }).block_touch ?? null,
      trajectory:
        (ev as { trajectory?: [number, number, number, number] | null }).trajectory ?? null,
    });
  });
  return actions;
}

/** A selection over the action list. Every field is optional; an omitted/null
 * field does not constrain. All present fields must match (logical AND). */
export interface ActionFilter {
  team_key?: TeamKey | null;   // HOME / AWAY, or null = either team
  player_id?: string | null;
  player_number?: number | null;
  role?: Role | null;          // e.g. Role.LIBERO -> "the libero"
  skill?: Skill | null;
  rating?: Rating | null;      // null = any rating
  set_number?: number | null;
}

export function action_matches(spec: ActionFilter, a: Action): boolean {
  if (spec.team_key != null && a.team_key !== spec.team_key) return false;
  if (spec.player_id != null && a.player_id !== spec.player_id) return false;
  if (spec.player_number != null && a.player_number !== spec.player_number) return false;
  if (spec.role != null && a.role !== spec.role) return false;
  if (spec.skill != null && a.skill !== spec.skill) return false;
  if (spec.rating != null && a.rating !== spec.rating) return false;
  if (spec.set_number != null && a.set_number !== spec.set_number) return false;
  return true;
}

/** Actions matching `spec`, ordered by timestamp (ties and timestamp-less
 * actions keep their original event order). */
export function filter_actions(actions: Action[], spec: ActionFilter): Action[] {
  const matched = actions.filter((a) => action_matches(spec, a));
  matched.sort((x, y) => {
    const xNull = x.ts == null;
    const yNull = y.ts == null;
    if (xNull !== yNull) return xNull ? 1 : -1;
    const xt = x.ts ?? 0;
    const yt = y.ts ?? 0;
    if (xt !== yt) return xt - yt;
    return x.index - y.index;
  });
  return matched;
}
