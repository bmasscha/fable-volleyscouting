// Native Workspace Directory Engine for FableScouterData root workspace.
//
// Allows the user to select a single root directory on their tablet or computer
// (e.g. Documents/FableScouterData or Google Drive/FableScouter). Stores all data
// as standard desktop-compatible files in subdirectories:
//   - <Root>/rosters/*.json
//   - <Root>/matches/*.fable.json
//   - <Root>/systems/*.json
//
// Survives 100% of browser history / site data clear operations because the files
// live on real device/cloud disk storage outside the browser sandbox.

import { Team } from "./core/models";
import { SystemSpec } from "./core/systems";
import { deserialize_system, serialize_system } from "./core/user_systems";
import {
  MatchSnapshot,
  exportMatchJson,
  exportTeamJson,
  importMatchJson,
  importTeamsFromJson,
  matchExportFilename,
  teamExportFilename,
} from "./browserStorage";
import { importFullAppBackupJson } from "./backupStore";
import { ROSTER_STORE, openDb, requestResult, txDone } from "./matchStore";
import { FsDirectoryHandle } from "./fsAccess";

const WORKSPACE_HANDLE_ID = "workspace-root-handle";

interface WorkspaceHandleRecord {
  id: string;
  handle: FsDirectoryHandle;
}

export interface WorkspaceData {
  teams: Team[];
  matches: MatchSnapshot[];
  systems: SystemSpec[];
}

/** Check if showDirectoryPicker API is available in the current browser. */
export function isWorkspacePickerSupported(): boolean {
  return typeof (globalThis as { showDirectoryPicker?: unknown }).showDirectoryPicker === "function";
}

/** Load the stored root workspace directory handle from IndexedDB. */
export async function loadWorkspaceHandle(): Promise<FsDirectoryHandle | null> {
  try {
    const db = await openDb();
    const tx = db.transaction(ROSTER_STORE, "readonly");
    const record = (await requestResult(tx.objectStore(ROSTER_STORE).get(WORKSPACE_HANDLE_ID))) as
      | WorkspaceHandleRecord
      | undefined;
    return record?.handle ?? null;
  } catch (error) {
    console.warn("Could not load workspace handle.", error);
    return null;
  }
}

/** Store or remove the workspace directory handle in IndexedDB. */
export async function saveWorkspaceHandle(handle: FsDirectoryHandle | null): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(ROSTER_STORE, "readwrite");
  if (handle == null) {
    tx.objectStore(ROSTER_STORE).delete(WORKSPACE_HANDLE_ID);
  } else {
    tx.objectStore(ROSTER_STORE).put({ id: WORKSPACE_HANDLE_ID, handle });
  }
  await txDone(tx);
}

/** Get display name of currently linked workspace folder, or null if none linked. */
export async function getWorkspaceFolderName(): Promise<string | null> {
  const handle = await loadWorkspaceHandle();
  return handle?.name ?? null;
}

/** Prompt user to pick a workspace directory and save it. Returns folder name or null. */
export async function linkWorkspaceFolder(): Promise<string | null> {
  const picker = (globalThis as { showDirectoryPicker?: (opts?: unknown) => Promise<FsDirectoryHandle> }).showDirectoryPicker;
  if (picker == null) {
    return null;
  }
  try {
    const handle = await picker({ mode: "readwrite", id: "fable-scouter-workspace" });
    await saveWorkspaceHandle(handle);
    await ensureWorkspaceSubfolders(handle);
    return handle.name;
  } catch (error) {
    if ((error as { name?: string }).name === "AbortError") {
      return null; // User cancelled
    }
    console.warn("Could not link workspace folder.", error);
    return null;
  }
}

/** Unlink the workspace directory handle. Does not delete files on disk. */
export async function unlinkWorkspaceFolder(): Promise<void> {
  try {
    await saveWorkspaceHandle(null);
  } catch (error) {
    console.warn("Could not unlink workspace folder.", error);
  }
}

// ------------------------------------------------------- Session permission
//
// Permission is requested EXACTLY ONCE per page session, and only from a real
// user gesture (see requestWorkspaceAccess). Every background write then merely
// *queries* the grant — it never prompts. This is what stops Android from
// popping the "allow access?" dialog on nearly every scouting touch, which the
// old code caused by calling requestPermission() from each per-event write.
//
// When a background write finds permission is no longer granted it does not
// prompt (there is no user gesture to attach a prompt to). Instead it records a
// "flush pending" flag: the data is already safe in IndexedDB, and the UI
// surfaces a Reconnect action so the user can re-grant with one tap and flush
// everything back to the folder — so nothing is lost even if browsing data is
// later cleared.

let flushPending = false;

/** True when a background write was skipped because folder permission had
 * lapsed. The UI shows a "Reconnect workspace" action while this is set. */
export function isWorkspaceFlushPending(): boolean {
  return flushPending;
}

/** Clear the pending-flush flag (call after a successful reconnect + flush). */
export function clearWorkspaceFlushPending(): void {
  flushPending = false;
}

