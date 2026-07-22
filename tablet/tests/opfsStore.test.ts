import { describe, expect, test, vi } from "vitest";

import {
  DEFAULT_OPFS_BACKUP_FILE,
  deleteOpfsBackup,
  isOpfsSupported,
  loadOpfsBackup,
  saveOpfsBackup,
} from "../src/opfsStore";

describe("OPFS store layer", () => {
  test("isOpfsSupported returns false when navigator.storage.getDirectory is missing", () => {
    // Default Node env without OPFS
    expect(isOpfsSupported()).toBe(false);
  });

  test("saveOpfsBackup returns false when OPFS is unsupported", async () => {
    const result = await saveOpfsBackup("test data");
    expect(result).toBe(false);
  });

  test("loadOpfsBackup returns null when OPFS is unsupported", async () => {
    const data = await loadOpfsBackup();
    expect(data).toBeNull();
  });

  test("deleteOpfsBackup returns false when OPFS is unsupported", async () => {
    const result = await deleteOpfsBackup();
    expect(result).toBe(false);
  });

  test("OPFS operations succeed when mock getDirectory is available", async () => {
    const memoryFiles = new Map<string, string>();

    const fakeDirHandle = {
      getFileHandle: vi.fn(async (name: string, options?: { create?: boolean }) => {
        if (!memoryFiles.has(name) && !options?.create) {
          throw new Error("File not found");
        }
        return {
          createWritable: vi.fn(async () => {
            let buffer = "";
            return {
              write: vi.fn(async (chunk: string) => {
                buffer += chunk;
              }),
              close: vi.fn(async () => {
                memoryFiles.set(name, buffer);
              }),
            };
          }),
          getFile: vi.fn(async () => ({
            text: vi.fn(async () => memoryFiles.get(name) ?? ""),
          })),
        };
      }),
      removeEntry: vi.fn(async (name: string) => {
        if (!memoryFiles.has(name)) {
          throw new Error("File not found");
        }
        memoryFiles.delete(name);
      }),
    };

    vi.stubGlobal("navigator", {
      storage: {
        getDirectory: vi.fn(async () => fakeDirHandle),
      },
    });

    expect(isOpfsSupported()).toBe(true);

    const saved = await saveOpfsBackup("{\"test\": 123}", "my_backup.json");
    expect(saved).toBe(true);

    const loaded = await loadOpfsBackup("my_backup.json");
    expect(loaded).toBe("{\"test\": 123}");

    const deleted = await deleteOpfsBackup("my_backup.json");
    expect(deleted).toBe(true);
    expect(await loadOpfsBackup("my_backup.json")).toBeNull();

    vi.unstubAllGlobals();
  });
});
