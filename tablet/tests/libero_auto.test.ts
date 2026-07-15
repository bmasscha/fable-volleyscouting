/** Automatic libero exchange: forced front-row exits, learned re-entry
 * at serve-receive, the auto_libero config gate, pairing memory and the
 * `auto` flag on LiberoSwapEvent.
 * Mirrors tests/test_libero_auto.py. */
import { describe, expect, test } from "vitest";

import { MatchEngine, Phase } from "../src/core/engine";
import {
  LiberoSwapEvent, event_from_dict, event_to_dict,
} from "../src/core/events";
import {
  AWAY, HOME, MatchConfig, Rating, Role, Team, TeamKey,
  config_from_dict, config_to_dict, default_config,
  make_player, make_team,
} from "../src/core/models";
import { BACK_ROW } from "../src/core/rotation";

const LIB = "h7";

function make_teams(): Record<TeamKey, Team> {
  // h3 and h5 are the middles the libero exchanges with; h7 is the libero
  const roles: Record<number, Role> = { 3: Role.MIDDLE, 5: Role.MIDDLE, 7: Role.LIBERO };
  return {
    home: make_team("Home", [1, 2, 3, 4, 5, 6, 7].map(
      (i) => make_player(i, `H${i}`, roles[i] ?? Role.UNIVERSAL, `h${i}`))),
    away: make_team("Away", [1, 2, 3, 4, 5, 6, 7].map(
      (i) => make_player(i + 50, `A${i}`, i === 7 ? Role.LIBERO : Role.UNIVERSAL, `a${i}`))),
  };
}

function set_start_event(serving: TeamKey = AWAY, left: TeamKey = HOME) {
  return {
    type: "set_start" as const,
    set_number: 1,
    lineups: {
      home: ["h1", "h2", "h3", "h4", "h5", "h6"],
      away: ["a1", "a2", "a3", "a4", "a5", "a6"],
    },
    liberos: { home: [LIB], away: ["a7"] },
    serving_team: serving,
    left_team: left,
  };
}

/** Set running, AWAY serving, HOME receiving (lineup h1..h6, P1..P6). */
function make_engine(config?: MatchConfig): MatchEngine {
  const engine = new MatchEngine(config ?? default_config(), make_teams());
  engine.append(set_start_event());
  return engine;
}

/** UI behavior: append engine-proposed swaps until there are none. */
function drain(engine: MatchEngine, limit = 6): LiberoSwapEvent[] {
  const applied: LiberoSwapEvent[] = [];
  for (let i = 0; i < limit; i++) {
    const e = engine.next_auto_libero_swap();
    if (e == null) break;
    engine.append(e);
    applied.push(e);
  }
  return applied;
}

function enter_libero(engine: MatchEngine, partner = "h5"): void {
  engine.append({
    type: "libero_swap", team: HOME, libero_id: LIB, partner_id: partner,
  });
}

function rally_point(engine: MatchEngine, team: TeamKey): void {
  engine.append({ type: "rally_point", team });
}

// ------------------------------------------------------------- forced exits

describe("forced exits", () => {
  test("no suggestion before any entry", () => {
    const engine = make_engine();
    expect(engine.next_auto_libero_swap()).toBeNull();
    rally_point(engine, HOME); // side-out, HOME rotates
    expect(engine.next_auto_libero_swap()).toBeNull();
  });

  test("forced exit when libero rotates to front row", () => {
    const engine = make_engine();
    enter_libero(engine); // libero in for h5 at P5
    rally_point(engine, HOME); // side-out: libero -> P4
    const e = engine.next_auto_libero_swap();
    expect(e).not.toBeNull();
    expect(e!.auto).toBe(true);
    expect(e!.team).toBe(HOME);
    expect(e!.libero_id).toBe(LIB);
    expect(e!.partner_id).toBe("h5");
    engine.append(e!);
    const lineup = engine.state.team[HOME].lineup;
    expect(lineup[3]).toBe("h5"); // h5 back at P4
    expect(lineup.includes(LIB)).toBe(false);
    expect(engine.pending_alerts()).toEqual([]);
  });

  test("forced exit when libero must serve", () => {
    const engine = make_engine();
    enter_libero(engine);
    rally_point(engine, HOME); // HOME gains serve
    // push the libero (now P4) to P1 by force
    engine.append({ type: "rotation_adjust", team: HOME, steps: 3 });
    expect(engine.state.team[HOME].lineup[0]).toBe(LIB);
    const e = engine.next_auto_libero_swap();
    expect(e).not.toBeNull();
    expect(e!.auto).toBe(true);
    expect(e!.partner_id).toBe("h5");
  });

  test("libero_may_serve suppresses the P1 exit", () => {
    const engine = make_engine({ ...default_config(), libero_may_serve: true });
    enter_libero(engine);
    rally_point(engine, HOME);
    engine.append({ type: "rotation_adjust", team: HOME, steps: 3 });
    expect(engine.state.team[HOME].lineup[0]).toBe(LIB);
    expect(engine.next_auto_libero_swap()).toBeNull(); // serving from P1 is legal
  });

  test("auto_libero disabled never suggests", () => {
    const engine = make_engine({ ...default_config(), auto_libero: false });
    enter_libero(engine);
    rally_point(engine, HOME); // libero at P4: exit is due
    expect(engine.next_auto_libero_swap()).toBeNull();
    expect(engine.pending_alerts()).toHaveLength(1); // manual alert still shown
  });
});