/** Query — never prompt — whether the handle currently holds readwrite access. */
async function hasWritePermission(handle: FsDirectoryHandle): Promise<boolean> {
  if (handle.queryPermission == null) {
    return true; // older implementations grant on pick
  }
  return (await handle.queryPermission({ mode: "readwrite" })) === "granted";
}

/** Gate a background write on an already-granted permission WITHOUT prompting.
 * On a lapsed grant it records the pending flush and returns false. */
async function guardWrite(handle: FsDirectoryHandle): Promise<boolean> {
  if (await hasWritePermission(handle)) {
    return true;
  }
  flushPending = true;
  return false;
}

/** Request readwrite permission. MUST be called from within a user gesture
 * (e.g. a button tap) — Android only shows/persists the grant with user
 * activation. Returns true when access is (already or newly) granted. */
export async function requestWorkspaceAccess(handle: FsDirectoryHandle): Promise<boolean> {
  if (await hasWritePermission(handle)) {
    return true;
  }
  if (handle.requestPermission == null) {
    return true;
  }
  return (await handle.requestPermission({ mode: "readwrite" })) === "granted";
}

/** Report whether a linked handle currently has access, without prompting.
 * Safe to call at startup (outside a user gesture). */
export async function workspaceAccessGranted(handle: FsDirectoryHandle): Promise<boolean> {
  return hasWritePermission(handle);
}

/** Ensure subdirectories rosters/, matches/, systems/ exist in the root folder. */
export async function ensureWorkspaceSubfolders(root: FsDirectoryHandle): Promise<void> {
  if (!(await hasWritePermission(root))) {
    return;
  }
  try {
    const subfolderPicker = (root as unknown as { getDirectoryHandle: (name: string, opts?: { create?: boolean }) => Promise<FsDirectoryHandle> });
    if (typeof subfolderPicker.getDirectoryHandle === "function") {
      await subfolderPicker.getDirectoryHandle("rosters", { create: true });
      await subfolderPicker.getDirectoryHandle("matches", { create: true });
      await subfolderPicker.getDirectoryHandle("systems", { create: true });
    }
  } catch (error) {
    console.warn("Could not create workspace subfolders.", error);
  }
}

export async function getSubfolder(root: FsDirectoryHandle, name: string, create = true): Promise<FsDirectoryHandle | null> {
  try {
    const dirPicker = (root as unknown as { getDirectoryHandle: (name: string, opts?: { create?: boolean }) => Promise<FsDirectoryHandle> });
    if (typeof dirPicker.getDirectoryHandle === "function") {
      return await dirPicker.getDirectoryHandle(name, { create });
    }
  } catch {
    // subfolder missing or inaccessible
  }
  return null;
}

