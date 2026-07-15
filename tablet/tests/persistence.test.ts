import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "vitest";

import * as persistence from "../src/core/persistence";
import {
  AttackEvent,
  DigEvent,
  LiberoSwapEvent,
  ManualScoreEvent,
  MatchEvent,
  RallyPointEvent,
  ReceptionEvent,
  RotationAdjustEvent,
  ServeEvent,
  ServeOverrideEvent,
  SetStartEvent,
  SubstitutionEvent,
  TimeoutEvent,
  Trajectory,
  event_from_dict,
  event_to_dict,
} from "../src/core/events";
import { AWAY, HOME, MatchConfig, Player, Rating, Role, Team, TeamKey, default_config, make_player, make_team } from "../src/core/models";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));

function with_tmp_dir<T>(prefix: string, fn: (tmp_dir: string) => T): T {
  const tmp_dir = mkdtempSync(join(TEST_DIR, `${prefix}-`));
  try {
    return fn(tmp_dir);
  } finally {
    rmSync(tmp_dir, { recursive: true, force: true });
  }
}

function make_teams(): Record<TeamKey, Team> {
  const home = make_team("Home",
    Array.from({ length: 9 }, (_, i) => make_player(
      i + 1,
      `H${i + 1}`,
      i === 0 ? Role.SETTER : i === 6 ? Role.LIBERO : Role.OUTSIDE,
    )));
  const away = make_team("Away",
    Array.from({ length: 9 }, (_, i) => make_player(i + 51, `A${i + 1}`)));
  return { [HOME]: home, [AWAY]: away };
}

function all_event_samples(teams: Record<TeamKey, Team>): MatchEvent[] {
  const h = teams[HOME].players.map((p) => p.id);
  const a = teams[AWAY].players.map((p) => p.id);
  return [
    {
      type: "set_start",
      ts: null,
      set_number: 1,
      lineups: { [HOME]: h.slice(0, 6), [AWAY]: a.slice(0, 6) },
      liberos: { [HOME]: [h[6]!], [AWAY]: [a[6]!] },
      serving_team: HOME,
      left_team: AWAY,
    } satisfies SetStartEvent,
    {
      type: "serve",
      ts: null,
      team: HOME,
      player_id: h[0]!,
      rating: Rating.GOOD,
      trajectory: [-10.2, 7.5, 4.4, 3.1] as Trajectory,
    } satisfies ServeEvent,
    {
      type: "serve",
      ts: null,
      team: HOME,
      player_id: h[0]!,
      rating: Rating.ERROR,
      trajectory: null,
    } satisfies ServeEvent,
    {
      type: "reception",
      ts: null,
      team: AWAY,
      player_id: a[4]!,
      rating: Rating.PERFECT,
      overpass: false,
    } satisfies ReceptionEvent,
    {
      type: "reception",
      ts: null,
      team: AWAY,
      player_id: a[4]!,
      rating: Rating.POOR,
      overpass: true,
    } satisfies ReceptionEvent,
    { type: "rotation_adjust", ts: null, team: HOME, steps: -1 } satisfies RotationAdjustEvent,
    {
      type: "attack",
      ts: null,
      team: AWAY,
      player_id: a[1]!,
      rating: Rating.POOR,
      trajectory: [2.0, 1.0, -6.0, 8.0] as Trajectory,
      block_touch: null,
    } satisfies AttackEvent,
    {
      type: "attack",
      ts: null,
      team: AWAY,
      player_id: a[1]!,
      rating: Rating.PERFECT,
      trajectory: null,
      block_touch: null,
    } satisfies AttackEvent,
    { type: "dig", ts: null, team: HOME, player_id: h[5]!, rating: Rating.GOOD } satisfies DigEvent,
    { type: "rally_point", ts: null, team: AWAY, reason: "net fault" } satisfies RallyPointEvent,
    { type: "substitution", ts: null, team: HOME, player_out: h[0]!, player_in: h[7]! } satisfies SubstitutionEvent,
    { type: "libero_swap", ts: null, team: AWAY, libero_id: a[6]!, partner_id: a[2]! } satisfies LiberoSwapEvent,
    { type: "manual_score", ts: null, team: HOME, delta: -1 } satisfies ManualScoreEvent,
    { type: "serve_override", ts: null, team: AWAY } satisfies ServeOverrideEvent,
    { type: "timeout", ts: null, team: HOME } satisfies TimeoutEvent,
  ];
}

