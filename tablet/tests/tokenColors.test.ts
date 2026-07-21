import { describe, expect, test } from "vitest";

import {
  LIBERO_PALETTE,
  inkFor,
  liberoColorFor,
  outlineFor,
} from "../src/tokenColors";

// 1:1 mirror of tests/test_token_colors.py -- keep the two in lock-step.

describe("token colours", () => {
  test("inkFor picks dark ink on light jerseys", () => {
    expect(inkFor("#ffffff")).toBe("#000000"); // white jersey -> black ink
    expect(inkFor("#fbc02d")).toBe("#000000"); // yellow jersey -> black ink
  });

  test("inkFor picks light ink on dark jerseys", () => {
    expect(inkFor("#000000")).toBe("#ffffff"); // black jersey -> white ink
    expect(inkFor("#0d1b3e")).toBe("#ffffff"); // navy jersey -> white ink
  });

  test("outlineFor is the opposite of the ink", () => {
    expect(outlineFor("#000000")).toBe("#ffffff");
    expect(outlineFor("#ffffff")).toBe("#000000");
  });

  test("liberoColorFor avoids a reddish colour for a red team", () => {
    const team = "#d32f2f"; // red team
    const result = liberoColorFor(team);
    expect(result).not.toBe(team); // never the team colour
    expect(result).not.toBe("#d32f2f"); // never the red palette entry
    expect((LIBERO_PALETTE as readonly string[]).includes(result)).toBe(true);
  });

  test("liberoColorFor for white is near-black", () => {
    expect(liberoColorFor("#ffffff")).toBe("#212121");
  });

  test("liberoColorFor for black is white", () => {
    expect(liberoColorFor("#000000")).toBe("#ffffff");
  });

  test("liberoColorFor output is always in the palette", () => {
    for (const team of [
      "#d32f2f",
      "#ffffff",
      "#000000",
      "#2e7d32",
      "#1565c0",
      "#e8853b",
      "#8e24aa",
    ]) {
      expect((LIBERO_PALETTE as readonly string[]).includes(liberoColorFor(team))).toBe(true);
    }
  });

  test("liberoColorFor is deterministic", () => {
    for (const team of ["#d32f2f", "#123456", "#abcdef"]) {
      expect(liberoColorFor(team)).toBe(liberoColorFor(team));
    }
  });
});