// ------------------------------------------------------------- Rosters Sync
export async function writeWorkspaceTeams(
  root: FsDirectoryHandle,
  teams: Team[],
  removedTeams: Team[] = [],
): Promise<boolean> {
  if (teams.length === 0 && removedTeams.length === 0) {
    return true; // nothing to write and nothing to remove
  }
  if (!(await guardWrite(root))) {
    return false;
  }
  const folder = await getSubfolder(root, "rosters", true);
  if (folder == null) {
    return false;
  }

  // Write/update current teams (one <SafeName>.json per team, desktop shape).
  for (const team of teams) {
    const filename = teamExportFilename(team);
    const fileHandle = await folder.getFileHandle(filename, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(exportTeamJson(team));
    await writable.close();
  }

  // Only remove files for teams the user EXPLICITLY deleted in the app. Team
  // files added to the folder by hand (e.g. a roster copied in from elsewhere)
  // are never touched here — they are imported into the library on the next
  // scan instead of being silently deleted.
  for (const team of removedTeams) {
    try {
      await folder.removeEntry(teamExportFilename(team));
    } catch {
      // File already gone or never existed.
    }
  }
  return true;
}

export async function readWorkspaceTeams(root: FsDirectoryHandle): Promise<Team[]> {
  const folder = await getSubfolder(root, "rosters", false);
  if (folder == null) {
    return [];
  }
  const teams: Team[] = [];
  for await (const name of folder.keys()) {
    if (!name.toLowerCase().endsWith(".json")) {
      continue;
    }
    try {
      const file = await (await folder.getFileHandle(name)).getFile();
      teams.push(...importTeamsFromJson(await file.text()));
    } catch {
      // Skip non-team file
    }
  }
  return teams;
}

// ------------------------------------------------------------- Matches Sync
export async function writeWorkspaceMatch(root: FsDirectoryHandle, match: MatchSnapshot): Promise<boolean> {
  if (!(await guardWrite(root))) {
    return false;
  }
  const folder = await getSubfolder(root, "matches", true);
  if (folder == null) {
    return false;
  }
  const filename = matchExportFilename(match);
  const fileHandle = await folder.getFileHandle(filename, { create: true });
  const writable = await fileHandle.createWritable();
  await writable.write(exportMatchJson(match));
  await writable.close();
  return true;
}

export async function deleteWorkspaceMatch(root: FsDirectoryHandle, matchId: string): Promise<boolean> {
  if (!(await guardWrite(root))) {
    return false;
  }
  const folder = await getSubfolder(root, "matches", false);
  if (folder == null) {
    return false;
  }
  for await (const name of folder.keys()) {
    if (!name.toLowerCase().endsWith(".json")) {
      continue;
    }
    try {
      const file = await (await folder.getFileHandle(name)).getFile();
      const snapshot = importMatchJson(await file.text());
      if (snapshot.id === matchId) {
        await folder.removeEntry(name);
        return true;
      }
    } catch {
      // Skip non-match file
    }
  }
  return false;
}

export async function readWorkspaceMatches(root: FsDirectoryHandle): Promise<MatchSnapshot[]> {
  const folder = await getSubfolder(root, "matches", false);
  if (folder == null) {
    return [];
  }
  const matches: MatchSnapshot[] = [];
  for await (const name of folder.keys()) {
    if (!name.toLowerCase().endsWith(".json")) {
      continue;
    }
    try {
      const file = await (await folder.getFileHandle(name)).getFile();
      matches.push(importMatchJson(await file.text(), false));
    } catch {
      // Skip invalid match file
    }
  }
  return matches;
}

// ------------------------------------------------------------- Systems Sync
export async function writeWorkspaceSystems(root: FsDirectoryHandle, systems: SystemSpec[]): Promise<boolean> {
  if (systems.length === 0) {
    return true;
  }
  if (!(await guardWrite(root))) {
    return false;
  }
  const folder = await getSubfolder(root, "systems", true);
  if (folder == null) {
    return false;
  }
  for (const sys of systems) {
    const filename = `${sys.id}.json`;
    const fileHandle = await folder.getFileHandle(filename, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(JSON.stringify(serialize_system(sys), null, 1));
    await writable.close();
  }
  return true;
}

export async function readWorkspaceSystems(root: FsDirectoryHandle): Promise<SystemSpec[]> {
  const folder = await getSubfolder(root, "systems", false);
  if (folder == null) {
    return [];
  }
  const systems: SystemSpec[] = [];
  for await (const name of folder.keys()) {
    if (!name.toLowerCase().endsWith(".json")) {
      continue;
    }
    try {
      const file = await (await folder.getFileHandle(name)).getFile();
      const text = await file.text();
      systems.push(deserialize_system(JSON.parse(text)));
    } catch {
      // Skip unparseable
    }
  }
  return systems;
}

async function collectJsonFileTexts(dir: FsDirectoryHandle): Promise<string[]> {
  const texts: string[] = [];
  try {
    for await (const name of dir.keys()) {
      if (name.toLowerCase().endsWith(".json") || name.toLowerCase().endsWith(".fable.json")) {
        try {
          const file = await (await dir.getFileHandle(name)).getFile();
          texts.push(await file.text());
        } catch {
          // skip unreadable file
        }
      }
    }
  } catch {
    // skip unreadable dir
  }
  return texts;
}

// ------------------------------------------------------------- Full Read
export async function readFullWorkspaceState(root: FsDirectoryHandle): Promise<WorkspaceData> {
  const rosterFolder = await getSubfolder(root, "rosters", false);
  const matchFolder = await getSubfolder(root, "matches", false);
  const systemFolder = await getSubfolder(root, "systems", false);

  const sources: FsDirectoryHandle[] = [root];
  if (rosterFolder != null) sources.push(rosterFolder);
  if (matchFolder != null) sources.push(matchFolder);
  if (systemFolder != null) sources.push(systemFolder);

  const teamMap = new Map<string, Team>();
  const matchMap = new Map<string, MatchSnapshot>();
  const systemMap = new Map<string, SystemSpec>();

  for (const source of sources) {
    const fileTexts = await collectJsonFileTexts(source);
    for (const text of fileTexts) {
      // 1. Try full app backup package
      try {
        const fullBackup = importFullAppBackupJson(text);
        if (fullBackup.matches.length > 0 || fullBackup.rosterLibrary.length > 0) {
          for (const t of fullBackup.rosterLibrary) {
            teamMap.set(t.name, t);
          }
          for (const m of fullBackup.matches) {
            matchMap.set(m.id, m);
          }
          for (const s of fullBackup.userSystems) {
            systemMap.set(s.id, s);
          }
          continue;
        }
      } catch {
        // Not a full backup package
      }

      // 2. Try match snapshot
      try {
        const match = importMatchJson(text, false);
        matchMap.set(match.id, match);
        continue;
      } catch {
        // Not a match file
      }

      // 3. Try team roster file
      try {
        const teams = importTeamsFromJson(text);
        for (const t of teams) {
          teamMap.set(t.name, t);
        }
        continue;
      } catch {
        // Not a team file
      }

      // 4. Try custom system spec
      try {
        const sys = deserialize_system(JSON.parse(text));
        if (sys.id != null && typeof sys.id === "string") {
          systemMap.set(sys.id, sys);
        }
        continue;
      } catch {
        // Not a system spec
      }
    }
  }

  return {
    teams: Array.from(teamMap.values()),
    matches: Array.from(matchMap.values()),
    systems: Array.from(systemMap.values()),
  };
}
