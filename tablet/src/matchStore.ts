// Durable, offline match archive backed by IndexedDB.
//
// The live autosave (browserStorage.ts) is a single localStorage slot -- a
// crash buffer for the *current* match. This store is the permanent library:
// one record per match keyed by its stable id, so a scout can keep many games,
// reopen any of them, and never have a new game silently overwrite an old one.
//
// A tiny hand-rolled promise wrapper is used deliberately (no idb/idb-keyval
// dependency) to keep the fully-offline PWA bundle unchanged.

import { MatchEngine } from "./core/engine";
import { Phase } from "./core/engine";
import { AWAY, HOME } from "./core/models";
import {
  MatchSnapshot,
  fromStoredSnapshot,
  toStoredSnapshot,
} from "./browserStorage";

const DB_NAME = "fable-scouter";
const DB_VERSION = 1;
const STORE = "matches";

/** Lightweight listing row -- everything the Saved-matches screen needs
 * without deserializing the whole event log. Derived and denormalized at
 * write time. */
export interface MatchMeta {
  id: string;
  homeName: string;
  awayName: string;
  createdAt: number;
  updatedAt: number;
  eventCount: number;
  setNumber: number;
  homeSets: number;
  awaySets: number;
  finished: boolean;
}

interface MatchRecord {
  id: string;
  meta: MatchMeta;
  stored: ReturnType<typeof toStoredSnapshot>;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise != null) {
    return dbPromise;
  }
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  // A failed open must not be cached, or every later call rejects too.
  dbPromise.catch(() => {
    dbPromise = null;
  });
  return dbPromise;
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function txDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

/** Replay the match to summarize it for the listing. Best-effort: a snapshot
 * that fails to replay still lists (with a zeroed score) rather than vanishing. */
function deriveMeta(snapshot: MatchSnapshot): MatchMeta {
  const engine = new MatchEngine(snapshot.config, snapshot.teams);
  let finished = false;
  let setNumber = 0;
  let homeSets = 0;
  let awaySets = 0;
  try {
    engine.load_events(snapshot.events);
    finished = engine.state.phase === Phase.MATCH_OVER;
    setNumber = engine.state.set_number;
    homeSets = engine.state.scores[HOME];
    awaySets = engine.state.scores[AWAY];
  } catch {
    // keep the best-effort defaults
  }
  return {
    id: snapshot.id,
    homeName: snapshot.teams[HOME].name,
    awayName: snapshot.teams[AWAY].name,
    createdAt: snapshot.createdAt,
    updatedAt: snapshot.savedAt ?? Date.now(),
    eventCount: snapshot.events.length,
    setNumber,
    homeSets,
    awaySets,
    finished,
  };
}

/** Insert or update the match keyed by its id. */
export async function putMatch(snapshot: MatchSnapshot): Promise<void> {
  const db = await openDb();
  const record: MatchRecord = {
    id: snapshot.id,
    meta: deriveMeta(snapshot),
    stored: toStoredSnapshot(snapshot),
  };
  const tx = db.transaction(STORE, "readwrite");
  tx.objectStore(STORE).put(record);
  await txDone(tx);
}

/** Load one match, or null if it is absent / corrupt. */
export async function getMatch(id: string): Promise<MatchSnapshot | null> {
  const db = await openDb();
  const tx = db.transaction(STORE, "readonly");
  const record = (await requestResult(tx.objectStore(STORE).get(id))) as
    | MatchRecord
    | undefined;
  if (record == null) {
    return null;
  }
  try {
    return fromStoredSnapshot(record.stored);
  } catch {
    return null;
  }
}

/** List every saved match, most recently updated first. */
export async function listMatches(): Promise<MatchMeta[]> {
  const db = await openDb();
  const tx = db.transaction(STORE, "readonly");
  const records = (await requestResult(tx.objectStore(STORE).getAll())) as MatchRecord[];
  return records
    .map((record) => record.meta)
    .sort((a, b) => b.updatedAt - a.updatedAt);
}

/** Remove a match from the archive. */
export async function deleteMatch(id: string): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(STORE, "readwrite");
  tx.objectStore(STORE).delete(id);
  await txDone(tx);
}
