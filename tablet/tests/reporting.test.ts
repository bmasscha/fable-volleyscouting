import { describe, expect, test } from "vitest";

import { ReportPlayerRow, REPORT_SORT_KEY, buildReportSections, sortReportRows } from "../src/core/reporting";
import { AttackEvent, MatchEvent, ServeEvent } from "../src/core/events";
import { AWAY, HOME, Rating, Role, Skill, Team, TeamKey, make_player, make_team } from "../src/core/models";
import { compute_stats } from "../src/core/stats";

function teams(): Record<TeamKey, Team> {
  return {
    [HOME]: make_team("Home", [
      make_player(1, "Alice", Role.OUTSIDE, "home-1"),
      make_player(8, "Bea", Role.SETTER, "home-8"),
    ]),
    [AWAY]: make_team("Away", [
      make_player(4, "Zoe", Role.OPPOSITE, "away-4"),
    ]),
  };
}

function events(): MatchEvent[] {
  return [
    { type: "serve", team: HOME, player_id: "home-1", rating: Rating.PERFECT } satisfies ServeEvent,
    { type: "attack", team: HOME, player_id: "home-8", rating: Rating.GOOD } satisfies AttackEvent,
  ];
}

describe("reporting helpers", () => {
  test("buildReportSections keeps roster rows and active rows separate", () => {
    const sections = buildReportSections(compute_stats(events(), teams()), teams());
    const home = sections.find((section) => section.teamKey === HOME)!;
    const away = sections.find((section) => section.teamKey === AWAY)!;

    expect(home.rows.map((row) => row.name)).toEqual(["Alice", "Bea"]);
    expect(home.activeRows.map((row) => row.name)).toEqual(["Alice", "Bea"]);
    expect(away.rows.map((row) => row.name)).toEqual(["Zoe"]);
    expect(away.activeRows).toHaveLength(0);
    expect(home.totalRow.name).toBe("TEAM TOTAL");
    expect(home.totalRow.skills[Skill.SERVE].count(Rating.PERFECT)).toBe(1);
  });

  test("sortReportRows sorts by requested metric", () => {
    const rows = buildReportSections(compute_stats(events(), teams()), teams())
      .find((section) => section.teamKey === HOME)!.rows;

    expect(sortReportRows(rows, REPORT_SORT_KEY.NUMBER).map((row) => row.number)).toEqual([1, 8]);
    expect(sortReportRows(rows, REPORT_SORT_KEY.POINTS, true).map((row) => row.name)).toEqual(["Alice", "Bea"]);
  });

  test("sortReportRows handles placeholder total-like rows", () => {
    const [row] = buildReportSections(compute_stats([], teams()), teams())
      .find((section) => section.teamKey === AWAY)!.rows;
    const totalLike: ReportPlayerRow = {
      ...row,
      playerId: null,
      number: null,
      name: "TEAM TOTAL",
    };

    expect(sortReportRows([row, totalLike], REPORT_SORT_KEY.NUMBER).map((entry) => entry.name)).toEqual(["Zoe", "TEAM TOTAL"]);
  });
});
