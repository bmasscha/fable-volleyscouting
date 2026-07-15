/** Block handling: deflection classification geometry, the engine's
 * covered-ball (block cover) branch, serialization of block_touch and
 * vertex normalization in the trajectory charts.
 * Mirrors tests/test_blocks.py. */
import { describe, expect, test } from "vitest";

import {
  BLOCK_OUT, COVERED, IN_PLAY,
  classify_block_deflection, landing_in_bounds,
} from "../src/core/blocks";
import { MatchEngine, Phase } from "../src/core/engine";
import { AttackEvent, event_from_dict, event_to_dict } from "../src/core/events";
import {
  AWAY, HOME, Rating, Role, Skill, Team, TeamKey,
  default_config, make_player, make_team,
} from "../src/core/models";
import { LEFT, RIGHT } from "../src/core/rotation";
import { collect_trajectories } from "../src/core/trajectories";

const HOME_IDS = ["h1", "h2", "h3", "h4", "h5", "h6"];
const AWAY_IDS = ["a1", "a2", "a3", "a4", "a5", "a6"];

function make_teams(): Record<TeamKey, Team> {
  return {
    home: make_team("Home", [1, 2, 3, 4, 5, 6].map((i) => make_player(i, `H${i}`, Role.UNIVERSAL, `h${i}`))),
    away: make_team("Away", [1, 2, 3, 4, 5, 6].map((i) => make_player(i, `A${i}`, Role.UNIVERSAL, `a${i}`))),
  };
}

function set_start_event(serving: TeamKey = HOME, left: TeamKey = HOME) {
  return {
    type: "set_start" as const,
    set_number: 1,
    lineups: { home: [...HOME_IDS], away: [...AWAY_IDS] },
    liberos: { home: [] as string[], away: [] as string[] },
    serving_team: serving,
    left_team: left,
  };
}

// ----------------------------------------------------------- classification

describe("classification", () => {
  test.each([
    [9.5, 4.5],     // beyond right baseline
    [-9.5, 4.5],    // beyond left baseline
    [3.0, -0.5],    // beyond north sideline
    [3.0, 9.5],     // beyond south sideline
    [-12.0, 11.0],  // far out
  ])("out of bounds (%f, %f) is block_out for both sides", (x, y) => {
    expect(classify_block_deflection(LEFT, x, y)).toBe(BLOCK_OUT);
    expect(classify_block_deflection(RIGHT, x, y)).toBe(BLOCK_OUT);
  });

  test("out tolerance matches serve tolerance", () => {
    // 0.4 m beyond the line is still "in", just past it is out
    expect(landing_in_bounds(9.4, 4.5)).toBe(true);
    expect(landing_in_bounds(9.41, 4.5)).toBe(false);
    expect(landing_in_bounds(3.0, -0.4)).toBe(true);
    expect(landing_in_bounds(3.0, -0.41)).toBe(false);
  });

  test("landing on attacker half is covered", () => {
    expect(classify_block_deflection(LEFT, -3.0, 4.0)).toBe(COVERED);
    expect(classify_block_deflection(RIGHT, 3.0, 4.0)).toBe(COVERED);
  });

  test("landing on blocker half stays in play", () => {
    expect(classify_block_deflection(LEFT, 3.0, 4.0)).toBe(IN_PLAY);
    expect(classify_block_deflection(RIGHT, -3.0, 4.0)).toBe(IN_PLAY);
  });

  test("landing exactly on net plane counts as blocker side", () => {
    expect(classify_block_deflection(LEFT, 0.0, 4.5)).toBe(IN_PLAY);
    expect(classify_block_deflection(RIGHT, 0.0, 4.5)).toBe(IN_PLAY);
  });
});

// ------------------------------------------------------------ engine flows

/** Set running, HOME serving from the LEFT, rally advanced to the point
 * where AWAY (right side) is in the attack phase. */
function make_engine(): MatchEngine {
  const teams = make_teams();
  const eng = new MatchEngine(default_config(), teams);
  eng.append(set_start_event(HOME, HOME));
  eng.append({ type: "serve", team: HOME, player_id: eng.state.team[HOME].lineup[0]!, rating: Rating.GOOD });
  eng.append({ type: "reception", team: AWAY, player_id: eng.state.team[AWAY].lineup[0]!, rating: Rating.GOOD });
  expect(eng.state.phase).toBe(Phase.ATTACK);
  expect(eng.state.attacking_team).toBe(AWAY);
  return eng;
}

function blocked_attack(engine: MatchEngine, team: TeamKey, rating: Rating,
  landing: [number, number], touch: [number, number] = [0.2, 4.5]): AttackEvent {
  const [x1, y1] = engine.side_of(team) === RIGHT ? [4.0, 4.5] : [-4.0, 4.5];
  return {
    type: "attack", team,
    player_id: engine.state.team[team].lineup[1]!,
    rating,
    trajectory: [x1, y1, landing[0], landing[1]],
    block_touch: touch,
  };
}

