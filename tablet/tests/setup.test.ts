import { describe, expect, test } from "vitest";

import { AWAY, HOME, Role, make_player, make_team } from "../src/core/models";
import {
  buildMatchSetupResult,
  createSeedRosterLibrary,
  makeMatchSetupDraft,
  normalizedBoundedInteger,
  prepareTeamForSave,
} from "../src/setup";

describe("match setup draft", () => {
  test("defaults to distinct home and away teams", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);

    expect(draft.homeTeamName).toBe("Home");
    expect(draft.awayTeamName).toBe("Away");
    expect(draft.lineups[HOME]).toHaveLength(6);
    expect(draft.lineups[HOME]).not.toContain("home-07");
    expect(draft.liberos[HOME]).toContain("home-07");
    expect(draft.systems).toEqual({ [HOME]: "5-1", [AWAY]: "5-1" });
  });

  test("rebuilding once the roster library loads still designates the liberos", () => {
    // App builds a draft on mount while rosterLibrary is still empty, then
    // rebuilds it when the stored library lands. The libero designation has
    // to survive that: without it nothing is registered as libero and the
    // automatic exchange never runs.
    const library = createSeedRosterLibrary();
    const beforeLibrary = makeMatchSetupDraft([], null);
    expect(beforeLibrary.liberos[HOME]).toEqual([]);

    const draft = makeMatchSetupDraft(library, beforeLibrary);

    expect(draft.liberos[HOME]).toContain("home-07");
    expect(draft.liberos[AWAY]).toContain("away-07");
  });

  test("keeps an explicit libero selection when the team is unchanged", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    draft.liberos[HOME] = [];

    const rebuilt = makeMatchSetupDraft(library, draft);

    expect(rebuilt.liberos[HOME]).toEqual([]);
  });

  test("designates the liberos of the team a dropped selection falls back to", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    expect(draft.liberos[HOME]).toEqual(["home-07", "home-12"]);

    // "Home" is gone from the library, so the draft resolves to another team
    const withoutHome = library.filter((team) => team.name !== "Home");
    const rebuilt = makeMatchSetupDraft(withoutHome, draft);

    expect(rebuilt.homeTeamName).toBe("Away");
    expect(rebuilt.liberos[HOME]).toEqual(["away-07", "away-12"]);
  });
});

describe("team editor validation", () => {
  test("rejects duplicate jersey numbers", () => {
    const library = createSeedRosterLibrary();
    const duplicate = make_team("Scratch", [
      make_player(1, "A"),
      make_player(1, "B"),
    ]);

    const result = prepareTeamForSave(duplicate, library, null);

    expect(result.team).toBeNull();
    expect(result.error).toContain("used more than once");
  });

  test("normalizes jersey numbers to bounded integers", () => {
    const library = createSeedRosterLibrary();
    const draft = make_team("Scratch", [
      make_player(7.8, "A"),
      make_player(12.2, "B"),
    ]);

    const result = prepareTeamForSave(draft, library, null);

    expect(result.error).toBeNull();
    expect(result.team?.players.map((player) => player.number)).toEqual([7, 12]);
  });
});

