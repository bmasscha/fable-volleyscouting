import "fake-indexeddb/auto";

import { beforeEach, describe, expect, test, vi } from "vitest";

import {
  exportFullAppBackupJson,
  importFullAppBackupJson,
  restoreFullAppBackup,
} from "../src/backupStore";
import { default_config, make_player, make_team } from "../src/core/models";
import { openDb, loadAllMatches } from "../src/matchStore";
import { loadRosterLibraryIdb } from "../src/rosterStore";
import { MatchSnapshot, newMatchId } from "../src/browserStorage";
import { SystemSpec } from "../src/core/systems";

import { SYSTEMS } from "../src/core/systems";

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

// Clear IndexedDB and mock localStorage before each test
beforeEach(async () => {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: new FakeStorage(),
  });

  const db = await openDb();
  for (const storeName of ["matches", "rosters", "videoLinks"]) {
    const tx = db.transaction(storeName, "readwrite");
    tx.objectStore(storeName).clear();
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }
});

function sampleSnapshot(): MatchSnapshot {
  const home = make_team("Home Team", [make_player(1, "Player 1")]);
  const away = make_team("Away Team", [make_player(2, "Player 2")]);
  return {
    id: newMatchId(),
    createdAt: Date.now(),
    config: default_config(),
    teams: { home, away },
    events: [],
    lastWarnings: [],
    switchSides: true,
    savedAt: Date.now(),
  };
}

describe("full application backup and restore", () => {
  test("export and import round-trips full application state", () => {
    const snapshot = sampleSnapshot();
    const team = make_team("Roster Team", [make_player(5, "Five")]);
    const userSystem: SystemSpec = SYSTEMS["6-6"];

    const json = exportFullAppBackupJson([snapshot], [team], [userSystem]);
    const imported = importFullAppBackupJson(json);

    expect(imported.version).toBe(1);
    expect(imported.app).toBe("fable-scouter-tablet");
    expect(imported.type).toBe("full-app-backup");
    expect(imported.matches.length).toBe(1);
    expect(imported.matches[0].id).toBe(snapshot.id);
    expect(imported.rosterLibrary.length).toBe(1);
    expect(imported.rosterLibrary[0].name).toBe("Roster Team");
    expect(imported.userSystems.length).toBe(1);
    expect(imported.userSystems[0].id).toBe("6-6");
  });

  test("importFullAppBackupJson throws on invalid input", () => {
    expect(() => importFullAppBackupJson("not json")).toThrow();
    expect(() => importFullAppBackupJson("{}")).toThrow("missing matches or roster library");
  });

  test("restoreFullAppBackup persists matches and rosters to IndexedDB", async () => {
    const snapshot = sampleSnapshot();
    const team = make_team("Durable Team", []);
    const backup = {
      version: 1 as const,
      app: "fable-scouter-tablet" as const,
      type: "full-app-backup" as const,
      exportedAt: Date.now(),
      matches: [snapshot],
      rosterLibrary: [team],
      userSystems: [],
      videoLinks: {},
    };

    const result = await restoreFullAppBackup(backup);
    expect(result.matchCount).toBe(1);
    expect(result.teamCount).toBe(1);

    const matches = await loadAllMatches();
    expect(matches.length).toBe(1);
    expect(matches[0].id).toBe(snapshot.id);

    const rosters = await loadRosterLibraryIdb();
    expect(rosters?.length).toBe(1);
    expect(rosters?.[0].name).toBe("Durable Team");
  });
});