describe("TestEventSerialization", () => {
  test("test_every_event_type_round_trips", () => {
    for (const event of all_event_samples(make_teams())) {
      expect(event_from_dict(event_to_dict(event))).toEqual(event);
    }
  });

  test("test_rating_serialized_as_symbol", () => {
    const teams = make_teams();
    const event: ServeEvent = {
      type: "serve",
      ts: null,
      team: HOME,
      player_id: teams[HOME].players[0]!.id,
      rating: Rating.PERFECT,
    };
    expect(event_to_dict(event).rating).toBe("#");
  });

  test("test_trajectory_list_in_dict_tuple_after_load", () => {
    const teams = make_teams();
    const event: AttackEvent = {
      type: "attack",
      ts: null,
      team: HOME,
      player_id: teams[HOME].players[0]!.id,
      rating: Rating.GOOD,
      trajectory: [1.0, 2.0, 3.0, 4.0],
    };
    const d = event_to_dict(event);
    expect(d.trajectory).toEqual([1.0, 2.0, 3.0, 4.0]);
    expect((event_from_dict(d) as AttackEvent).trajectory).toEqual([1.0, 2.0, 3.0, 4.0]);
  });
});

describe("TestMatchRoundTrip", () => {
  test("test_full_round_trip", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      const config: MatchConfig = { ...default_config(), sets_to_win: 2, points_per_set: 21, libero_may_serve: true };
      const events = all_event_samples(teams);
      const path = join(tmp_dir, "match.json");
      persistence.save_match(path, config, teams, events);

      const [config2, teams2, events2] = persistence.load_match(path);
      expect(config2).toEqual(config);
      expect(events2).toEqual(events);
      for (const team_key of [HOME, AWAY] as const) {
        expect(teams2[team_key].name).toBe(teams[team_key].name);
        expect(teams2[team_key].color).toBe(teams[team_key].color);
        expect(teams2[team_key].players.map((p) => [p.id, p.number, p.name, p.role]))
          .toEqual(teams[team_key].players.map((p) => [p.id, p.number, p.name, p.role]));
      }
    });
  });

  test("test_file_is_valid_json_and_overwrites", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      const path = join(tmp_dir, "m.json");
      persistence.save_match(path, default_config(), teams, []);
      expect(JSON.parse(readFileSync(path, "utf8")).events).toEqual([]);
      const events = all_event_samples(teams);
      persistence.save_match(path, default_config(), teams, events);
      expect(JSON.parse(readFileSync(path, "utf8")).events).toHaveLength(events.length);
      const leftovers = readdirSync(tmp_dir).filter((p) => p.endsWith(".tmp"));
      expect(leftovers).toEqual([]);
    });
  });
});

describe("TestTimestamps", () => {
  test("test_ts_defaults_to_none_and_round_trips", () => {
    const event = event_from_dict({ type: "timeout", team: HOME });
    expect(event.ts).toBeNull();
    const stamped: ServeOverrideEvent = { type: "serve_override", team: AWAY, ts: 1234.5 };
    const d = event_to_dict(stamped);
    expect(d.ts).toBe(1234.5);
    expect(event_from_dict(d).ts).toBe(1234.5);
  });

  test("test_old_files_without_ts_still_load", () => {
    const d = { type: "timeout", team: HOME }; // pre-timestamp format
    expect(event_from_dict(d)).toEqual({ type: "timeout", team: HOME, ts: null });
  });

  test("test_ts_survives_match_round_trip", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      const events: MatchEvent[] = [
        { type: "timeout", team: HOME, ts: 100.0 } satisfies TimeoutEvent,
        { type: "rally_point", team: AWAY, ts: 101.5 } satisfies RallyPointEvent,
      ];
      const path = join(tmp_dir, "m.json");
      persistence.save_match(path, default_config(), teams, events);
      const [, , events2] = persistence.load_match(path);
      expect(events2.map((event) => event.ts)).toEqual([100.0, 101.5]);
    });
  });
});

