// Structural types for the File System Access API bits the workspace engine
// uses. The installed TS DOM lib does not always declare showDirectoryPicker or
// the permission methods, so we keep our own narrow surface here. The workspace
// folder engine (workspaceStore.ts) is the sole consumer.

export type PermissionState = "granted" | "denied" | "prompt";

export interface PermissionDescriptor {
  mode?: "read" | "readwrite";
}

export interface FsWritable {
  write(data: string): Promise<void>;
  close(): Promise<void>;
}

export interface FsFileHandle {
  createWritable(): Promise<FsWritable>;
  getFile(): Promise<{ text(): Promise<string> }>;
}

export interface FsDirectoryHandle {
  name: string;
  keys(): AsyncIterableIterator<string>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FsFileHandle>;
  removeEntry(name: string, options?: { recursive?: boolean }): Promise<void>;
  queryPermission?(descriptor?: PermissionDescriptor): Promise<PermissionState>;
  requestPermission?(descriptor?: PermissionDescriptor): Promise<PermissionState>;
}