// ---------------------------------------------------------------- re-entry

describe("re-entry", () => {
  test("no blind re-entry without a partner in the back row", () => {
    const engine = make_engine();
    enter_libero(engine);
    rally_point(engine, HOME);
    drain(engine); // forced exit applied
    rally_point(engine, AWAY); // HOME receives next
    // learned partner h5 is at P4 (front) and no middle is in the back row
    expect(engine.next_auto_libero_swap()).toBeNull();
  });

  test("role fallback picks the back-row middle", () => {
    const engine = make_engine();
    enter_libero(engine);
    rally_point(engine, HOME);
    drain(engine);
    rally_point(engine, AWAY); // HOME receives...
    rally_point(engine, HOME); // ...and rotates: h3 -> P1
    rally_point(engine, AWAY); // HOME receives next
    const e = engine.next_auto_libero_swap();
    expect(e).not.toBeNull();
    expect(e!.auto).toBe(true);
    expect(e!.partner_id).toBe("h3"); // role fallback
    engine.append(e!);
    expect(engine.state.team[HOME].libero_partners[LIB]).toEqual(["h5", "h3"]);
  });

  test("learned partner preferred at serve-receive", () => {
    // full cycle: libero has entered for both h5 and h3; when h5 arrives
    // in the back row at serve-receive the learned pairing brings the
    // libero straight back without relying on roles
    const engine = make_engine();
    enter_libero(engine);
    for (const winner of [HOME, AWAY, HOME, AWAY] as TeamKey[]) {
      rally_point(engine, winner);
      drain(engine);
    }
    for (const winner of [HOME, AWAY, HOME, AWAY, HOME] as TeamKey[]) {
      rally_point(engine, winner);
      drain(engine); // second forced exit inside
    }
    rally_point(engine, AWAY); // HOME receives next
    const e = engine.next_auto_libero_swap();
    expect(e).not.toBeNull();
    expect(e!.auto).toBe(true);
    expect(e!.partner_id).toBe("h5"); // learned pairing
    const lineup = engine.state.team[HOME].lineup;
    expect(BACK_ROW.includes(lineup.indexOf(e!.partner_id))).toBe(true);
  });

  test("no re-entry while own team serves", () => {
    const engine = make_engine();
    enter_libero(engine);
    rally_point(engine, HOME); // HOME serves next
    drain(engine); // forced exit only
    expect(engine.state.serving_team).toBe(HOME);
    expect(engine.next_auto_libero_swap()).toBeNull();
  });

  test("no re-entry when libero already on court", () => {
    const engine = make_engine();
    enter_libero(engine);
    expect(engine.next_auto_libero_swap()).toBeNull();
  });

  test("no suggestions during a live rally", () => {
    const engine = make_engine();
    enter_libero(engine);
    rally_point(engine, HOME); // exit is due (libero at P4)
    engine.append({
      type: "serve", team: HOME,
      player_id: engine.state.team[HOME].lineup[0], rating: Rating.GOOD,
    });
    expect(engine.state.phase).toBe(Phase.RECEPTION);
    expect(engine.next_auto_libero_swap()).toBeNull();
  });

  test("drain terminates and settles", () => {
    const engine = make_engine();
    enter_libero(engine);
    rally_point(engine, HOME);
    const applied = drain(engine);
    expect(applied.length).toBeGreaterThanOrEqual(1);
    expect(applied.length).toBeLessThanOrEqual(3);
    expect(engine.next_auto_libero_swap()).toBeNull();
  });

  test("pairing memory resets next set", () => {
    const engine = new MatchEngine(
      { ...default_config(), points_per_set: 1, min_lead: 1 }, make_teams());
    engine.append(set_start_event());
    enter_libero(engine);
    rally_point(engine, HOME); // 1-0: set over
    expect(engine.state.phase).toBe(Phase.SET_OVER);
    engine.append(engine.suggest_next_set_start()!);
    expect(engine.state.team[HOME].libero_partners).toEqual({});
    expect(engine.next_auto_libero_swap()).toBeNull(); // first entry manual again
  });
});

// ------------------------------------------------------------ serialization

describe("serialization", () => {
  test("auto flag round trip", () => {
    const e: LiberoSwapEvent = {
      type: "libero_swap", ts: null, team: HOME,
      libero_id: "L", partner_id: "P", auto: true,
    };
    const d = event_to_dict(e);
    expect(d.auto).toBe(true);
    expect(event_from_dict(d)).toEqual(e);
  });

  test("legacy swap dict defaults to manual", () => {
    const d = {
      type: "libero_swap", team: HOME, libero_id: "L",
      partner_id: "P", ts: null,
    };
    expect((event_from_dict(d) as LiberoSwapEvent).auto).toBe(false);
  });

  test("legacy config defaults auto_libero on", () => {
    const d = config_to_dict(default_config());
    delete d.auto_libero;
    expect(config_from_dict(d).auto_libero).toBe(true);
  });
});
