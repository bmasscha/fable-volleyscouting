import { afterEach, beforeEach, describe, expect, test } from "vitest";

import { clearAutosave, loadAutosave, loadRosterLibrary, saveAutosave, saveRosterLibrary, AUTOSAVE_KEY, ROSTER_LIBRARY_KEY } from "../src/browserStorage";
import { default_config, make_player, make_team } from "../src/core/models";

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
      switchSides: false,
      savedAt: null,
    });
    const stored = JSON.parse(localStorage.getItem(AUTOSAVE_KEY)!);
    delete stored.switchSides;
    localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(stored));

    expect(loadAutosave()?.switchSides).toBe(true);
  });
});
