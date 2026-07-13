import { describe, expect, test } from "vitest";

import {
  AttackEvent,
  ManualScoreEvent,
  MatchEvent as Event,
  RallyPointEvent,
  ReceptionEvent,
  ServeEvent,
  SetStartEvent,
  Trajectory,
} from "../src/core/events";
import {
  AWAY,
  HOME,
  Rating,
  Role,
  Skill,
  Team,
  TeamKey,
  default_config,
  make_player,
  make_team,
} from "../src/core/models";
import {
  TrajectoryStat,
  collect_trajectories,
  filter_trajectories,
  outcome,
  summarize_trajectories,
} from "../src/core/trajectories";

const HOME_IDS = ["h1", "h2", "h3", "h4", "h5", "h6"];
const AWAY_IDS = ["a1", "a2", "a3", "a4", "a5", "a6"];

function teams(): Record<TeamKey, Team> {
  return {
    home: make_team("Home", [1, 2, 3, 4, 5, 6].map((i) => make_player(i, `H${i}`, Role.UNIVERSAL, `h${i}`))),
    away: make_team("Away", [1, 2, 3, 4, 5, 6].map((i) => make_player(i, `A${i}`, Role.UNIVERSAL, `a${i}`))),
  };
}

function set_start(n = 1, serving: TeamKey = HOME, left: TeamKey = HOME): SetStartEvent {
  return {
    type: "set_start",
    set_number: n,
    lineups: { home: [...HOME_IDS], away: [...AWAY_IDS] },
    liberos: { home: [], away: [] },
    serving_team: serving,
    left_team: left,
  };
}

function collect(team_map: Record<TeamKey, Team>, events: Event[]): TrajectoryStat[] {
  return collect_trajectories(default_config(), team_map, events);
}

function mirror(line: Trajectory): Trajectory {
  const [x1, y1, x2, y2] = line;
  return [-x1, 9.0 - y1, -x2, 9.0 - y2];
}

// ------------------------------------------------------------ normalization

