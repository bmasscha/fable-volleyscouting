import { describe, expect, test } from "vitest";

import { AttackEvent, DigEvent, ManualScoreEvent, MatchEvent, RallyPointEvent, ReceptionEvent, ServeEvent } from "../src/core/events";
import { AWAY, HOME, Rating, Role, Skill, Team, TeamKey, make_player, make_team } from "../src/core/models";
import { ACES, KILLS, MANUAL_OTHER, OPPONENT_ERRORS, SkillLine, compute_stats, export_csv, export_html } from "../src/core/stats";

function parse_csv(text: string): string[][] {
  return text
    .split(/\r?\n/)
    .filter((line) => line !== "")
    .map((line) => line.split(","));
}

function teams(): Record<TeamKey, Team> {
  const alice = make_player(1, "Alice", Role.OUTSIDE, "p_alice");
  const bob = make_player(9, "Bob", Role.OPPOSITE, "p_bob");
  const carol = make_player(7, "Carol", Role.LIBERO, "p_carol");
  return {
    [HOME]: make_team("Home Hawks", [alice, bob]),
    [AWAY]: make_team("Away Owls", [carol]),
  };
}

function events(): MatchEvent[] {
  return [
    // Alice serves: one ace, one error, one good.
    { type: "serve", team: HOME, player_id: "p_alice", rating: Rating.PERFECT } satisfies ServeEvent,
    { type: "serve", team: HOME, player_id: "p_alice", rating: Rating.ERROR } satisfies ServeEvent,
    { type: "serve", team: HOME, player_id: "p_alice", rating: Rating.GOOD } satisfies ServeEvent,
    // Bob attacks: one kill, one poor.
    { type: "attack", team: HOME, player_id: "p_bob", rating: Rating.PERFECT } satisfies AttackEvent,
    { type: "attack", team: HOME, player_id: "p_bob", rating: Rating.POOR } satisfies AttackEvent,
    // Carol (away): reception error (-> home point), a good dig.
    { type: "reception", team: AWAY, player_id: "p_carol", rating: Rating.ERROR } satisfies ReceptionEvent,
    { type: "dig", team: AWAY, player_id: "p_carol", rating: Rating.GOOD } satisfies DigEvent,
    // Manual events.
    { type: "rally_point", team: HOME, reason: "net fault" } satisfies RallyPointEvent,
    { type: "manual_score", team: AWAY, delta: 2 } satisfies ManualScoreEvent,
    { type: "manual_score", team: AWAY, delta: -1 } satisfies ManualScoreEvent,
    // Unknown player: must be skipped gracefully.
    { type: "serve", team: HOME, player_id: "p_ghost", rating: Rating.PERFECT } satisfies ServeEvent,
  ];
}

function stats() {
  return compute_stats(events(), teams());
}

// ------------------------------------------------------------- SkillLine

