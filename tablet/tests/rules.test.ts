import { describe, expect, test } from "vitest";

import { MatchConfig, default_config } from "../src/core/models";
import * as rules from "../src/core/rules";

function config(): MatchConfig {
  return default_config(); // FIVB defaults: best of 5, 25/15, lead 2, 6 subs
}

// ---------------------------------------------------------- deciding set

describe("TestIsDecidingSet", () => {
  test.each([
    [1, false], [2, false], [3, false], [4, false], [5, true], [6, false],
  ])("test_best_of_five(%i, %s)", (set_number, expected) => {
    expect(rules.is_deciding_set(config(), set_number)).toBe(expected);
  });

  test.each([
    [1, false], [2, false], [3, true],
  ])("test_best_of_three(%i, %s)", (set_number, expected) => {
    const cfg: MatchConfig = { ...default_config(), sets_to_win: 2 };
    expect(rules.is_deciding_set(cfg, set_number)).toBe(expected);
  });

  test("test_single_set_match", () => {
    const cfg: MatchConfig = { ...default_config(), sets_to_win: 1 };
    expect(rules.is_deciding_set(cfg, 1)).toBe(true);
  });
});

describe("TestSetTarget", () => {
  test.each([1, 2, 3, 4])("test_regular_sets_go_to_25(%i)", (set_number) => {
    expect(rules.set_target(config(), set_number)).toBe(25);
  });

  test("test_deciding_set_goes_to_15", () => {
    expect(rules.set_target(config(), 5)).toBe(15);
  });

  test("test_configurable_targets", () => {
    const cfg: MatchConfig = {
      ...default_config(),
      sets_to_win: 2,
      points_per_set: 21,
      points_deciding_set: 11,
    };
    expect(rules.set_target(cfg, 1)).toBe(21);
    expect(rules.set_target(cfg, 3)).toBe(11);
  });
});

// ------------------------------------------------------------ set winner

describe("TestSetWinner", () => {
  test.each<[number, number, number, 0 | 1 | null]>([
    // regular set to 25, 2-point lead
    [1, 0, 0, null],
    [1, 24, 0, null], // one short of target
    [1, 25, 0, 0],
    [1, 0, 25, 1],
    [1, 25, 23, 0],
    [1, 23, 25, 1],
    [1, 25, 24, null], // lead only 1 -> continues
    [1, 24, 25, null],
    [1, 24, 24, null],
    [1, 25, 25, null],
    [1, 26, 24, 0], // no cap: 26-24 valid
    [1, 24, 26, 1],
    [1, 31, 29, 0], // no cap: 31-29 valid
    [1, 29, 31, 1],
    [1, 30, 29, null], // deuce marathon continues
    // deciding (5th) set to 15
    [5, 15, 13, 0],
    [5, 13, 15, 1],
    [5, 15, 14, null],
    [5, 14, 14, null],
    [5, 16, 14, 0],
    [5, 14, 16, 1],
    [5, 20, 18, 0], // no cap in the deciding set either
    [5, 15, 0, 0],
  ])("test_set_winner(%i, %i, %i, %s)", (set_number, a, b, expected) => {
    expect(rules.set_winner(config(), set_number, a, b)).toBe(expected);
  });

  test("test_custom_min_lead", () => {
    const cfg: MatchConfig = { ...default_config(), min_lead: 1 };
    expect(rules.set_winner(cfg, 1, 25, 24)).toBe(0);
  });
});

describe("TestMatchWinner", () => {
  test.each<[number, number, 0 | 1 | null]>([
    [0, 0, null], [1, 0, null], [2, 2, null], [2, 1, null],
    [3, 0, 0], [3, 1, 0], [3, 2, 0],
    [0, 3, 1], [1, 3, 1], [2, 3, 1],
  ])("test_best_of_five(%i, %i, %s)", (a, b, expected) => {
    expect(rules.match_winner(config(), a, b)).toBe(expected);
  });

  test("test_best_of_three", () => {
    const cfg: MatchConfig = { ...default_config(), sets_to_win: 2 };
    expect(rules.match_winner(cfg, 2, 0)).toBe(0);
    expect(rules.match_winner(cfg, 1, 1)).toBeNull();
    expect(rules.match_winner(cfg, 0, 2)).toBe(1);
  });
});

// ---------------------------------------------------------- substitutions

const LINEUP = ["p1", "p2", "p3", "p4", "p5", "p6"];
const LIBEROS = ["lib"];

