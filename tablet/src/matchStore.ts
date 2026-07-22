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
import {
  VideoLink,
  video_link_from_dict,
  video_link_to_dict,
} from "./core/videoSync";

const DB_NAME = "fable-scouter";
const DB_VERSION = 3;
const STORE = "matches";
const VIDEO_STORE = "videoLinks";
/** Roster library + linked-folder handle. Shared with rosterStore.ts /
 * rosterFileSync.ts, which open the same DB via the exported openDb(). */
export const ROSTER_STORE = "rosters";

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

export function openDb(): Promise<IDBDatabase> {
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
      // v2: per-match video links for the review tool (keyed by match id).
      if (!db.objectStoreNames.contains(VIDEO_STORE)) {
        db.createObjectStore(VIDEO_STORE, { keyPath: "id" });
      }
      // v3: durable team library + the linked roster-folder handle.
      if (!db.objectStoreNames.contains(ROSTER_STORE)) {
        db.createObjectStore(ROSTER_STORE, { keyPath: "id" });
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

export function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export function txDone(tx: IDBTransaction): Promise<void> {
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

/** Load all full match snapshots from the archive. */
export async function loadAllMatches(): Promise<MatchSnapshot[]> {
  const db = await openDb();
  const tx = db.transaction(STORE, "readonly");
  const records = (await requestResult(tx.objectStore(STORE).getAll())) as MatchRecord[];
  const matches: MatchSnapshot[] = [];
  for (const record of records) {
    try {
      matches.push(fromStoredSnapshot(record.stored));
    } catch {
      // skip corrupt
    }
  }
  return matches;
}

/** Insert or update a batch of matches. */
export async function putMatches(snapshots: MatchSnapshot[]): Promise<void> {
  if (snapshots.length === 0) {
    return;
  }
  const db = await openDb();
  const tx = db.transaction(STORE, "readwrite");
  const store = tx.objectStore(STORE);
  for (const snapshot of snapshots) {
    const record: MatchRecord = {
      id: snapshot.id,
      meta: deriveMeta(snapshot),
      stored: toStoredSnapshot(snapshot),
    };
    store.put(record);
  }
  await txDone(tx);
}

// ------------------------------------------------------------- video links
//
// The video-review route stores, per match, which video it is bound to and the
// sync anchors. A YouTube source_ref (the video id) persists fully; for a local
// file only the name is kept for display -- the file itself is re-picked each
// session (browsers cannot silently reopen a local file), while the anchors
// remain valid.

interface VideoLinkRecord {
  id: string;
  link: Record<string, unknown>;
}

/** Save (upsert) the video link for a match. */
export async function saveVideoLink(matchId: string, link: VideoLink): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(VIDEO_STORE, "readwrite");
  tx.objectStore(VIDEO_STORE).put({ id: matchId, link: video_link_to_dict(link) });
  await txDone(tx);
}

/** Load the video link for a match, or null if none is stored / it is corrupt. */
export async function getVideoLink(matchId: string): Promise<VideoLink | null> {
  const db = await openDb();
  const tx = db.transaction(VIDEO_STORE, "readonly");
  const record = (await requestResult(tx.objectStore(VIDEO_STORE).get(matchId))) as
    | VideoLinkRecord
    | undefined;
  if (record == null) {
    return null;
  }
  try {
    return video_link_from_dict(record.link);
  } catch {
    return null;
  }
}

/** Load all stored video links keyed by match id. */
export async function getAllVideoLinks(): Promise<Record<string, VideoLink>> {
  const db = await openDb();
  const tx = db.transaction(VIDEO_STORE, "readonly");
  const records = (await requestResult(tx.objectStore(VIDEO_STORE).getAll())) as VideoLinkRecord[];
  const result: Record<string, VideoLink> = {};
  for (const record of records) {
    try {
      result[record.id] = video_link_from_dict(record.link);
    } catch {
      // skip unparseable
    }
  }
  return result;
}

/** Save a batch of video links keyed by match id. */
export async function saveVideoLinksBatch(links: Record<string, VideoLink>): Promise<void> {
  const entries = Object.entries(links);
  if (entries.length === 0) {
    return;
  }
  const db = await openDb();
  const tx = db.transaction(VIDEO_STORE, "readwrite");
  const store = tx.objectStore(VIDEO_STORE);
  for (const [id, link] of entries) {
    store.put({ id, link: video_link_to_dict(link) });
  }
  await txDone(tx);
}

