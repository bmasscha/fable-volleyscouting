import "fake-indexeddb/auto";

import { beforeEach, describe, expect, test } from "vitest";

import { MatchSnapshot } from "../src/browserStorage";
import {
  deleteMatch,
  getMatch,
  getVideoLink,
  listMatches,
  putMatch,
  saveVideoLink,
} from "../src/matchStore";
import { default_config, make_player, make_team } from "../src/core/models";
import { FILE, YOUTUBE, video_link } from "../src/core/videoSync";

function snapshot(id: string, overrides: Partial<MatchSnapshot> = {}): MatchSnapshot {
  return {
    id,
    createdAt: 1000,
    config: default_config(),
    teams: {
      home: make_team("Home", [make_player(1, "A", undefined, "h1")]),
      away: make_team("Away", [make_player(2, "B", undefined, "a1")]),
    },
    events: [],
    lastWarnings: [],
    switchSides: true,
    savedAt: 2000,
    ...overrides,
  };
}

// The in-memory fake DB persists across tests in a file; start each test empty.
beforeEach(async () => {
  for (const meta of await listMatches()) {
    await deleteMatch(meta.id);
  }
});

describe("match archive (IndexedDB)", () => {
  test("put then get round-trips a match", async () => {
    await putMatch(snapshot("a", { switchSides: false }));

    const loaded = await getMatch("a");
    expect(loaded?.id).toBe("a");
    expect(loaded?.teams.home.name).toBe("Home");
    expect(loaded?.switchSides).toBe(false);
  });

  test("get returns null for an unknown id", async () => {
    expect(await getMatch("missing")).toBeNull();
  });

  test("list returns meta for every match, newest updated first", async () => {
    await putMatch(snapshot("old", { savedAt: 100 }));
    await putMatch(snapshot("new", { savedAt: 900 }));

    const metas = await listMatches();
    expect(metas.map((m) => m.id)).toEqual(["new", "old"]);
    expect(metas[0]!.homeName).toBe("Home");
    expect(metas[0]!.awayName).toBe("Away");
  });

  test("put overwrites the record with the same id", async () => {
    await putMatch(snapshot("a", { savedAt: 100 }));
    await putMatch(snapshot("a", { savedAt: 500 }));

    const metas = await listMatches();
    expect(metas).toHaveLength(1);
    expect(metas[0]!.updatedAt).toBe(500);
  });

  test("delete removes a match", async () => {
    await putMatch(snapshot("a"));
    await deleteMatch("a");

    expect(await getMatch("a")).toBeNull();
    expect(await listMatches()).toHaveLength(0);
  });

  test("meta reports the event count", async () => {
    await putMatch(snapshot("a"));
    const metas = await listMatches();
    expect(metas[0]!.eventCount).toBe(0);
    expect(metas[0]!.finished).toBe(false);
  });
});

describe("video links", () => {
  test("get returns null when none is stored", async () => {
    expect(await getVideoLink("nope")).toBeNull();
  });

  test("save then get round-trips a link with anchors", async () => {
    const link = video_link(YOUTUBE, "dQw4w9WgXcQ", [
      { event_ts: 1000, video_seconds: 12 },
    ]);
    await saveVideoLink("match-a", link);
    const loaded = await getVideoLink("match-a");
    expect(loaded?.source_kind).toBe(YOUTUBE);
    expect(loaded?.source_ref).toBe("dQw4w9WgXcQ");
    expect(loaded?.anchors).toEqual([{ event_ts: 1000, video_seconds: 12 }]);
  });

  test("save overwrites the link for the same match", async () => {
    await saveVideoLink("match-b", video_link(FILE, "old.mp4"));
    await saveVideoLink("match-b", video_link(FILE, "new.mp4"));
    const loaded = await getVideoLink("match-b");
    expect(loaded?.source_ref).toBe("new.mp4");
  });
});