describe("TestValidateSubstitution", () => {
  test("test_clean_substitution_has_no_warnings", () => {
    const w = rules.validate_substitution(LINEUP, LIBEROS, 0, [], "p1", "s1", config());
    expect(w).toEqual([]);
  });

  test("test_sixth_substitution_still_legal", () => {
    const pairs: [string, string][] = [
      ["p1", "s1"], ["p2", "s2"], ["p3", "s3"], ["p4", "s4"], ["p5", "s5"],
    ];
    const w = rules.validate_substitution(LINEUP, LIBEROS, 5, pairs, "p6", "s6", config());
    expect(w).toEqual([]);
  });

  test("test_seventh_substitution_warns_limit", () => {
    const pairs: [string, string][] = [
      ["p1", "s1"], ["p2", "s2"], ["p3", "s3"], ["p4", "s4"], ["p5", "s5"], ["p6", "s6"],
    ];
    const w = rules.validate_substitution(LINEUP, LIBEROS, 6, pairs, "p1", "s7", config());
    expect(w.some((x) => x.includes("limit"))).toBe(true);
  });

  test("test_configurable_sub_limit", () => {
    const cfg: MatchConfig = { ...default_config(), subs_per_set: 2 };
    const w = rules.validate_substitution(LINEUP, LIBEROS, 2, [], "p1", "s1", cfg);
    expect(w.some((x) => x.includes("limit (2)"))).toBe(true);
  });

  test("test_player_out_not_on_court_warns", () => {
    const w = rules.validate_substitution(LINEUP, LIBEROS, 0, [], "ghost", "s1", config());
    expect(w.some((x) => x.includes("not on court"))).toBe(true);
  });

  test("test_player_in_already_on_court_warns", () => {
    const w = rules.validate_substitution(LINEUP, LIBEROS, 0, [], "p1", "p2", config());
    expect(w.some((x) => x.includes("already on court"))).toBe(true);
  });

  test("test_libero_cannot_enter_via_substitution", () => {
    const w = rules.validate_substitution(LINEUP, LIBEROS, 0, [], "p1", "lib", config());
    expect(w.some((x) => x.includes("libero"))).toBe(true);
  });

  test("test_reentry_for_original_partner_is_legal", () => {
    // p1 left for s1; p1 may come back exactly for s1.
    const lineup = ["s1", "p2", "p3", "p4", "p5", "p6"];
    const w = rules.validate_substitution(
      lineup, LIBEROS, 1, [["p1", "s1"]], "s1", "p1", config(),
    );
    expect(w).toEqual([]);
  });

  test("test_exhausted_pair_warns_on_third_exchange", () => {
    // p1 -> s1, s1 -> p1 closed the pair; a third exchange warns.
    const pairs: [string, string][] = [["p1", "s1"], ["s1", "p1"]];
    const w = rules.validate_substitution(LINEUP, LIBEROS, 2, pairs, "p1", "s1", config());
    expect(w.some((x) => x.includes("re-entry"))).toBe(true);
  });

  test("test_substitute_cannot_enter_for_a_different_player", () => {
    // s1 already entered for p1 (and left again); now proposed for p2.
    const pairs: [string, string][] = [["p1", "s1"], ["s1", "p1"]];
    const w = rules.validate_substitution(LINEUP, LIBEROS, 2, pairs, "p2", "s1", config());
    expect(w.some((x) => x.includes("different player"))).toBe(true);
  });

  test("test_starter_may_only_reenter_for_own_substitute", () => {
    // p1 was replaced by s1; p1 tries to come back for p2 instead.
    const lineup = ["s1", "p2", "p3", "p4", "p5", "p6"];
    const w = rules.validate_substitution(
      lineup, LIBEROS, 1, [["p1", "s1"]], "p2", "p1", config(),
    );
    expect(w.some((x) => x.includes("re-enter"))).toBe(true);
  });

  test("test_multiple_warnings_accumulate", () => {
    const w = rules.validate_substitution(LINEUP, LIBEROS, 6, [], "ghost", "p2", config());
    expect(w.length).toBeGreaterThanOrEqual(3); // limit + out-not-on-court + in-already-on-court
  });
});

// ----------------------------------------------------------------- libero

describe("TestValidateLiberoEntry", () => {
  test("test_partner_not_on_court_is_the_only_warning", () => {
    const w = rules.validate_libero_entry(LINEUP, "ghost", false, config());
    expect(w).toEqual(["replaced player is not on court"]);
  });

  test.each([4, 5])("test_back_row_entry_is_legal(%i)", (slot) => {
    const w = rules.validate_libero_entry(LINEUP, LINEUP[slot], false, config());
    expect(w).toEqual([]);
  });

  test.each([1, 2, 3])("test_front_row_entry_warns(%i)", (slot) => {
    const w = rules.validate_libero_entry(LINEUP, LINEUP[slot], false, config());
    expect(w.some((x) => x.includes("back-row"))).toBe(true);
  });

  test("test_p1_while_team_serving_warns_by_default", () => {
    const w = rules.validate_libero_entry(LINEUP, LINEUP[0], true, config());
    expect(w.some((x) => x.includes("may not serve"))).toBe(true);
  });

  test("test_p1_while_team_serving_ok_if_federation_allows", () => {
    const cfg: MatchConfig = { ...default_config(), libero_may_serve: true };
    const w = rules.validate_libero_entry(LINEUP, LINEUP[0], true, cfg);
    expect(w).toEqual([]);
  });

  test("test_p1_while_team_receiving_is_legal", () => {
    const w = rules.validate_libero_entry(LINEUP, LINEUP[0], false, config());
    expect(w).toEqual([]);
  });

  test("test_back_row_entry_while_serving_is_legal_off_p1", () => {
    const w = rules.validate_libero_entry(LINEUP, LINEUP[4], true, config());
    expect(w).toEqual([]);
  });
});

describe("TestValidateLiberoExit", () => {
  test("test_correct_partner_is_legal", () => {
    expect(rules.validate_libero_exit("p5", "p5")).toEqual([]);
  });

  test("test_wrong_partner_warns", () => {
    const w = rules.validate_libero_exit("p5", "p4");
    expect(w).toEqual(["libero must be exchanged back with the player they replaced"]);
  });
});