describe("stats", () => {
  test("test_skill_line_empty_is_all_zero", () => {
    const line = SkillLine();
    expect(line.total).toBe(0);
    expect(line.pct(Rating.PERFECT)).toBe(0.0);
    expect(line.efficiency).toBe(0.0);
    expect(line.positive_pct).toBe(0.0);
  });

  test("test_skill_line_math", () => {
    const line = SkillLine();
    for (const rating of [Rating.PERFECT, Rating.PERFECT, Rating.ERROR, Rating.GOOD]) {
      line.add(rating);
    }
    expect(line.total).toBe(4);
    expect(line.pct(Rating.PERFECT)).toBeCloseTo(50.0);
    expect(line.efficiency).toBeCloseTo((2 - 1) / 4 * 100);
    expect(line.positive_pct).toBeCloseTo((2 + 1) / 4 * 100);
  });

  // ---------------------------------------------------------- compute_stats

  test("test_player_serve_counts", () => {
    const serve = stats()[HOME].players.p_alice.line(Skill.SERVE);
    expect(serve.total).toBe(3);
    expect(serve.count(Rating.PERFECT)).toBe(1);
    expect(serve.count(Rating.ERROR)).toBe(1);
    expect(serve.count(Rating.GOOD)).toBe(1);
    expect(serve.count(Rating.POOR)).toBe(0);
    expect(serve.pct(Rating.PERFECT)).toBeCloseTo(100 / 3);
    expect(serve.efficiency).toBeCloseTo(0.0);
    expect(serve.positive_pct).toBeCloseTo(200 / 3);
  });

  test("test_player_points", () => {
    const team_stats = stats();
    expect(team_stats[HOME].players.p_alice.points).toBe(1); // one ace
    expect(team_stats[HOME].players.p_bob.points).toBe(1); // one kill
    expect(team_stats[AWAY].players.p_carol.points).toBe(0);
  });

  test("test_team_totals_skip_unknown_player", () => {
    const team_stats = stats();
    // The p_ghost ace must not be counted anywhere.
    expect(team_stats[HOME].totals[Skill.SERVE].total).toBe(3);
    expect(team_stats[HOME].totals[Skill.SERVE].count(Rating.PERFECT)).toBe(1);
    expect(team_stats[HOME].totals[Skill.ATTACK].total).toBe(2);
    expect(team_stats[AWAY].totals[Skill.RECEPTION].total).toBe(1);
    expect(team_stats[AWAY].totals[Skill.DIG].count(Rating.GOOD)).toBe(1);
  });

  test("test_points_breakdown_home", () => {
    const bd = stats()[HOME].points_breakdown;
    expect(bd[ACES]).toBe(1);
    expect(bd[KILLS]).toBe(1);
    expect(bd[OPPONENT_ERRORS]).toBe(1); // Carol's reception error
    expect(bd[MANUAL_OTHER]).toBe(1); // one rally point, no score deltas
    expect(stats()[HOME].total_points).toBe(4);
  });

  test("test_points_breakdown_away", () => {
    const bd = stats()[AWAY].points_breakdown;
    expect(bd[ACES]).toBe(0);
    expect(bd[KILLS]).toBe(0);
    expect(bd[OPPONENT_ERRORS]).toBe(1); // Alice's serve error
    expect(bd[MANUAL_OTHER]).toBe(1); // net manual delta +2 - 1
    expect(stats()[AWAY].total_points).toBe(2);
  });

  test("test_no_events_gives_zeroed_stats", () => {
    const team_stats = compute_stats([], teams());
    expect(team_stats[HOME].total_points).toBe(0);
    expect(team_stats[HOME].players.p_alice.points).toBe(0);
    expect(team_stats[AWAY].totals[Skill.DIG].total).toBe(0);
  });

  // -------------------------------------------------------------- export_csv

  test("test_export_csv", () => {
    const team_map = teams();
    const rows = parse_csv(export_csv(stats(), team_map));

    const header = rows[0]!;
    expect(header.slice(0, 4)).toEqual(["team", "number", "name", "role"]);
    expect(header).toContain("serve_total");
    expect(header).toContain("dig_eff_pct");
    expect(header.at(-1)).toBe("points");
    // 3 players + 2 team-total rows.
    expect(rows).toHaveLength(1 + 5);

    const alice = rows[1]!;
    expect(alice.slice(0, 4)).toEqual(["Home Hawks", "1", "Alice", "outside"]);
    const i = header.indexOf("serve_total");
    expect(alice.slice(i, i + 6)).toEqual(["3", "1", "0", "1", "1", "0.0"]);
    expect(alice.at(-1)).toBe("1");

    const home_total = rows[3]!;
    expect(home_total[2]).toBe("TEAM TOTAL");
    expect(home_total[i]).toBe("3");
    const j = header.indexOf("attack_total");
    expect(home_total.slice(j, j + 6)).toEqual(["2", "0", "1", "0", "1", "50.0"]);
    expect(home_total.at(-1)).toBe("4");

    const away_total = rows[5]!;
    expect(away_total[0]).toBe("Away Owls");
    expect(away_total.at(-1)).toBe("2");
  });

  // ------------------------------------------------------------- export_html

  test("test_export_html", () => {
    const text = export_html(stats(), teams());

    expect(text.trimStart().startsWith("<!DOCTYPE html>")).toBe(true);
    for (const name of ["Alice", "Bob", "Carol", "Home Hawks", "Away Owls"]) {
      expect(text).toContain(name);
    }
    expect(text).toContain("TEAM TOTAL");
    expect(text).toContain("aces 1"); // home breakdown
    expect(text).toContain("opponent errors 1");
    expect(text).toContain("manual/other 1");
  });

  test("test_export_html_escapes_names", () => {
    const team_map = teams();
    team_map[HOME].players[0]!.name = "A<script>lice";
    const team_stats = compute_stats([], team_map);
    const text = export_html(team_stats, team_map);
    expect(text).not.toContain("<script>");
    expect(text).toContain("A&lt;script&gt;lice");
  });
});
