import { afterEach, beforeEach, describe, expect, test } from "vitest";

import {
  clearAutosave,
  exportMatchJson,
  importMatchJson,
  loadAutosave,
  loadRosterLibrary,
  matchExportFilename,
  saveAutosave,
  saveRosterLibrary,
  exportRosterLibraryJson,
  exportTeamJson,
  teamExportFilename,
  importTeamsFromJson,
  AUTOSAVE_KEY,
  ROSTER_LIBRARY_KEY,
  type MatchSnapshot,
} from "../src/browserStorage";
import {
  HOME,
  AWAY,
  Rating,
  config_to_dict,
  default_config,
  make_player,
  make_team,
  team_to_dict,
} from "../src/core/models";
import { ServeEvent } from "../src/core/events";

function sampleSnapshot(overrides: Partial<MatchSnapshot> = {}): MatchSnapshot {
  const serve: ServeEvent = {
    type: "serve",
    ts: 12.5,
    team: HOME,
    player_id: "h1",
    rating: Rating.PERFECT,
  };
  return {
    id: "sample",
    createdAt: 1000,
    config: default_config(),
    teams: {
      home: make_team("Home", [make_player(1, "A", undefined, "h1")]),
      away: make_team("Away", [make_player(2, "B", undefined, "a1")]),
    },
    events: [serve],
    lastWarnings: [],
    switchSides: true,
    savedAt: 2000,
    ...overrides,
  };
}

class FakeStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

beforeEach(() => {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: new FakeStorage(),
  });
});

afterEach(() => {
  Reflect.deleteProperty(globalThis, "localStorage");
});

describe("browser roster library storage", () => {
  test("seeds default teams on first load", () => {
    const teams = loadRosterLibrary();

    expect(teams.map((team) => team.name)).toEqual(["Away", "Home"]);
    expect(localStorage.getItem(ROSTER_LIBRARY_KEY)).not.toBeNull();
  });

  test("round-trips saved library", () => {
    saveRosterLibrary([
      make_team("Zeta", [make_player(1, "One", undefined, "z1")], "#101010"),
      make_team("Alpha", [make_player(2, "Two", undefined, "a1")], "#202020"),
    ]);

    const teams = loadRosterLibrary();

    expect(teams.map((team) => team.name)).toEqual(["Alpha", "Zeta"]);
    expect(teams[0]!.players[0]!.id).toBe("a1");
  });

  test("does not reseed an intentionally empty library", () => {
    localStorage.setItem(ROSTER_LIBRARY_KEY, JSON.stringify({ version: 1, teams: [] }));

    const teams = loadRosterLibrary();

    expect(teams).toEqual([]);
  });

  test("reports autosave storage failures", () => {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      writable: true,
      value: {
        getItem: () => null,
        setItem: () => {
          throw new Error("quota");
        },
        removeItem: () => {
          throw new Error("quota");
        },
      } satisfies Partial<Storage>,
    });

    const ok = saveAutosave({
      config: default_config(),
      teams: {
        home: make_team("Home", [make_player(1, "A", undefined, "h1")]),
        away: make_team("Away", [make_player(2, "B", undefined, "a1")]),
      },
      events: [],
      lastWarnings: [],
      id: "m1",
      createdAt: 0,
      switchSides: true,
      savedAt: null,
    });

    expect(ok).toBe(false);
    expect(clearAutosave()).toBe(false);
  });

  test("round-trips switchSides = false", () => {
    saveAutosave({
      config: default_config(),
      teams: {
        home: make_team("Home", [make_player(1, "A", undefined, "h1")]),
        away: make_team("Away", [make_player(2, "B", undefined, "a1")]),
      },
      events: [],
      lastWarnings: [],
      id: "m2",
      createdAt: 0,
      switchSides: false,
      savedAt: 123,
    });

    expect(loadAutosave()?.switchSides).toBe(false);
  });

  test("autosave from before switchSides defaults to switching sides", () => {
    saveAutosave({
      config: default_config(),
      teams: {
        home: make_team("Home", [make_player(1, "A", undefined, "h1")]),
        away: make_team("Away", [make_player(2, "B", undefined, "a1")]),
      },
      events: [],
      lastWarnings: [],
      id: "m3",
      createdAt: 0,
      switchSides: false,
      savedAt: null,
    });
    const stored = JSON.parse(localStorage.getItem(AUTOSAVE_KEY)!);
    delete stored.switchSides;
    localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(stored));

    expect(loadAutosave()?.switchSides).toBe(true);
  });

  test("autosave from before ids gains a durable id on load", () => {
    saveAutosave(sampleSnapshot());
    const stored = JSON.parse(localStorage.getItem(AUTOSAVE_KEY)!);
    delete stored.id;
    delete stored.createdAt;
    localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(stored));

    const loaded = loadAutosave();
    expect(typeof loaded?.id).toBe("string");
    expect(loaded!.id.length).toBeGreaterThan(0);
    // createdAt backfills from savedAt when absent
    expect(loaded?.createdAt).toBe(2000);
  });
});

