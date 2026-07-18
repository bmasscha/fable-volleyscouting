import { afterEach, beforeEach, describe, expect, test } from "vitest";

import {
  USER_SYSTEMS_KEY,
  loadUserSystems,
  saveUserSystems,
} from "../src/browserStorage";
import {
  DEFAULT_SYSTEM,
  SYSTEMS,
  SystemSpec,
  get_system,
  system_ids,
} from "../src/core/systems";
import {
  BUILTIN_IDS,
  deserialize_system,
  parse_import,
  refresh_registry,
  serialize_system,
} from "../src/core/user_systems";

// The exact JSON the desktop writes for serialize_system(SYSTEMS["6-6"]).
// Pinned as a fixture: coordinates, stringified int keys, [x, y] arrays.
const FIXTURE_6_6 = {
  format: 1,
  id: "6-6",
  label: "6-6 (no dedicated setter)",
  description: "No setter role: whoever rotates through zone 3 sets that rally.",
  uses_setter_roles: false,
  expected_setters: 0,
  fixed_setter_slot: 2,
  charts: {
    receive: { 0: { 0: [-7.5, 7.5], 1: [-4.0, 7.0], 2: [-1.0, 4.7], 3: [-4.0, 2.0], 4: [-7.5, 1.5], 5: [-7.5, 4.5] } },
    serve_base: { 0: { 1: [-1.6, 7.4], 2: [-1.6, 4.5], 3: [-1.6, 1.6], 4: [-6.5, 1.8], 5: [-6.5, 4.6] } },
    offense: { 0: { 0: [-6.8, 7.4], 1: [-3.4, 7.4], 2: [-0.9, 5.8], 3: [-3.4, 1.6], 4: [-6.8, 1.6], 5: [-6.8, 4.5] } },
    defense: { 0: { 0: [-6.0, 7.5], 1: [-1.4, 7.4], 2: [-1.2, 4.5], 3: [-1.4, 1.6], 4: [-6.0, 1.8], 5: [-7.8, 4.5] } },
  },
};

// A valid custom (non-builtin) system: the 6-6 fixture under a new id.
function customFixture(id = "my-6-6"): Record<string, unknown> {
  const clone = JSON.parse(JSON.stringify(FIXTURE_6_6)) as Record<string, unknown>;
  clone.id = id;
  clone.label = `custom ${id}`;
  return clone;
}

// Drop every non-builtin from SYSTEMS so other test files are unaffected.
afterEach(() => {
  refresh_registry([]);
});

describe("deserialize_system", () => {
  test("the pinned 6-6 fixture deserializes to SYSTEMS['6-6']", () => {
    expect(deserialize_system(FIXTURE_6_6)).toEqual(SYSTEMS["6-6"]);
  });

  test("serialize/deserialize round-trips every builtin", () => {
    for (const id of Object.keys(SYSTEMS)) {
      const spec = SYSTEMS[id];
      expect(deserialize_system(serialize_system(spec))).toEqual(spec);
    }
  });
});

describe("deserialize_system validation", () => {
  test("rejects a wrong format", () => {
    const data = customFixture();
    data.format = 2;
    expect(() => deserialize_system(data)).toThrow(/newer version of the app/);
  });

  test("rejects a bad id", () => {
    const data = customFixture();
    data.id = "has space";
    expect(() => deserialize_system(data)).toThrow(/invalid system id/);
  });

  test("rejects a missing mode", () => {
    const data = customFixture();
    delete (data.charts as Record<string, unknown>).defense;
    expect(() => deserialize_system(data)).toThrow(/missing chart for mode 'defense'/);
  });

  test("rejects a wrong slot set", () => {
    const data = customFixture();
    delete ((data.charts as any).receive[0])[5];
    expect(() => deserialize_system(data)).toThrow(/slots must be exactly \[0, 1, 2, 3, 4, 5\]/);
  });

  test("rejects an out-of-bounds coordinate", () => {
    const data = customFixture();
    (data.charts as any).receive[0][2] = [5, 4.7];
    expect(() => deserialize_system(data)).toThrow(/off the authored area/);
  });

  test("rejects a keyless system without fixed_setter_slot", () => {
    const data = customFixture();
    delete data.fixed_setter_slot;
    expect(() => deserialize_system(data)).toThrow(/fixed_setter_slot must be 0\.\.5/);
  });
});

