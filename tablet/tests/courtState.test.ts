import { describe, expect, test } from "vitest";

import { MatchEngine } from "../src/core/engine";
import { HOME, AWAY, Role, Rating, TeamKey, default_config, make_player, make_team } from "../src/core/models";
import { serve_xy } from "../src/core/rotation";
import {
  LIBERO_TOKEN_COLOR,
  SETTER_TOKEN_COLOR,
  actingSetterId,
  buildCourtTokens,
  displayedPositions,
  nearestPlayerId,
  recentCourtTrajectories,
  serveIsOut,
  teamOnHalf,
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

/** HOME as a 6-2: h1 and h4 are both setters (diagonal by default), so
 * exactly one of them is in the back row and runs the offence. */
function makeSixTwoEngine(homeLineup = ["h1", "h2", "h3", "h4", "h5", "h6"]): MatchEngine {
  const home = make_team("Home", [
    make_player(1, "Setter 1", Role.SETTER, "h1"),
    make_player(2, "Outside 1", Role.OUTSIDE, "h2"),
    make_player(3, "Middle 1", Role.MIDDLE, "h3"),
    make_player(4, "Setter 2", Role.SETTER, "h4"),
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
    lineups: { home: homeLineup, away: ["a1", "a2", "a3", "a4", "a5", "a6"] },
    liberos: { home: [], away: [] },
    serving_team: AWAY,
    left_team: HOME,
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

  test("paints only the acting setter as setter in a 6-2", () => {
    // HOME as a 6-2: setters at P1 (back, acting) and P4 (front, hitting)
    const engine = makeSixTwoEngine();
    expect(actingSetterId(engine, HOME)).toBe("h1");

    const tokens = buildCourtTokens(engine, null, true);
    const acting = tokens.find((t) => t.playerId === "h1")!;
    const hitting = tokens.find((t) => t.playerId === "h4")!;

    expect(acting.color).toBe(SETTER_TOKEN_COLOR);
    expect(hitting.color).toBe(engine.teams.home.color);
    // both keep the S badge: setters by trade, one of them is hitting
    expect(acting.badge).toBe("S");
    expect(hitting.badge).toBe("S");
  });

  test("the blue setter changes hands when the setters swap rows", () => {
    const engine = makeSixTwoEngine();
    engine.append({ type: "rotation_adjust", team: HOME, steps: 3 });
    expect(engine.state.team.home.lineup[0]).toBe("h4");
    expect(actingSetterId(engine, HOME)).toBe("h4");

    const tokens = buildCourtTokens(engine, null, true);
    expect(tokens.find((t) => t.playerId === "h4")!.color).toBe(SETTER_TOKEN_COLOR);
    expect(tokens.find((t) => t.playerId === "h1")!.color).toBe(engine.teams.home.color);
  });

  test("an ambiguous lineup keeps both setters marked", () => {
    // setters at P1 and P5: both back row, acting one undecidable
    const engine = makeSixTwoEngine(["h1", "h2", "h3", "h5", "h4", "h6"]);
    expect(actingSetterId(engine, HOME)).toBeNull();

    const tokens = buildCourtTokens(engine, null, true);
    expect(tokens.find((t) => t.playerId === "h1")!.color).toBe(SETTER_TOKEN_COLOR);
    expect(tokens.find((t) => t.playerId === "h4")!.color).toBe(SETTER_TOKEN_COLOR);
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

  test("teamOnHalf picks the team occupying the drag's starting x", () => {
    const leftHome = makeEngine(HOME, HOME);   // left_team = HOME
    const leftAway = makeEngine(AWAY, HOME);   // left_team = AWAY

    expect(teamOnHalf(leftHome.state, -3)).toBe(HOME);  // negative x -> left half
    expect(teamOnHalf(leftHome.state, 3)).toBe(AWAY);   // positive x -> right half
    expect(teamOnHalf(leftHome.state, 0)).toBe(AWAY);   // boundary -> right team

    expect(teamOnHalf(leftAway.state, -3)).toBe(AWAY);
    expect(teamOnHalf(leftAway.state, 3)).toBe(HOME);
    expect(teamOnHalf(leftAway.state, 0)).toBe(HOME);
  });
});
