import "fake-indexeddb/auto";

import { beforeEach, describe, expect, test, vi } from "vitest";

import { make_player, make_team } from "../src/core/models";
import { MatchSnapshot, newMatchId } from "../src/browserStorage";
import { default_config } from "../src/core/models";
import {
  isWorkspacePickerSupported,
  readFullWorkspaceState,
  readWorkspaceMatches,
  readWorkspaceTeams,
  writeWorkspaceMatch,
  writeWorkspaceTeams,
} from "../src/workspaceStore";
import { FsDirectoryHandle } from "../src/fsAccess";

function createMockDirectory(): { handle: FsDirectoryHandle; files: Map<string, string> } {
  const files = new Map<string, string>();
  const subdirs = new Map<string, ReturnType<typeof createMockDirectory>>();

  const dirHandle = {
    name: "FableScouterData",
    keys: async function* () {
      for (const key of files.keys()) {
        yield key;
      }
    },
    getFileHandle: vi.fn(async (name: string, options?: { create?: boolean }) => {
      if (!files.has(name) && !options?.create) {
        throw new Error(`File not found: ${name}`);
      }
      return {
        createWritable: vi.fn(async () => {
          let buffer = "";
          return {
            write: vi.fn(async (chunk: string) => {
              buffer += chunk;
            }),
            close: vi.fn(async () => {
              files.set(name, buffer);
            }),
          };
        }),
        getFile: vi.fn(async () => ({
          text: vi.fn(async () => files.get(name) ?? ""),
        })),
      };
    }),
    getDirectoryHandle: vi.fn(async (name: string, options?: { create?: boolean }) => {
      if (!subdirs.has(name)) {
        if (!options?.create) {
          throw new Error(`Subdirectory not found: ${name}`);
        }
        subdirs.set(name, createMockDirectory());
      }
      return subdirs.get(name)!.handle;
    }),
    removeEntry: vi.fn(async (name: string) => {
      files.delete(name);
    }),
    queryPermission: vi.fn(async () => "granted"),
    requestPermission: vi.fn(async () => "granted"),
  };

  return { handle: dirHandle as unknown as FsDirectoryHandle, files };
}

describe("workspaceStore engine", () => {
  test("isWorkspacePickerSupported returns false in default node env", () => {
    expect(isWorkspacePickerSupported()).toBe(false);
  });

  test("writeWorkspaceTeams and readWorkspaceTeams round-trip teams in rosters/ subfolder", async () => {
    const mock = createMockDirectory();
    const team1 = make_team("Alpha", [make_player(1, "Player 1")]);
    const team2 = make_team("Beta", [make_player(2, "Player 2")]);

    const written = await writeWorkspaceTeams(mock.handle, [team1, team2]);
    expect(written).toBe(true);

    const readBack = await readWorkspaceTeams(mock.handle);
    expect(readBack.map((t) => t.name).sort()).toEqual(["Alpha", "Beta"]);
  });

  test("writeWorkspaceMatch and readWorkspaceMatches round-trip matches in matches/ subfolder", async () => {
    const mock = createMockDirectory();
    const snapshot: MatchSnapshot = {
      id: newMatchId(),
      createdAt: Date.now(),
      config: default_config(),
      teams: {
        home: make_team("Home", [make_player(1, "H1")]),
        away: make_team("Away", [make_player(2, "A1")]),
      },
      events: [],
      lastWarnings: [],
      switchSides: true,
      savedAt: Date.now(),
    };

    const written = await writeWorkspaceMatch(mock.handle, snapshot);
    expect(written).toBe(true);

    const matches = await readWorkspaceMatches(mock.handle);
    expect(matches.length).toBe(1);
    expect(matches[0].id).toBe(snapshot.id);
    expect(matches[0].teams.home.name).toBe("Home");
  });

  test("writeWorkspaceTeams keeps a team file not in the library (e.g. hand-copied)", async () => {
    const mock = createMockDirectory();
    const alpha = make_team("Alpha", [make_player(1, "Player 1")]);
    const beta = make_team("Beta", [make_player(2, "Player 2")]);
    // Beta lands in the folder (stand-in for a roster copied straight into rosters/).
    await writeWorkspaceTeams(mock.handle, [alpha, beta]);

    // A later save of only Alpha, WITHOUT marking Beta removed, must not delete Beta.
    await writeWorkspaceTeams(mock.handle, [alpha]);

    const readBack = await readWorkspaceTeams(mock.handle);
    expect(readBack.map((t) => t.name).sort()).toEqual(["Alpha", "Beta"]);
  });

  test("writeWorkspaceTeams removes only teams explicitly marked as removed", async () => {
    const mock = createMockDirectory();
    const alpha = make_team("Alpha", [make_player(1, "Player 1")]);
    const beta = make_team("Beta", [make_player(2, "Player 2")]);
    await writeWorkspaceTeams(mock.handle, [alpha, beta]);

    await writeWorkspaceTeams(mock.handle, [alpha], [beta]);

    const readBack = await readWorkspaceTeams(mock.handle);
    expect(readBack.map((t) => t.name)).toEqual(["Alpha"]);
  });

  test("readFullWorkspaceState scans both root directory and subdirectories", async () => {
    const mock = createMockDirectory();
    const team = make_team("RootTeam", [make_player(1, "R1")]);
    const snapshot: MatchSnapshot = {
      id: newMatchId(),
      createdAt: Date.now(),
      config: default_config(),
      teams: {
        home: team,
        away: make_team("Opponent", [make_player(2, "O1")]),
      },
      events: [],
      lastWarnings: [],
      switchSides: true,
      savedAt: Date.now(),
    };

    // Write team and match into subfolders
    await writeWorkspaceTeams(mock.handle, [team]);
    await writeWorkspaceMatch(mock.handle, snapshot);

    const state = await readFullWorkspaceState(mock.handle);
    expect(state.teams.length).toBe(1);
    expect(state.teams[0].name).toBe("RootTeam");
    expect(state.matches.length).toBe(1);
    expect(state.matches[0].id).toBe(snapshot.id);
  });
});
