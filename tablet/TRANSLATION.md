# Translation conventions — Python `core/` → TypeScript `tablet/src/core/`

The Python code in `core/` is the **reference implementation**. This folder is a
1:1 translation whose only job is to behave identically. These conventions keep
future syncs mechanical: when `core/xyz.py` changes, the diff must be portable
to `src/core/xyz.ts` line by line.

## Rules

1. **Mirror names exactly.** File names, function names, parameter names, field
   names and their order stay as in Python — `snake_case` included. Do not
   "improve" names, split functions, or reorder code. One Python module = one
   TS module; keep the same doc comments (translated to `/** … */`).

2. **Enums become string-literal unions with a same-named const object.**
   ```ts
   export const Rating = { ERROR: "!", POOR: "-", GOOD: "+", PERFECT: "#" } as const;
   export type Rating = (typeof Rating)[keyof typeof Rating];
   ```
   The values are the serialized forms — identical to Python's `.value`.

3. **Dataclasses become interfaces** (+ a `default_…()`/`make_…()` factory when
   Python has field defaults). Events are a discriminated union on `type`
   (see `events.ts`) whose shape equals the *serialized* dict form.

4. **Team-keyed dicts** are `Record<TeamKey, T>` with `TeamKey = "home" | "away"`.

5. **Warning strings must match Python byte-for-byte.** The conformance suite
   compares them exactly. Template literals mirror the f-strings; Python
   `enum.value` interpolations are already plain strings in TS.

6. **Python semantics to watch:**
   - `%` on negative numbers: Python `-1 % 6 == 5`. Use `((n % m) + m) % m`.
   - `x or y` on an optional: use `x ?? y` (never `||` — `0`/`""` differ).
   - `list.index` / `in`: use `indexOf` / `includes`.
   - `dict` iteration order = JS object insertion order (both guaranteed).
   - Copy defensively exactly where Python does (`list(x)` → `[...x]`).
   - `round(x, 2)` for fixture floats round-trips exactly through JSON.

7. **No new behavior.** If something looks like a bug in the Python code,
   report it — do not fix it unilaterally on either side.

## Verification

- Unit tests: port the matching `tests/test_*.py` to `tablet/tests/*.test.ts`
  (Vitest). Keep test names and assertions recognizably parallel.
- Conformance: `tablet/tests/conformance.test.ts` replays golden fixtures in
  `tablet/conformance/` generated from the Python engine by
  `tools/gen_conformance.py`. These must always pass unchanged.
- Run with: `npm --prefix tablet run test` (from the repo root).
