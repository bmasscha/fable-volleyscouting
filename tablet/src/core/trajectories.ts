/** Per-player serve / attack trajectory charts.
 *
 * Trajectories are stored on ServeEvent / AttackEvent exactly as drawn, in
 * absolute court coordinates -- but teams switch sides between sets (and at
 * 8 points in the deciding set), so raw lines from different sets point in
 * opposite directions. This module replays the event log through the engine
 * to know which side the acting team occupied at each touch and mirrors
 * everything to one canonical orientation: the acting team always plays
 * LEFT -> RIGHT. That makes all of a player's serves (or attacks) directly
 * comparable on a single chart.
 */
import { MatchEngine } from "./engine";
import { MatchEvent as Event, Trajectory } from "./events";
import { MatchConfig, Rating, Skill, Team, TeamKey } from "./models";
import { to_side } from "./rotation";

export interface TrajectoryStat {
  team: TeamKey;
  player_id: string;
  skill: Skill; // SERVE or ATTACK
  rating: Rating;
  set_number: number;
  line: Trajectory; // normalized: acting team plays LEFT -> RIGHT
  // block deflection vertex (attacks only), normalized like `line`
  block_touch?: [number, number] | null;
}

export interface TrajectoryFilter {
  team?: TeamKey | null;
  player_id?: string | null;
  set_number?: number | null;
  skill?: Skill | null;
}

export interface TrajectorySummary {
  total: number;
  points: number;
  errors: number;
}

/** Display class of a trajectory: 'error' (fault -> red),
 * 'point' (ace / kill -> green) or 'neutral' (in play -> white). */
export function outcome(rating: Rating): "error" | "point" | "neutral" {
  if (rating === Rating.ERROR) {
    return "error";
  }
  if (rating === Rating.PERFECT) {
    return "point";
  }
  return "neutral";
}

/** Mirror a line drawn while the acting team was on `side` so the
 * team always plays LEFT -> RIGHT (to_side is its own inverse). */
function _normalize(line: Trajectory, side: string): Trajectory {
  const [x1, y1] = to_side(line[0], line[1], side);
  const [x2, y2] = to_side(line[2], line[3], side);
  return [x1, y1, x2, y2];
}

/** Replay `events` and return every recorded serve / attack trajectory
 * in canonical orientation, in match order. */
export function collect_trajectories(config: MatchConfig, teams: Record<TeamKey, Team>,
  events: Event[]): TrajectoryStat[] {
  const engine = new MatchEngine(config, teams);
  const out: TrajectoryStat[] = [];
  for (const e of events) {
    if ((e.type === "serve" || e.type === "attack") && e.trajectory) {
      // side must be read BEFORE applying the event: an ace or fault
      // in the deciding set can trigger the mid-set side switch
      const side = engine.side_of(e.team);
      const skill = e.type === "serve" ? Skill.SERVE : Skill.ATTACK;
      const touch = e.type === "attack" ? e.block_touch : null;
      out.push({
        team: e.team,
        player_id: e.player_id,
        skill,
        rating: e.rating,
        set_number: engine.state.set_number,
        line: _normalize(e.trajectory, side),
        block_touch: touch != null ? to_side(touch[0], touch[1], side) : null,
      });
    }
    engine.append(e);
  }
  return out;
}

export function filter_trajectories(
  stats: TrajectoryStat[],
  filter: TrajectoryFilter,
): TrajectoryStat[] {
  return stats.filter((stat) => (
    (filter.team == null || stat.team === filter.team)
    && (filter.player_id == null || stat.player_id === filter.player_id)
    && (filter.set_number == null || stat.set_number === filter.set_number)
    && (filter.skill == null || stat.skill === filter.skill)
  ));
}

export function summarize_trajectories(stats: TrajectoryStat[]): TrajectorySummary {
  const summary: TrajectorySummary = { total: stats.length, points: 0, errors: 0 };
  for (const stat of stats) {
    const group = outcome(stat.rating);
    if (group === "point") {
      summary.points += 1;
    } else if (group === "error") {
      summary.errors += 1;
    }
  }
  return summary;
}