describe("trajectories", () => {
  test("test_serve_from_left_side_is_unchanged", () => {
    const team_map = teams();
    const line: Trajectory = [-10.2, 7.5, 5.0, 3.0];
    const stats = collect(team_map, [
      set_start(1, HOME, HOME),
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, trajectory: line } satisfies ServeEvent,
    ]);
    expect(stats).toHaveLength(1);
    const t = stats[0]!;
    expect([t.team, t.player_id, t.skill, t.rating, t.set_number]).toEqual(
      [HOME, "h1", Skill.SERVE, Rating.GOOD, 1],
    );
    expect(t.line).toEqual(line);
  });

  test("test_serve_from_right_side_is_mirrored", () => {
    const team_map = teams();
    const canonical: Trajectory = [-10.2, 7.5, 5.0, 3.0];
    const stats = collect(team_map, [
      set_start(1, AWAY, HOME), // away plays RIGHT
      { type: "serve", team: AWAY, player_id: "a1", rating: Rating.GOOD, trajectory: mirror(canonical) } satisfies ServeEvent,
    ]);
    expect(stats[0]!.line).toEqual(canonical);
  });

  test("test_attack_from_right_side_is_mirrored", () => {
    const team_map = teams();
    const canonical: Trajectory = [-2.0, 5.0, 7.0, 1.0];
    const stats = collect(team_map, [
      set_start(1, HOME, HOME),
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, trajectory: [-10.2, 7.5, 5.0, 3.0] } satisfies ServeEvent,
      { type: "reception", team: AWAY, player_id: "a5", rating: Rating.GOOD } satisfies ReceptionEvent,
      { type: "attack", team: AWAY, player_id: "a2", rating: Rating.PERFECT, trajectory: mirror(canonical) } satisfies AttackEvent,
    ]);
    const attacks = stats.filter((t) => t.skill === Skill.ATTACK);
    expect(attacks).toHaveLength(1);
    expect(attacks[0]!.line).toEqual(canonical);
    expect(attacks[0]!.rating).toBe(Rating.PERFECT);
  });

  test("test_events_without_trajectory_are_skipped", () => {
    const team_map = teams();
    const stats = collect(team_map, [
      set_start(1, HOME, HOME),
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, trajectory: [-10.2, 7.5, 5.0, 3.0] } satisfies ServeEvent,
      { type: "reception", team: AWAY, player_id: "a5", rating: Rating.GOOD } satisfies ReceptionEvent,
      { type: "attack", team: AWAY, player_id: "a2", rating: Rating.PERFECT, trajectory: null } satisfies AttackEvent, // rated without drag
    ]);
    expect(stats.map((t) => t.skill)).toEqual([Skill.SERVE]);
  });

  test("test_side_switch_between_sets", () => {
    /** Same team, same real-world direction of play flips between sets;
     * both serves must normalize to the identical canonical line. */
    const team_map = teams();
    const canonical: Trajectory = [-10.2, 7.5, 5.0, 3.0];
    const stats = collect(team_map, [
      set_start(1, HOME, HOME),
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, trajectory: canonical } satisfies ServeEvent,
      { type: "manual_score", team: HOME, delta: 25 } satisfies ManualScoreEvent, // home wins set 1
      set_start(2, AWAY, AWAY), // sides switch
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, trajectory: mirror(canonical) } satisfies ServeEvent,
    ]);
    expect(stats).toHaveLength(2);
    expect(stats[0]!.line).toEqual(canonical);
    expect(stats[1]!.line).toEqual(canonical);
    expect([stats[0]!.set_number, stats[1]!.set_number]).toEqual([1, 2]);
  });

  test("test_deciding_set_mid_set_switch", () => {
    /** The ace that brings the leading team to 8 in the deciding set is
     * still normalized with the pre-switch side; the next serve (after the
     * teams walked around) is mirrored. */
    const team_map = teams();
    const canonical: Trajectory = [-10.2, 7.5, 5.0, 3.0];
    const events: Event[] = [];
    // sets 1-4: alternate winners to force a deciding 5th set
    for (const [idx, winner] of ([HOME, AWAY, HOME, AWAY] as const).entries()) {
      events.push(set_start(idx + 1, HOME, HOME));
      events.push({ type: "manual_score", team: winner, delta: 25 } satisfies ManualScoreEvent);
    }
    events.push(set_start(5, HOME, HOME));
    for (let i = 0; i < 7; i += 1) { // 7-0 home
      events.push({ type: "rally_point", team: HOME } satisfies RallyPointEvent);
    }
    // ace -> 8-0: triggers the mid-set side switch AFTER this serve
    events.push({ type: "serve", team: HOME, player_id: "h1", rating: Rating.PERFECT, trajectory: canonical } satisfies ServeEvent);
    // home now plays RIGHT and keeps the serve
    events.push({ type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, trajectory: mirror(canonical) } satisfies ServeEvent);
    const stats = collect(team_map, events);
    expect(stats).toHaveLength(2);
    expect(stats[0]!.line).toEqual(canonical);
    expect(stats[1]!.line).toEqual(canonical);
    expect(stats[0]!.rating).toBe(Rating.PERFECT);
  });

  // ------------------------------------------------------------ outcome class

  test("test_outcome_classification", () => {
    expect(outcome(Rating.ERROR)).toBe("error");
    expect(outcome(Rating.PERFECT)).toBe("point");
    expect(outcome(Rating.GOOD)).toBe("neutral");
    expect(outcome(Rating.POOR)).toBe("neutral");
  });

  test("test_filter_trajectories_by_team_player_set_and_skill", () => {
    const team_map = teams();
    const stats = collect(team_map, [
      set_start(1, HOME, HOME),
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, trajectory: [-10.2, 7.5, 5.0, 3.0] } satisfies ServeEvent,
      { type: "reception", team: AWAY, player_id: "a5", rating: Rating.GOOD } satisfies ReceptionEvent,
      { type: "attack", team: AWAY, player_id: "a2", rating: Rating.PERFECT, trajectory: mirror([-2.0, 5.0, 7.0, 1.0]) } satisfies AttackEvent,
      set_start(2, HOME, AWAY),
      { type: "serve", team: AWAY, player_id: "a1", rating: Rating.ERROR, trajectory: mirror([-10.2, 7.5, 5.0, 3.0]) } satisfies ServeEvent,
    ]);

    expect(filter_trajectories(stats, { team: HOME }).map((stat) => stat.player_id)).toEqual(["h1"]);
    expect(filter_trajectories(stats, { player_id: "a2", skill: Skill.ATTACK }).map((stat) => stat.rating)).toEqual([Rating.PERFECT]);
    expect(filter_trajectories(stats, { set_number: 2 }).map((stat) => stat.player_id)).toEqual(["a1"]);
  });

  test("test_summarize_trajectories_counts_points_and_errors", () => {
    const stats: TrajectoryStat[] = [
      { team: HOME, player_id: "h1", skill: Skill.SERVE, rating: Rating.PERFECT, set_number: 1, line: [-1, 1, 1, 1] },
      { team: HOME, player_id: "h1", skill: Skill.SERVE, rating: Rating.ERROR, set_number: 1, line: [-1, 2, 1, 2] },
      { team: HOME, player_id: "h1", skill: Skill.SERVE, rating: Rating.GOOD, set_number: 1, line: [-1, 3, 1, 3] },
    ];

    expect(summarize_trajectories(stats)).toEqual({ total: 3, points: 1, errors: 1 });
  });
});
