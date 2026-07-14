import { describe, expect, test } from "vitest";

import { MatchEngine } from "../src/core/engine";
import { HOME, AWAY, Role, Rating, TeamKey, default_config, make_player, make_team } from "../src/core/models";
import { serve_xy } from "../src/core/rotation";
import {
  buildCourtTokens,
  displayedPositions,
  nearestPlayerId,
  recentCourtTrajectories,
  serveIsOut,
  trajectoriesExpired,
} from "../src/courtState";

function makeEngine(leftTeam: TeamKey = HOME, servingTeam: TeamKey = HOME): MatchEngine {
  const home = make_team("Home", [
    make_player(1, "Setter", Role.SETTER, "h1"),
    make_player(2, "Outside 1", Role.OUTSIDE, "h2"),
    make_player(3, "Middle 1", Role.MIDDLE, "h3"),
    make_player(4, "Opposite", Role.OPPOSITE, "h4"),
    make_player(5, "Outside 2", Role.OUTSIDE, "h5"),
    make_player(6, "Middle 2", Role.MIDDLE, "h6"),
  ]);
  const away = make_team("Away", [
    make_player(11, "Setter", Role.SETTER, "a1"),
    make_player(12, "Outside 1", Role.OUTSIDE, "a2"),
    make_player(13, "Middle 1", Role.MIDDLE, "a3"),
    make_player(14, "Opposite", Role.OPPOSITE, "a4"),
    make_player(15, "Outside 2", Role.OUTSIDE, "a5"),
    make_player(16, "Middle 2", Role.MIDDLE, "a6"),
  ]);
  const engine = new MatchEngine(default_config(), { home, away });
  engine.append({
    type: "set_start",
    set_number: 1,
    lineups: {
      home: ["h1", "h2", "h3", "h4", "h5", "h6"],
      away: ["a1", "a2", "a3", "a4", "a5", "a6"],
    },
    liberos: { home: [], away: [] },
    serving_team: servingTeam,
    left_team: leftTeam,
  });
  return engine;
}

describe("court state helpers", () => {
  test("uses displayed positions for nearest-player selection", () => {
    const engine = makeEngine();

    const positions = displayedPositions(engine, HOME, true);
    const serverPosition = positions.h1;

    expect(serverPosition).toEqual(serve_xy(engine.side_of(HOME)));
    expect(nearestPlayerId(engine, HOME, serverPosition[0], serverPosition[1], true)).toBe("h1");
    expect(displayedPositions(engine, HOME, false).h1).not.toEqual(serverPosition);
  });

  test("marks the selected player and server in court token specs", () => {
    const engine = makeEngine();

    const tokens = buildCourtTokens(engine, { teamKey: HOME, playerId: "h1" }, true);
    const serverToken = tokens.find((token) => token.playerId === "h1");

    expect(serverToken).toMatchObject({
      teamKey: HOME,
      highlight: true,
      serving: true,
      badge: "S",
    });
  });

  test("detects serve errors based on the opponent court side", () => {
    const leftHome = makeEngine(HOME, HOME);
    const rightHome = makeEngine(AWAY, HOME);

    expect(serveIsOut(leftHome, HOME, 2, 4.5)).toBe(false);
    expect(serveIsOut(leftHome, HOME, -1, 4.5)).toBe(true);
    expect(serveIsOut(rightHome, HOME, -2, 4.5)).toBe(false);
    expect(serveIsOut(rightHome, HOME, 1, 4.5)).toBe(true);
  });

  test("keeps recent trajectories from the current rally", () => {
    const recent = recentCourtTrajectories([
      {
        type: "set_start",
        set_number: 1,
        lineups: {
          home: ["h1", "h2", "h3", "h4", "h5", "h6"],
          away: ["a1", "a2", "a3", "a4", "a5", "a6"],
        },
        liberos: { home: [], away: [] },
        serving_team: HOME,
        left_team: HOME,
      },
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, trajectory: [-10.2, 7.5, 2, 4.5] },
      { type: "reception", team: AWAY, player_id: "a5", rating: Rating.GOOD },
      { type: "attack", team: AWAY, player_id: "a4", rating: Rating.GOOD, trajectory: [3, 7, -5, 3] },
      { type: "dig", team: HOME, player_id: "h6", rating: Rating.GOOD },
      { type: "attack", team: HOME, player_id: "h2", rating: Rating.PERFECT, trajectory: [-4, 2, 7, 2] },
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, trajectory: [-10.2, 7.5, 1, 6] },
    ]);

    expect(recent).toHaveLength(1);
    expect(recent[0]).toMatchObject({
      kind: "serve",
      trajectory: [-10.2, 7.5, 1, 6],
      opacity: 1,
    });
  });

  test("marks trajectories expired only between rallies", () => {
    const engine = makeEngine();

    expect(trajectoriesExpired(engine)).toBe(true); // before the first serve

    engine.append({
      type: "serve", team: HOME, player_id: "h1",
      rating: Rating.GOOD, trajectory: [-10.2, 7.5, 2, 4.5],
    });
    expect(trajectoriesExpired(engine)).toBe(false); // rally underway

    engine.append({ type: "rally_point", team: AWAY, reason: "manual" });
    expect(trajectoriesExpired(engine)).toBe(true); // point scored

    engine.undo();
    expect(trajectoriesExpired(engine)).toBe(false); // undo reopens the rally
  });
});