describe("engine flows", () => {
  test("covered ball returns play to attacking team", () => {
    const engine = make_engine();
    // AWAY attacks from the right; the block returns the ball into the
    // right (AWAY) half in-bounds -> AWAY must cover its own ball
    let w = engine.append(blocked_attack(engine, AWAY, Rating.POOR, [3.0, 3.0]));
    expect(w).toEqual([]);
    expect(engine.state.phase).toBe(Phase.DEFENSE);
    expect(engine.state.attacking_team).toBe(HOME); // "ball comes from" HOME side

    // the cover dig charged to AWAY is legal...
    w = engine.append({ type: "dig", team: AWAY, player_id: engine.state.team[AWAY].lineup[4]!, rating: Rating.GOOD });
    expect(w).toEqual([]);
    // ...and AWAY attacks again
    expect(engine.state.phase).toBe(Phase.ATTACK);
    expect(engine.state.attacking_team).toBe(AWAY);
  });

  test("dig by blockers after covered ball warns", () => {
    const engine = make_engine();
    engine.append(blocked_attack(engine, AWAY, Rating.POOR, [3.0, 3.0]));
    const w = engine.append({ type: "dig", team: HOME, player_id: engine.state.team[HOME].lineup[4]!, rating: Rating.GOOD });
    expect(w.some((x) => x.includes("dig charged to the attacking team"))).toBe(true);
  });

  test("covered ball then direct attack uses implicit dig", () => {
    const engine = make_engine();
    engine.append(blocked_attack(engine, AWAY, Rating.POOR, [3.0, 3.0]));
    // scouter skips the cover dig and logs the next AWAY attack directly
    const w = engine.append({ type: "attack", team: AWAY, player_id: engine.state.team[AWAY].lineup[2]!, rating: Rating.GOOD });
    expect(w).toEqual([]);
    expect(engine.state.phase).toBe(Phase.DEFENSE);
    expect(engine.state.attacking_team).toBe(AWAY);
  });

  test("block-out kill awards point to attacker", () => {
    const engine = make_engine();
    const before = engine.state.scores[AWAY];
    engine.append(blocked_attack(engine, AWAY, Rating.PERFECT, [-2.0, 10.0])); // deflected out
    expect(engine.state.scores[AWAY]).toBe(before + 1);
    expect(engine.state.phase).toBe(Phase.AWAIT_SERVE);
  });

  test("deflection on blocker side is normal defense", () => {
    const engine = make_engine();
    const w = engine.append(blocked_attack(engine, AWAY, Rating.GOOD, [-4.0, 4.0]));
    expect(w).toEqual([]);
    expect(engine.state.phase).toBe(Phase.DEFENSE);
    expect(engine.state.attacking_team).toBe(AWAY); // HOME digs as usual
  });

  test("attack without block_touch unchanged", () => {
    const engine = make_engine();
    engine.append({ type: "attack", team: AWAY, player_id: engine.state.team[AWAY].lineup[1]!, rating: Rating.GOOD, trajectory: [4.0, 4.5, -3.0, 3.0] });
    expect(engine.state.phase).toBe(Phase.DEFENSE);
    expect(engine.state.attacking_team).toBe(AWAY);
  });

  test("undo restores pre-block state", () => {
    const engine = make_engine();
    engine.append(blocked_attack(engine, AWAY, Rating.POOR, [3.0, 3.0]));
    engine.undo();
    expect(engine.state.phase).toBe(Phase.ATTACK);
    expect(engine.state.attacking_team).toBe(AWAY);
  });
});

// ---------------------------------------------------------- serialization

describe("serialization", () => {
  test("block_touch round trip", () => {
    const e: AttackEvent = {
      type: "attack", ts: null, team: HOME, player_id: "H2", rating: Rating.POOR,
      trajectory: [-4.0, 4.5, -3.0, 3.0], block_touch: [-0.2, 4.5],
    };
    const d = event_to_dict(e);
    expect(d.block_touch).toEqual([-0.2, 4.5]);
    const back = event_from_dict(d);
    expect(back).toEqual(e);
    expect((back as AttackEvent).block_touch).toEqual([-0.2, 4.5]);
  });

  test("legacy attack dict without block_touch loads", () => {
    const d = {
      type: "attack", team: HOME, player_id: "H2", rating: "+",
      trajectory: [-4.0, 4.5, 3.0, 3.0], ts: null,
    };
    const e = event_from_dict(d) as AttackEvent;
    expect(e.block_touch).toBeNull();
  });
});

// ------------------------------------------------------------ chart stats

describe("chart stats", () => {
  test("block_touch normalized like line", () => {
    // An attack from the RIGHT half is mirrored to the canonical
    // left -> right orientation, vertex included.
    const teams = make_teams();
    const config = default_config();
    const events = [
      set_start_event(HOME, HOME),
      { type: "serve" as const, team: HOME, player_id: "h1", rating: Rating.GOOD },
      { type: "reception" as const, team: AWAY, player_id: "a1", rating: Rating.GOOD },
      {
        type: "attack" as const, team: AWAY, player_id: teams[AWAY].players[1]!.id,
        rating: Rating.PERFECT, trajectory: [4.0, 4.5, -2.0, 10.0] as [number, number, number, number],
        block_touch: [0.2, 4.0] as [number, number],
      },
    ];
    const stats = collect_trajectories(config, teams, events);
    const atk = stats.filter((s) => s.block_touch != null);
    expect(atk).toHaveLength(1);
    // RIGHT-side mirror: (x, y) -> (-x, 9 - y)
    expect(atk[0]!.line).toEqual([-4.0, 4.5, 2.0, -1.0]);
    expect(atk[0]!.block_touch).toEqual([-0.2, 5.0]);
  });

  test("serve trajectory has no block_touch", () => {
    const teams = make_teams();
    const config = default_config();
    const events = [
      set_start_event(HOME, HOME),
      { type: "serve" as const, team: HOME, player_id: teams[HOME].players[0]!.id, rating: Rating.GOOD, trajectory: [-10.0, 7.5, 5.0, 3.0] as [number, number, number, number] },
    ];
    const stats = collect_trajectories(config, teams, events);
    expect(stats[0]!.block_touch).toBeNull();
  });
});
