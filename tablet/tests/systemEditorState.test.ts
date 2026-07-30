import { describe, expect, test } from "vitest";

import { SYSTEMS } from "../src/core/systems";
import { BUILTIN_IDS } from "../src/core/user_systems";
import {
  canSave,
  copyIdFor,
  createEditorState,
  roleHint,
  saveHint,
  setterSlots,
} from "../src/systemEditorState";

const ALL_SLOTS = [0, 1, 2, 3, 4, 5];

// --- setterSlots: which tokens the editor paints as setters -------------
// Display-only. Nothing here is stored: expected_setters already rode
// along in the saved JSON, these functions only read it.
describe("setterSlots", () => {
  test("a 5-1 marks only the rotation's own setter", () => {
    const state = createEditorState("5-1");
    expect(state.expected_setters).toBe(1);
    for (const key of ALL_SLOTS) {
      expect(setterSlots(state, key)).toEqual([key]);
    }
  });

  test("a 6-2 marks the acting setter and its diagonal, acting first", () => {
    const state = createEditorState("6-2");
    expect(state.expected_setters).toBe(2);
    expect(setterSlots(state, 1)).toEqual([1, 4]);
    expect(setterSlots(state, 0)).toEqual([0, 3]);
    expect(setterSlots(state, 4)).toEqual([4, 1]); // wraps past P6
  });

  test("raising the setters field to 3 spreads a 6-3 live", () => {
    // The editor mutates expected_setters in place via patch(); the court
    // must follow without reloading the base system.
    const state = createEditorState("6-2");
    state.expected_setters = 3;
    expect(setterSlots(state, 1)).toEqual([1, 3, 5]);
    expect(setterSlots(state, 0)).toEqual([0, 2, 4]);
  });

  test("a keyless 6-6 keeps marking exactly its fixed setting slot", () => {
    const state = createEditorState("6-6");
    expect(state.uses_setter_roles).toBe(false);
    expect(state.fixed_setter_slot).toBe(SYSTEMS["6-6"].fixed_setter_slot);
    expect(setterSlots(state, 0)).toEqual([2]);
  });

  test("a keyless system ignores expected_setters entirely", () => {
    // A 6-6 has no setter role, so a stray count must not spread it.
    const state = createEditorState("6-6-p1");
    state.expected_setters = 2;
    expect(setterSlots(state, 0)).toEqual([0]);
  });

  test("moving the fixed setting slot moves the mark", () => {
    const state = createEditorState("6-6");
    state.fixed_setter_slot = 5;
    expect(setterSlots(state, 0)).toEqual([5]);
  });
});

// --- roleHint: the little label under each token -------------------------
describe("roleHint", () => {
  test("a 5-1 reads its offset categories, setter at the key", () => {
    const state = createEditorState("5-1");
    expect(roleHint(state, 0, 0)).toBe("S");
    expect(roleHint(state, 0, 1)).toBe("OH");
    expect(roleHint(state, 0, 2)).toBe("MB");
    expect(roleHint(state, 0, 3)).toBe("OPP"); // one setter: the opposite
    expect(roleHint(state, 0, 4)).toBe("OH");
    expect(roleHint(state, 0, 5)).toBe("MB");
  });

  test("a 6-2's second setter reads S, not the OPP its offset implies", () => {
    const state = createEditorState("6-2");
    expect(roleHint(state, 1, 1)).toBe("S");
    expect(roleHint(state, 1, 4)).toBe("S"); // offset 3 would say "OPP"
    expect(roleHint(state, 1, 2)).toBe("OH");
    expect(roleHint(state, 1, 3)).toBe("MB");
    expect(roleHint(state, 1, 5)).toBe("OH");
    expect(roleHint(state, 1, 0)).toBe("MB");
  });

  test("a 6-3's three setters all read S", () => {
    const state = createEditorState("6-2");
    state.expected_setters = 3;
    expect(roleHint(state, 1, 1)).toBe("S");
    expect(roleHint(state, 1, 3)).toBe("S"); // offset 2 would say "MB"
    expect(roleHint(state, 1, 5)).toBe("S"); // offset 4 would say "OH"
    expect(roleHint(state, 1, 2)).toBe("OH");
    expect(roleHint(state, 1, 0)).toBe("MB");
  });

  test("every setter slot hints S, and only those", () => {
    const state = createEditorState("6-2");
    for (const key of ALL_SLOTS) {
      const setters = setterSlots(state, key);
      for (const slot of ALL_SLOTS) {
        expect(roleHint(state, key, slot) === "S").toBe(setters.includes(slot));
      }
    }
  });

  test("keyless hints are unchanged: 'sets' on the setting slot only", () => {
    const state = createEditorState("6-6");
    for (const slot of ALL_SLOTS) {
      expect(roleHint(state, 0, slot)).toBe(slot === 2 ? "sets" : "");
    }
  });
});

// --- saving on top of a built-in ----------------------------------------
// Save is never a dead button: only a malformed id blocks it, and a
// built-in id is redirected to a copy rather than refused.
describe("canSave / saveHint", () => {
  test("a built-in id is savable and says it will become a copy", () => {
    const state = createEditorState("6-6");
    expect(state.id).toBe("6-6");
    expect(canSave(state)).toBe(true);
    expect(saveHint(state)).toContain("copy");
  });

  test("only a malformed id blocks the save", () => {
    const state = createEditorState("6-6");
    state.id = "my 6-6";
    expect(canSave(state)).toBe(false);
    expect(saveHint(state)).toContain("id must start alphanumeric");
    state.id = "  my-6-6  "; // trimmed before validating
    expect(canSave(state)).toBe(true);
    expect(saveHint(state)).toBe("");
  });
});

describe("copyIdFor", () => {
  test("appends -copy, then numbers, skipping taken ids", () => {
    expect(copyIdFor("6-6", [])).toBe("6-6-copy");
    expect(copyIdFor("6-6", ["6-6-copy"])).toBe("6-6-copy-2");
    expect(copyIdFor("6-6", ["6-6-copy", "6-6-copy-2"])).toBe("6-6-copy-3");
  });

  test("never returns a built-in id", () => {
    for (const sid of BUILTIN_IDS) {
      expect(BUILTIN_IDS.has(copyIdFor(sid, []))).toBe(false);
    }
  });

  test("stays inside the 32-character id limit", () => {
    const long = "a".repeat(32);
    const id = copyIdFor(long, []);
    expect(id.length).toBeLessThanOrEqual(32);
    expect(id.endsWith("-copy")).toBe(true);
  });
});