describe("parse_import", () => {
  test("accepts a single serialized object", () => {
    const { specs, problems } = parse_import(JSON.stringify(customFixture("solo")));
    expect(problems).toEqual([]);
    expect(specs.map((s) => s.id)).toEqual(["solo"]);
  });

  test("accepts an array of systems", () => {
    const { specs, problems } = parse_import(
      JSON.stringify([customFixture("a-sys"), customFixture("b-sys")]));
    expect(problems).toEqual([]);
    expect(specs.map((s) => s.id)).toEqual(["a-sys", "b-sys"]);
  });

  test("keeps good entries and collects problems for bad ones", () => {
    const bad = customFixture("bad");
    bad.format = 99;
    const { specs, problems } = parse_import(
      JSON.stringify([customFixture("good"), bad]));
    expect(specs.map((s) => s.id)).toEqual(["good"]);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("entry 2");
  });

  test("skips a builtin id collision with a message", () => {
    const { specs, problems } = parse_import(JSON.stringify(FIXTURE_6_6));
    expect(specs).toEqual([]);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("collides with a built-in system");
  });

  test("reports invalid JSON without throwing", () => {
    const { specs, problems } = parse_import("{not json");
    expect(specs).toEqual([]);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("not valid JSON");
  });
});

describe("refresh_registry", () => {
  const BUILTIN_ORDER = Object.keys(SYSTEMS);

  test("inserts user systems sorted by id after the builtins", () => {
    const z = deserialize_system(customFixture("z-sys"));
    const a = deserialize_system(customFixture("a-sys"));
    refresh_registry([z, a]);
    expect(system_ids()).toEqual([...BUILTIN_ORDER, "a-sys", "z-sys"]);
    expect(get_system("a-sys")).toBe(a);
    expect(get_system("z-sys")).toBe(z);
  });

  test("is idempotent", () => {
    const spec = deserialize_system(customFixture("rep"));
    refresh_registry([spec]);
    const first = system_ids();
    refresh_registry([spec]);
    expect(system_ids()).toEqual(first);
  });

  test("removal drops the user system, restoring builtins only", () => {
    refresh_registry([deserialize_system(customFixture("temp"))]);
    expect(system_ids()).toContain("temp");
    refresh_registry([]);
    expect(system_ids()).toEqual(BUILTIN_ORDER);
  });

  test("skips builtin ids among the input and never mutates builtins", () => {
    const original = SYSTEMS["6-6"];
    const collide = deserialize_system(FIXTURE_6_6); // id "6-6"
    refresh_registry([collide]);
    expect(SYSTEMS["6-6"]).toBe(original);
    expect(system_ids()).toEqual(BUILTIN_ORDER);
    expect(BUILTIN_IDS.has("6-6")).toBe(true);
  });

  test("unknown ids fall back to the default", () => {
    refresh_registry([]);
    expect(get_system("nope")).toBe(SYSTEMS[DEFAULT_SYSTEM]);
  });
});

class FakeStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

describe("user systems storage", () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      writable: true,
      value: new FakeStorage(),
    });
  });

  test("round-trips saved systems through storage", () => {
    const specs = [
      deserialize_system(customFixture("store-a")),
      deserialize_system(customFixture("store-b")),
    ];
    expect(saveUserSystems(specs)).toBe(true);
    expect(loadUserSystems()).toEqual(specs);
  });

  test("returns [] when storage is empty", () => {
    expect(loadUserSystems()).toEqual([]);
  });

  test("corrupt storage returns [] without throwing", () => {
    localStorage.setItem(USER_SYSTEMS_KEY, "{not json");
    expect(loadUserSystems()).toEqual([]);
  });

  test("wrong-shape storage returns []", () => {
    localStorage.setItem(USER_SYSTEMS_KEY, JSON.stringify({ version: 1 }));
    expect(loadUserSystems()).toEqual([]);
  });

  test("skips an individually invalid stored entry", () => {
    const good = serialize_system(deserialize_system(customFixture("ok")));
    localStorage.setItem(USER_SYSTEMS_KEY, JSON.stringify({
      version: 1,
      systems: [good, { format: 1, id: "broken" }],
    }));
    const loaded = loadUserSystems();
    expect(loaded.map((s) => s.id)).toEqual(["ok"]);
  });
});