describe("match export / import", () => {
  test("export produces a desktop-compatible payload that preserves ts", () => {
    const json = exportMatchJson(sampleSnapshot());
    const data = JSON.parse(json);

    expect(data.version).toBe(1);
    expect(data.config).toBeTypeOf("object");
    expect(Object.keys(data.teams)).toEqual([HOME, AWAY]);
    expect(data.events).toHaveLength(1);
    expect(data.events[0].ts).toBe(12.5);
    expect(data.app).toBe("fable-scouter-tablet");
  });

  test("import round-trips a match and assigns a fresh id", () => {
    const original = sampleSnapshot({ id: "original" });
    const imported = importMatchJson(exportMatchJson(original));

    expect(imported.id).not.toBe("original");
    expect(imported.id.length).toBeGreaterThan(0);
    expect(imported.teams[HOME].name).toBe("Home");
    expect(imported.events).toHaveLength(1);
    expect(imported.events[0]!.ts).toBe(12.5);
    expect(imported.switchSides).toBe(true);
  });

  test("import accepts a bare desktop file (no tablet extras)", () => {
    const desktopFile = JSON.stringify({
      version: 1,
      config: config_to_dict(default_config()),
      teams: {
        home: team_to_dict(make_team("H", [make_player(1, "A", undefined, "h1")])),
        away: team_to_dict(make_team("W", [make_player(2, "B", undefined, "a1")])),
      },
      events: [],
    });
    const imported = importMatchJson(desktopFile);
    expect(imported.switchSides).toBe(true);
    expect(imported.teams[AWAY].name).toBe("W");
  });

  test("import rejects malformed files", () => {
    expect(() => importMatchJson("{not json")).toThrow();
    expect(() => importMatchJson(JSON.stringify({ version: 1 }))).toThrow();
  });

  test("export filename combines team names and date", () => {
    const name = matchExportFilename(sampleSnapshot({ savedAt: Date.UTC(2026, 6, 20) }));
    expect(name).toMatch(/^Home-vs-Away-2026-07-\d\d\.fable\.json$/);
  });
});

describe("single-team (desktop) export / import", () => {
  const demoTeam = () =>
    make_team(
      "Demo Home",
      [
        make_player(1, "Anna", "setter", "h1"),
        make_player(3, "Cato", "middle", "h3"),
      ],
      "#ff0000",
    );

  test("exportTeamJson matches the desktop team dict, indent 1", () => {
    const team = demoTeam();
    const json = exportTeamJson(team);

    expect(JSON.parse(json)).toEqual(team_to_dict(team));
    // indent=1 like core/persistence.save_team (json.dumps(indent=1))
    expect(json).toContain('\n "name":');
  });

  test("teamExportFilename mirrors desktop _team_filename", () => {
    expect(teamExportFilename(make_team("Demo Home", []))).toBe("Demo Home.json");
    // illegal characters -> underscore; accented letters are kept (isalnum)
    expect(teamExportFilename(make_team("FC/Barça #1", []))).toBe("FC_Barça _1.json");
    expect(teamExportFilename(make_team("", []))).toBe("team.json");
  });

  test("importTeamsFromJson reads a single desktop team file", () => {
    const team = demoTeam();
    const teams = importTeamsFromJson(exportTeamJson(team));

    expect(teams).toHaveLength(1);
    expect(teams[0]!.name).toBe("Demo Home");
    expect(teams[0]!.players.map((p) => p.id)).toEqual(["h1", "h3"]);
  });

  test("importTeamsFromJson reads a tablet roster bundle", () => {
    const bundle = exportRosterLibraryJson([
      make_team("Alpha", [make_player(2, "Two", undefined, "a1")], "#202020"),
      make_team("Zeta", [make_player(1, "One", undefined, "z1")], "#101010"),
    ]);
    const teams = importTeamsFromJson(bundle);

    expect(teams.map((t) => t.name).sort()).toEqual(["Alpha", "Zeta"]);
  });

  test("importTeamsFromJson rejects unrelated JSON", () => {
    expect(() => importTeamsFromJson("{not json")).toThrow();
    expect(() => importTeamsFromJson(JSON.stringify({ hello: "world" }))).toThrow();
    expect(() => importTeamsFromJson(JSON.stringify(42))).toThrow();
  });
});