describe("TestEventLog", () => {
  test("test_writer_reader_round_trip", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      const config: MatchConfig = { ...default_config(), points_per_set: 21 };
      const events = all_event_samples(teams);
      const lp = join(tmp_dir, "m.log.jsonl");
      const w = new persistence.EventLogWriter(lp, config, teams, events.slice(0, 3));
      for (const event of events.slice(3)) {
        w.log_event(event);
      }
      w.close();
      const [config2, teams2, events2] = persistence.read_event_log(lp);
      expect(config2).toEqual(config);
      expect(events2).toEqual(events);
      expect(teams2[HOME].name).toBe(teams[HOME].name);
    });
  });

  test("test_undo_records_pop_events", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      const events = all_event_samples(teams);
      const lp = join(tmp_dir, "m.log.jsonl");
      const w = new persistence.EventLogWriter(lp, default_config(), teams);
      w.log_event(events[0]!);
      w.log_event(events[1]!);
      w.log_undo();
      w.log_event(events[2]!);
      w.close();
      const [, , events2] = persistence.read_event_log(lp);
      expect(events2).toEqual([events[0], events[2]]);
    });
  });

  test("test_truncated_last_line_is_skipped", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      const events = all_event_samples(teams);
      const lp = join(tmp_dir, "m.log.jsonl");
      const w = new persistence.EventLogWriter(lp, default_config(), teams, events.slice(0, 2));
      w.close();
      writeFileSync(lp, readFileSync(lp, "utf8") + "{\"type\": \"timeout\", \"tea", "utf8"); // power lost mid-write
      const [, , events2] = persistence.read_event_log(lp);
      expect(events2).toEqual(events.slice(0, 2));
    });
  });

  test("test_log_without_header_raises", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const lp = join(tmp_dir, "m.log.jsonl");
      writeFileSync(lp, "{\"type\": \"timeout\", \"team\": \"home\", \"ts\": null}\n", "utf8");
      expect(() => persistence.read_event_log(lp)).toThrow();
    });
  });

  test("test_log_path_naming", () => {
    expect(basename(persistence.log_path(join("x", "match.json")))).toBe("match.log.jsonl");
  });

  test("test_default_rosters_dir_is_project_level", () => {
    const path = persistence.rosters_dir();
    expect(path.endsWith(join("tablet", "rosters"))).toBe(true);
    rmSync(path, { recursive: true, force: true });
  });
});

describe("TestLoadWithLogRecovery", () => {
  test("test_log_ahead_of_snapshot_wins", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      const config = default_config();
      const events = all_event_samples(teams);
      const path = join(tmp_dir, "m.json");
      persistence.save_match(path, config, teams, events.slice(0, 4));
      const w = new persistence.EventLogWriter(persistence.log_path(path), config, teams, events.slice(0, 6));
      w.close();
      const [, , events2, recovered] = persistence.load_match_with_log(path);
      expect(recovered).toBe(2);
      expect(events2).toEqual(events.slice(0, 6));
    });
  });

  test("test_snapshot_up_to_date_wins", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      const config = default_config();
      const events = all_event_samples(teams);
      const path = join(tmp_dir, "m.json");
      persistence.save_match(path, config, teams, events.slice(0, 4));
      const w = new persistence.EventLogWriter(persistence.log_path(path), config, teams, events.slice(0, 4));
      w.close();
      const [, , events2, recovered] = persistence.load_match_with_log(path);
      expect(recovered).toBe(0);
      expect(events2).toEqual(events.slice(0, 4));
    });
  });

  test("test_missing_or_corrupt_log_is_ignored", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      const events = all_event_samples(teams);
      const path = join(tmp_dir, "m.json");
      persistence.save_match(path, default_config(), teams, events.slice(0, 3));
      let [, , events2, recovered] = persistence.load_match_with_log(path);
      expect([events2.length, recovered]).toEqual([3, 0]);
      writeFileSync(persistence.log_path(path), "garbage\n", "utf8");
      [, , events2, recovered] = persistence.load_match_with_log(path);
      expect([events2.length, recovered]).toEqual([3, 0]);
    });
  });
});

describe("TestRosterLibrary", () => {
  test("test_save_load_delete", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const teams = make_teams();
      persistence.save_team(teams[HOME], tmp_dir);
      persistence.save_team(teams[AWAY], tmp_dir);
      const loaded = persistence.load_teams(tmp_dir);
      expect(loaded.map((t) => t.name).sort()).toEqual(["Away", "Home"]);
      const home2 = loaded.find((t) => t.name === "Home")!;
      expect(home2.players[6]!.role).toBe(Role.LIBERO);
      persistence.delete_team(teams[HOME], tmp_dir);
      expect(persistence.load_teams(tmp_dir).map((t) => t.name)).toEqual(["Away"]);
    });
  });

  test("test_name_sanitization", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      const weird = make_team("A/B: C?", [make_player(1, "X")]);
      const path = persistence.save_team(weird, tmp_dir);
      expect(existsSync(path)).toBe(true);
      const loaded = persistence.load_teams(tmp_dir);
      expect(loaded[0]!.name).toBe("A/B: C?"); // name survives inside the JSON
    });
  });

  test("test_corrupt_file_skipped", () => {
    with_tmp_dir("persistence-test", (tmp_dir) => {
      writeFileSync(join(tmp_dir, "broken.json"), "{ not json", "utf8");
      persistence.save_team(make_team("OK"), tmp_dir);
      expect(persistence.load_teams(tmp_dir).map((t) => t.name)).toEqual(["OK"]);
    });
  });
});
