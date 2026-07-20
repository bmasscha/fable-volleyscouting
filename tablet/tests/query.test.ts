import { describe, expect, test } from "vitest";

import { MatchEvent } from "../src/core/events";
import { AWAY, HOME, Rating, Role, Skill, Team, TeamKey, make_player, make_team } from "../src/core/models";
import { Action, ActionFilter, build_actions, filter_actions } from "../src/core/query";

function makeTeams(): Record<TeamKey, Team> {
  return {
    [HOME]: make_team("Home", [
      make_player(1, "Setter", Role.SETTER, "h1"),
      make_player(7, "Libero", Role.LIBERO, "h7"),
      make_player(12, "Wing", Role.OUTSIDE, "h12"),
    ]),
    [AWAY]: make_team("Away", [
      make_player(5, "Ace", Role.OPPOSITE, "a5"),
      make_player(12, "AwayWing", Role.OUTSIDE, "a12"),
    ]),
  };
}

function sampleEvents(): MatchEvent[] {
  return [
    { type: "set_start", set_number: 1, lineups: { home: [], away: [] },
      liberos: { home: ["h7"], away: [] }, serving_team: HOME, left_team: HOME, ts: 100 },
    { type: "serve", team: HOME, player_id: "h1", rating: Rating.ERROR, ts: 101 },
    { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, ts: 110 },
    { type: "reception", team: AWAY, player_id: "a5", rating: Rating.GOOD, ts: 111 },
    { type: "attack", team: AWAY, player_id: "a12", rating: Rating.PERFECT, ts: 112 },
    { type: "dig", team: HOME, player_id: "h7", rating: Rating.POOR, ts: 113 },
    { type: "set_start", set_number: 2, lineups: { home: [], away: [] },
      liberos: { home: ["h7"], away: [] }, serving_team: AWAY, left_team: AWAY, ts: 200 },
    { type: "serve", team: AWAY, player_id: "a5", rating: Rating.GOOD, ts: 201 },
    { type: "attack", team: AWAY, player_id: "a12", rating: Rating.GOOD, ts: 203 },
  ] as MatchEvent[];
}

describe("build_actions", () => {
  test("emits one action per skill event, skipping set_start", () => {
    const actions = build_actions(sampleEvents(), makeTeams());
    expect(actions).toHaveLength(7);
    expect(new Set(actions.map((a: Action) => a.skill))).toEqual(
      new Set([Skill.SERVE, Skill.RECEPTION, Skill.ATTACK, Skill.DIG]),
    );
  });

  test("resolves player and context", () => {
    const actions = build_actions(sampleEvents(), makeTeams());
    const attack = actions.find((a) => a.skill === Skill.ATTACK && a.set_number === 1)!;
    expect(attack.team_key).toBe(AWAY);
    expect(attack.player_number).toBe(12);
    expect(attack.player_name).toBe("AwayWing");
    expect(attack.role).toBe(Role.OUTSIDE);
    expect(attack.rating).toBe(Rating.PERFECT);
    expect(attack.ts).toBe(112);
    expect(attack.rally_index).toBe(2); // follows the 2nd serve
  });

  test("rally_index increments per serve and resets per set", () => {
    const actions = build_actions(sampleEvents(), makeTeams());
    const set1 = actions.filter((a) => a.set_number === 1);
    expect(set1.map((a) => a.rally_index)).toEqual([1, 2, 2, 2, 2]);
    const set2 = actions.filter((a) => a.set_number === 2);
    expect(set2[0]!.rally_index).toBe(1);
  });

  test("keeps an unknown player without roster data", () => {
    const events = [
      { type: "set_start", set_number: 1, lineups: { home: [], away: [] },
        liberos: { home: [], away: [] }, serving_team: HOME, left_team: HOME },
      { type: "serve", team: HOME, player_id: "ghost", rating: Rating.GOOD, ts: 5 },
    ] as MatchEvent[];
    const actions = build_actions(events, makeTeams());
    expect(actions).toHaveLength(1);
    expect(actions[0]!.player_number).toBeNull();
    expect(actions[0]!.role).toBeNull();
    expect(actions[0]!.player_name).toBe("");
  });
});

describe("filter_actions", () => {
  test("attacks by away #12", () => {
    const actions = build_actions(sampleEvents(), makeTeams());
    const spec: ActionFilter = { team_key: AWAY, player_number: 12, skill: Skill.ATTACK };
    expect(filter_actions(actions, spec).map((a) => a.ts)).toEqual([112, 203]);
  });

  test("serve-receive by the home libero (by role)", () => {
    const actions = build_actions(sampleEvents(), makeTeams());
    const recv = filter_actions(actions, {
      team_key: HOME, role: Role.LIBERO, skill: Skill.RECEPTION,
    });
    expect(recv).toEqual([]);
    const anySkill = filter_actions(actions, { team_key: HOME, role: Role.LIBERO });
    expect(anySkill.map((a) => a.skill)).toEqual([Skill.DIG]);
  });

  test("failed serves by a player", () => {
    const actions = build_actions(sampleEvents(), makeTeams());
    const result = filter_actions(actions, {
      player_id: "h1", skill: Skill.SERVE, rating: Rating.ERROR,
    });
    expect(result).toHaveLength(1);
    expect(result[0]!.ts).toBe(101);
  });

  test("by set number", () => {
    const actions = build_actions(sampleEvents(), makeTeams());
    const result = filter_actions(actions, { set_number: 2 });
    expect(result).toHaveLength(2);
    expect(new Set(result.map((a) => a.set_number))).toEqual(new Set([2]));
  });

  test("sorts timeless actions last, in event order", () => {
    const events = [
      { type: "set_start", set_number: 1, lineups: { home: [], away: [] },
        liberos: { home: [], away: [] }, serving_team: HOME, left_team: HOME },
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD },
      { type: "serve", team: HOME, player_id: "h1", rating: Rating.GOOD, ts: 1 },
    ] as MatchEvent[];
    const actions = build_actions(events, makeTeams());
    const result = filter_actions(actions, { skill: Skill.SERVE });
    expect(result.map((a) => a.ts)).toEqual([1, null]);
  });
});
