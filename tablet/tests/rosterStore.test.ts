import "fake-indexeddb/auto";

import { beforeEach, describe, expect, test } from "vitest";

import {
  loadRosterLibraryIdb,
  saveRosterLibraryIdb,
  requestPersistentStorage,
} from "../src/rosterStore";
import { openDb, ROSTER_STORE } from "../src/matchStore";
import { make_player, make_team } from "../src/core/models";

// The fake DB persists across tests; clear the roster store before each.
beforeEach(async () => {
  const db = await openDb();
  const tx = db.transaction(ROSTER_STORE, "readwrite");
  tx.objectStore(ROSTER_STORE).clear();
  await new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
});

describe("durable team library (IndexedDB)", () => {
  test("returns null before anything is stored", async () => {
    expect(await loadRosterLibraryIdb()).toBeNull();
  });

  test("save then load round-trips the library", async () => {
    const teams = [
      make_team("Alpha", [make_player(2, "Two", "outside", "a1")], "#202020"),
      make_team("Zeta", [make_player(1, "One", "setter", "z1")], "#101010"),
    ];

    expect(await saveRosterLibraryIdb(teams)).toBe(true);

    const loaded = await loadRosterLibraryIdb();
    expect(loaded?.map((t) => t.name)).toEqual(["Alpha", "Zeta"]);
    expect(loaded?.[0]!.players[0]!.id).toBe("a1");
    expect(loaded?.[1]!.color).toBe("#101010");
  });

  test("save overwrites the single library record", async () => {
    await saveRosterLibraryIdb([make_team("Alpha", [])]);
    await saveRosterLibraryIdb([make_team("Beta", []), make_team("Gamma", [])]);

    const loaded = await loadRosterLibraryIdb();
    expect(loaded?.map((t) => t.name)).toEqual(["Beta", "Gamma"]);
  });

  test("an empty library is stored (not treated as absent)", async () => {
    await saveRosterLibraryIdb([]);
    expect(await loadRosterLibraryIdb()).toEqual([]);
  });

  test("requestPersistentStorage never throws without the storage API", async () => {
    // node/jsdom test env has no navigator.storage.persist -> returns false.
    await expect(requestPersistentStorage()).resolves.toBe(false);
  });
});
