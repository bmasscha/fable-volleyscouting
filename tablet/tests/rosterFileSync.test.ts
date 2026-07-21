import { describe, expect, test } from "vitest";

import {
  FsDirectoryHandle,
  readTeamsFromDir,
  writeTeamsToDir,
} from "../src/rosterFileSync";
import { make_player, make_team } from "../src/core/models";

// In-memory stand-in for a FileSystemDirectoryHandle: a filename -> text map
// with just the surface writeTeamsToDir / readTeamsFromDir touch.
class FakeDir implements FsDirectoryHandle {
  name = "rosters";
  files: Map<string, string>;

  constructor(initial: Record<string, string> = {}) {
    this.files = new Map(Object.entries(initial));
  }

  async *keys(): AsyncIterableIterator<string> {
    // Snapshot so callers may mutate the map while iterating.
    for (const key of [...this.files.keys()]) {
      yield key;
    }
  }

  async getFileHandle(name: string, options?: { create?: boolean }) {
    if (!this.files.has(name)) {
      if (!options?.create) {
        throw new Error(`missing file ${name}`);
      }
      this.files.set(name, "");
    }
    const files = this.files;
    return {
      getFile: async () => ({ text: async () => files.get(name)! }),
      createWritable: async () => {
        let buffer = "";
        return {
          write: async (data: string) => {
            buffer += data;
          },
          close: async () => {
            files.set(name, buffer);
          },
        };
      },
    };
  }

  async removeEntry(name: string): Promise<void> {
    this.files.delete(name);
  }
}

const teamA = () => make_team("Alpha", [make_player(1, "One", "setter", "a1")], "#111111");
const teamB = () => make_team("Beta", [make_player(2, "Two", "middle", "b1")], "#222222");

describe("roster folder sync (fake directory handle)", () => {
  test("writes one desktop-shaped file per team", async () => {
    const dir = new FakeDir();
    await writeTeamsToDir(dir, [teamA(), teamB()]);

    expect([...dir.files.keys()].sort()).toEqual(["Alpha.json", "Beta.json"]);
    const alpha = JSON.parse(dir.files.get("Alpha.json")!);
    expect(alpha).toEqual({
      name: "Alpha",
      color: "#111111",
      players: [{ id: "a1", number: 1, name: "One", role: "setter" }],
    });
  });

  test("updates an existing team file in place", async () => {
    const dir = new FakeDir();
    await writeTeamsToDir(dir, [teamA()]);
    const recolored = { ...teamA(), color: "#999999" };
    await writeTeamsToDir(dir, [recolored]);

    expect(JSON.parse(dir.files.get("Alpha.json")!).color).toBe("#999999");
  });

  test("removes the file of a team dropped from the library", async () => {
    const dir = new FakeDir();
    await writeTeamsToDir(dir, [teamA(), teamB()]);
    await writeTeamsToDir(dir, [teamA()]); // Beta removed

    expect([...dir.files.keys()]).toEqual(["Alpha.json"]);
  });

  test("leaves unrelated JSON in the folder untouched", async () => {
    const dir = new FakeDir({ "notes.json": JSON.stringify({ note: "keep me" }) });
    await writeTeamsToDir(dir, [teamA()]);

    expect(dir.files.has("notes.json")).toBe(true);
    expect(dir.files.has("Alpha.json")).toBe(true);
  });

  test("reads back team files and skips non-team / non-json", async () => {
    const dir = new FakeDir({ "notes.json": JSON.stringify({ note: 1 }), "readme.txt": "hi" });
    await writeTeamsToDir(dir, [teamA(), teamB()]);

    const teams = await readTeamsFromDir(dir);
    expect(teams.map((t) => t.name).sort()).toEqual(["Alpha", "Beta"]);
    expect(teams.find((t) => t.name === "Alpha")!.players[0]!.id).toBe("a1");
  });
});