describe("buildMatchSetupResult", () => {
  test("rejects identical home and away teams", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    draft.awayTeamName = draft.homeTeamName;

    const result = buildMatchSetupResult(draft, library);

    expect(result.result).toBeNull();
    expect(result.error).toContain("different teams");
  });

  test("rejects duplicate starters", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    draft.lineups[HOME] = Array.from({ length: 6 }, () => draft.lineups[HOME][0]!);

    const result = buildMatchSetupResult(draft, library);

    expect(result.result).toBeNull();
    expect(result.error).toContain("only once");
  });

  test("rejects libero in the starting lineup", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    draft.lineups[HOME][0] = "home-07";

    const result = buildMatchSetupResult(draft, library);

    expect(result.result).toBeNull();
    expect(result.error).toContain("libero");
  });

  test("builds a valid config and set start event", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    draft.servingTeam = AWAY;
    draft.leftTeam = AWAY;
    draft.setsToWin = 2;
    draft.pointsPerSet = 21;
    draft.pointsDecidingSet = 15;
    draft.subsPerSet = 12;
    draft.liberoMayServe = true;

    const result = buildMatchSetupResult(draft, library);

    expect(result.error).toBeNull();
    expect(result.result).not.toBeNull();
    expect(result.result!.config).toMatchObject({
      sets_to_win: 2,
      points_per_set: 21,
      points_deciding_set: 15,
      subs_per_set: 12,
      libero_may_serve: true,
    });
    expect(result.result!.setStartEvent).toMatchObject({
      type: "set_start",
      set_number: 1,
      serving_team: AWAY,
      left_team: AWAY,
    });
    expect(result.result!.setStartEvent.lineups[HOME]).toHaveLength(6);
  });

  test("defaults to switching sides between sets", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    expect(draft.switchSides).toBe(true);

    const result = buildMatchSetupResult(draft, library);

    expect(result.result!.switchSides).toBe(true);
    expect(result.result!.config.deciding_set_switch_at).toBe(8);
  });

  test("fixed courts disable the deciding-set mid-set switch", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    draft.switchSides = false;

    const result = buildMatchSetupResult(draft, library);

    expect(result.error).toBeNull();
    expect(result.result!.switchSides).toBe(false);
    // the engine flips sides when the leading team reaches this score;
    // out-of-reach means it never fires
    expect(result.result!.config.deciding_set_switch_at)
      .toBeGreaterThan(result.result!.config.points_deciding_set);
  });

  test("a rebuilt draft keeps the fixed-courts choice", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    draft.switchSides = false;

    const rebuilt = makeMatchSetupDraft(library, draft);

    expect(rebuilt.switchSides).toBe(false);
  });

  test("carries the selected playing systems into the config", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    draft.systems = { [HOME]: "6-2", [AWAY]: "6-6" };

    const result = buildMatchSetupResult(draft, library);

    expect(result.error).toBeNull();
    expect(result.result!.config.systems).toEqual({ [HOME]: "6-2", [AWAY]: "6-6" });
  });

  test("normalizes numeric setup fields to integers", () => {
    const library = createSeedRosterLibrary();
    const draft = makeMatchSetupDraft(library);
    draft.pointsPerSet = 21.9;
    draft.pointsDecidingSet = 15.2;
    draft.subsPerSet = 6.7;

    const result = buildMatchSetupResult(draft, library);

    expect(result.error).toBeNull();
    expect(result.result?.config.points_per_set).toBe(21);
    expect(result.result?.config.points_deciding_set).toBe(15);
    expect(result.result?.config.subs_per_set).toBe(6);
  });

  test("normalizes helper values to bounded integers", () => {
    expect(normalizedBoundedInteger(7.9, 0, 99)).toBe(7);
    expect(normalizedBoundedInteger(Number.POSITIVE_INFINITY, 5, 99)).toBe(5);
  });

  test("keeps blank slots when a roster lacks six starters", () => {
    const shortLibrary = [
      make_team("Home", [
        make_player(1, "Setter", Role.SETTER, "h1"),
        make_player(2, "Outside", Role.OUTSIDE, "h2"),
        make_player(3, "Middle", Role.MIDDLE, "h3"),
      ]),
      make_team("Away", [
        make_player(11, "Setter", Role.SETTER, "a1"),
        make_player(12, "Outside", Role.OUTSIDE, "a2"),
        make_player(13, "Middle", Role.MIDDLE, "a3"),
        make_player(14, "Opposite", Role.OPPOSITE, "a4"),
        make_player(15, "Outside 2", Role.OUTSIDE, "a5"),
        make_player(16, "Middle 2", Role.MIDDLE, "a6"),
      ]),
    ];
    const draft = makeMatchSetupDraft(shortLibrary);

    const result = buildMatchSetupResult(draft, shortLibrary);

    expect(result.result).toBeNull();
    expect(result.error).toContain("assign a player");
  });
});
