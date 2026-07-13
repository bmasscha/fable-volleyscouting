import { describe, expect, test } from "vitest";

import { MatchEngine } from "../src/core/engine";
import { AWAY, HOME, Role, default_config, make_player, make_team } from "../src/core/models";
import {
  benchEntries,
  benchSummary,
  cloneSetStartEvent,
  exchangeEventFor,
  rotateEditedSetLineup,
  validateEditedSetStart,
} from "../src/matchUi";

function makeEngine(): MatchEngine {
  const home = make_team("Home", [
    make_player(1, "Setter", Role.SETTER, "h1"),
    make_player(2, "Outside 1", Role.OUTSIDE, "h2"),
    make_player(3, "Middle 1", Role.MIDDLE, "h3"),
    make_player(4, "Opposite", Role.OPPOSITE, "h4"),
    make_player(5, "Outside 2", Role.OUTSIDE, "h5"),
    make_player(6, "Middle 2", Role.MIDDLE, "h6"),
    make_player(7, "Libero", Role.LIBERO, "h7"),
    make_player(8, "Bench Setter", Role.SETTER, "h8"),
  ], "#2e7d32");
  const away = make_team("Away", [
    make_player(11, "Setter", Role.SETTER, "a1"),
    make_player(12, "Outside 1", Role.OUTSIDE, "a2"),
    make_player(13, "Middle 1", Role.MIDDLE, "a3"),
    make_player(14, "Opposite", Role.OPPOSITE, "a4"),
    make_player(15, "Outside 2", Role.OUTSIDE, "a5"),
    make_player(16, "Middle 2", Role.MIDDLE, "a6"),
    make_player(17, "Libero", Role.LIBERO, "a7"),
    make_player(18, "Bench", Role.UNIVERSAL, "a8"),
  ], "#6a1b9a");
  const engine = new MatchEngine(default_config(), { home, away });
  engine.append({
    type: "set_start",
    set_number: 1,
    lineups: {
      home: ["h1", "h2", "h3", "h4", "h5", "h6"],
      away: ["a1", "a2", "a3", "a4", "a5", "a6"],
    },
    liberos: { home: ["h7"], away: ["a7"] },
    serving_team: HOME,
    left_team: HOME,
  });
  return engine;
}

describe("match UI helpers", () => {
  test("lists off-court bench players with desktop-style summary", () => {
    const engine = makeEngine();
    engine.append({ type: "timeout", team: HOME });
    engine.append({ type: "substitution", team: HOME, player_out: "h2", player_in: "h8" });

    const entries = benchEntries(engine, HOME);

    expect(entries.map((entry) => entry.playerId)).toEqual(["h2", "h7"]);
    expect(entries.find((entry) => entry.playerId === "h7")).toMatchObject({ badge: "L" });
    expect(benchSummary(engine, HOME)).toBe("Subs 1/6 · TO 1/2");
  });

  test("creates substitution and libero exchange events from armed bench taps", () => {
    const engine = makeEngine();
    engine.append({ type: "libero_swap", team: HOME, libero_id: "h7", partner_id: "h5" });

    expect(exchangeEventFor(engine, HOME, "h8", "h2")).toEqual({
      type: "substitution",
      team: HOME,
      player_out: "h2",
      player_in: "h8",
    });
    expect(exchangeEventFor(engine, HOME, "h7", "h5")).toEqual({
      type: "libero_swap",
      team: HOME,
      libero_id: "h7",
      partner_id: "h5",
    });
    expect(exchangeEventFor(engine, HOME, "h5", "h7")).toEqual({
      type: "libero_swap",
      team: HOME,
      libero_id: "h7",
      partner_id: "h5",
    });
  });

  test("rotates and validates edited next-set lineups", () => {
    const draft = cloneSetStartEvent({
      type: "set_start",
      ts: null,
      set_number: 2,
      lineups: {
        home: ["h1", "h2", "h3", "h4", "h5", "h6"],
        away: ["a1", "a2", "a3", "a4", "a5", "a6"],
      },
      liberos: { home: ["h7"], away: ["a7"] },
      serving_team: AWAY,
      left_team: AWAY,
    });
    const engine = makeEngine();

    const rotated = rotateEditedSetLineup(draft, HOME, 1);
    expect(rotated.lineups.home).toEqual(["h2", "h3", "h4", "h5", "h6", "h1"]);
    expect(validateEditedSetStart(rotated, engine.teams)).toBeNull();

    rotated.lineups.home[0] = "h7";
    expect(validateEditedSetStart(rotated, engine.teams)).toBe("Home: starting lineup cannot include registered liberos.");
  });
});
