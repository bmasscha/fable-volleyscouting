// Durable team-library storage backed by IndexedDB.
//
// localStorage (browserStorage.ts) remains the synchronous fast cache the UI
// paints from on mount; this store is the durable copy in the same
// "fable-scouter" IndexedDB the match archive uses. IndexedDB has a far larger
// quota than localStorage and, together with navigator.storage.persist(),
// resists automatic eviction under storage pressure. (Neither survives a manual
// "clear browsing data" -- that is what the workspace folder / exported backup
// files are for; see workspaceStore.ts.)

import { Team, team_from_dict, team_to_dict } from "./core/models";
import { ROSTER_STORE, openDb, requestResult, txDone } from "./matchStore";

// Single record holding the whole library, keyed by a constant id.
const LIBRARY_ID = "library";

interface RosterLibraryRecord {
  id: string;
  teams: Record<string, unknown>[];
}

/** Load the durable team library, or null when none has been stored yet (so the
 * caller can fall back to / migrate the localStorage copy). Never throws: a
 * corrupt record or an unavailable DB yields null rather than blocking startup. */
export async function loadRosterLibraryIdb(): Promise<Team[] | null> {
  try {
    const db = await openDb();
    const tx = db.transaction(ROSTER_STORE, "readonly");
    const record = (await requestResult(tx.objectStore(ROSTER_STORE).get(LIBRARY_ID))) as
      | RosterLibraryRecord
      | undefined;
    if (record == null || !Array.isArray(record.teams)) {
      return null;
    }
    return record.teams.map((team) => team_from_dict(team));
  } catch (error) {
    console.warn("Durable team library is unavailable for reads.", error);
    return null;
  }
}

/** Upsert the whole team library. Returns whether the write succeeded. */
export async function saveRosterLibraryIdb(teams: Team[]): Promise<boolean> {
  try {
    const db = await openDb();
    const record: RosterLibraryRecord = {
      id: LIBRARY_ID,
      teams: teams.map((team) => team_to_dict(team)),
    };
    const tx = db.transaction(ROSTER_STORE, "readwrite");
    tx.objectStore(ROSTER_STORE).put(record);
    await txDone(tx);
    return true;
  } catch (error) {
    console.warn("Durable team library is unavailable for writes.", error);
    return false;
  }
}

/** Ask the browser to keep this origin's storage persistent (won't be evicted
 * automatically). Best-effort and idempotent; returns the resulting state.
 * Installed PWAs are commonly granted this without a prompt. */
export async function requestPersistentStorage(): Promise<boolean> {
  try {
    const storage = navigator.storage;
    if (storage?.persist == null) {
      return false;
    }
    if (storage.persisted != null && (await storage.persisted())) {
      return true;
    }
    return await storage.persist();
  } catch (error) {
    console.warn("Persistent-storage request failed.", error);
    return false;
  }
}
