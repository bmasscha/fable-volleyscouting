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
import { ROSTER_STORE, openDb, requestResult, txDone } from "./matchStore";
import { FsDirectoryHandle } from "./rosterFileSync";

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

export async function ensureWritePermission(handle: FsDirectoryHandle): Promise<boolean> {
  const descriptor = { mode: "readwrite" as const };
  if (handle.queryPermission != null) {
    if ((await handle.queryPermission(descriptor)) === "granted") {
      return true;
    }
  }
  if (handle.requestPermission != null) {
    return (await handle.requestPermission(descriptor)) === "granted";
  }
  return true;
}

/** Ensure subdirectories rosters/, matches/, systems/ exist in the root folder. */
export async function ensureWorkspaceSubfolders(root: FsDirectoryHandle): Promise<void> {
  if (!(await ensureWritePermission(root))) {
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
export async function writeWorkspaceTeams(root: FsDirectoryHandle, teams: Team[]): Promise<boolean> {
  if (!(await ensureWritePermission(root))) {
    return false;
  }
  const folder = await getSubfolder(root, "rosters", true);
  if (folder == null) {
    return false;
  }

  const wanted = new Map<string, Team>();
  for (const team of teams) {
    wanted.set(teamExportFilename(team), team);
  }

  // Write/update current teams
  for (const [filename, team] of wanted) {
    const fileHandle = await folder.getFileHandle(filename, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(exportTeamJson(team));
    await writable.close();
  }

  // Remove stale team files
  const stale: string[] = [];
  for await (const name of folder.keys()) {
    if (wanted.has(name) || !name.toLowerCase().endsWith(".json")) {
      continue;
    }
    try {
      const file = await (await folder.getFileHandle(name)).getFile();
      importTeamsFromJson(await file.text());
      stale.push(name);
    } catch {
      // non-team JSON
    }
  }
  for (const name of stale) {
    await folder.removeEntry(name);
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
  if (!(await ensureWritePermission(root))) {
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
  if (!(await ensureWritePermission(root))) {
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
  if (!(await ensureWritePermission(root))) {
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

// ------------------------------------------------------------- Full Read
export async function readFullWorkspaceState(root: FsDirectoryHandle): Promise<WorkspaceData> {
  const [teams, matches, systems] = await Promise.all([
    readWorkspaceTeams(root),
    readWorkspaceMatches(root),
    readWorkspaceSystems(root),
  ]);
  return { teams, matches, systems };
}
