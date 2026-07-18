"""User-authored playing systems: persistence + registry merge.

A coach can add custom systems (a school's own 6-2 variant, a beach
switch, ...) without touching code. Each custom system is one JSON file
in a ``systems\\`` folder at the project root, sibling to ``matches\\``
and ``rosters\\``. At app start ``refresh_registry`` loads them and
merges them into ``core.systems.SYSTEMS`` in place, so every consumer
of the registry -- the setup wizard, the per-team toolbar menus,
``system_xy`` and friends -- picks them up with no other change. A
custom id is stored verbatim in ``MatchConfig.systems`` exactly like a
built-in one.

Why this is safe to layer on top of the built-ins:

  * ``BUILTIN_IDS`` freezes the registry's keys at import time, before
    any user merge has run. It is the authority on which ids are
    untouchable -- built-ins can never be overwritten, shadowed or
    deleted, and a user file whose id collides with a built-in is
    skipped, not honoured.
  * ``refresh_registry`` mutates the *existing* ``SYSTEMS`` dict (other
    modules hold a reference to it) rather than rebinding it: it drops
    every non-built-in entry and re-inserts the current user systems in
    sorted-id order after the built-ins. It is therefore idempotent and
    reflects on-disk deletions on the next call.
  * A bad file must never stop the app from starting. ``load_user_systems``
    turns every parse/validation failure into a human problem string and
    skips that file; the caller (``main``) prints the problems to stderr
    and carries on.
  * ``get_system`` already falls back to the default "5-1" for an
    unknown id, so a match saved against a custom system that has since
    been deleted still opens -- it simply shows the default geometry
    instead of failing.

File schema (format 1), all ints stringified because they are JSON
object keys, coordinates as ``[x, y]`` pairs authored on the LEFT half
(net x=0, own end line x=-9) exactly like ``core.formations``. Mode
names are the ``Mode`` enum values; ``Mode.GRID`` is never stored (it is
the rotational fallback, not a chart). ``serve_base`` holds slots 1..5
only -- slot 0 is the server, placed by ``serve_xy`` at lookup time.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from core.formations import Mode
from core.persistence import _atomic_write
from core.systems import SYSTEMS, SystemSpec

FORMAT = 1

# The registry's keys captured before any user merge -- import-order
# safe because merges only ever happen at runtime via refresh_registry.
BUILTIN_IDS: frozenset[str] = frozenset(SYSTEMS)

# Modes that carry a stored chart (GRID is the fallback, never stored).
_STORED_MODES = (Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")

# Authored left half plus the free zone: the coordinate box the app is
# willing to draw a token in (mirrors tests/test_formations.py bounds).
_X_MIN, _X_MAX = -13.0, 0.0
_Y_MIN, _Y_MAX = -2.5, 11.5


def systems_dir(base: str | Path | None = None) -> Path:
    d = Path(base) if base else Path(__file__).resolve().parent.parent / "systems"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------- serialize

def serialize_system(spec: SystemSpec) -> dict:
    """JSON-ready dict for a SystemSpec (schema format 1)."""
    charts: dict[str, dict[str, dict[str, list[float]]]] = {}
    for mode in _STORED_MODES:
        charts[mode.value] = {
            str(key): {str(slot): [x, y] for slot, (x, y) in chart.items()}
            for key, chart in spec.charts[mode].items()
        }
    return {
        "format": FORMAT,
        "id": spec.id,
        "label": spec.label,
        "description": spec.description,
        "uses_setter_roles": spec.uses_setter_roles,
        "expected_setters": spec.expected_setters,
        "fixed_setter_slot": spec.fixed_setter_slot,
        "charts": charts,
    }


# ------------------------------------------------------------- deserialize

def _is_number(v) -> bool:
    # bool is a subclass of int -- a JSON true/false is not a coordinate.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _int_key(raw, what: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: bad key {raw!r}")


def _parse_chart(raw, mode: Mode, key: int) -> dict[int, tuple[float, float]]:
    where = f"{mode.value} chart key {key}"
    if not isinstance(raw, dict):
        raise ValueError(f"{where} is not an object")
    want = set(range(1, 6)) if mode is Mode.SERVE_BASE else set(range(6))
    chart: dict[int, tuple[float, float]] = {}
    for s, coord in raw.items():
        slot = _int_key(s, where)
        if not (isinstance(coord, (list, tuple)) and len(coord) == 2
                and _is_number(coord[0]) and _is_number(coord[1])):
            raise ValueError(f"{where} slot {slot}: coordinate must be [x, y]")
        x, y = float(coord[0]), float(coord[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"{where} slot {slot}: coordinate must be finite")
        if not (_X_MIN <= x <= _X_MAX and _Y_MIN <= y <= _Y_MAX):
            raise ValueError(
                f"{where} slot {slot}: ({x}, {y}) is off the authored area "
                f"(x in [{_X_MIN}, {_X_MAX}], y in [{_Y_MIN}, {_Y_MAX}])")
        chart[slot] = (x, y)
    if set(chart) != want:
        raise ValueError(f"{where}: slots must be exactly {sorted(want)}")
    return chart


def deserialize_system(data: dict) -> SystemSpec:
    """Build a SystemSpec from a format-1 dict, raising ValueError with a
    human message on any malformed or out-of-range field. The inverse of
    serialize_system: deserialize_system(serialize_system(spec)) == spec."""
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    if data.get("format") != FORMAT:
        raise ValueError(
            f"written by a newer version of the app (format "
            f"{data.get('format')!r}, this build reads format {FORMAT})")

    sid = data.get("id")
    if not (isinstance(sid, str) and _ID_RE.match(sid)):
        raise ValueError(f"invalid system id {sid!r}")
    label = data.get("label")
    description = data.get("description")
    if not isinstance(label, str) or not isinstance(description, str):
        raise ValueError("label and description must be strings")
    uses_setter_roles = data.get("uses_setter_roles")
    if not isinstance(uses_setter_roles, bool):
        raise ValueError("uses_setter_roles must be a boolean")
    expected_setters = data.get("expected_setters")
    if not isinstance(expected_setters, int) or isinstance(expected_setters, bool):
        raise ValueError("expected_setters must be an integer")
    fixed_setter_slot = data.get("fixed_setter_slot")

    if uses_setter_roles:
        want_keys = set(range(6))          # one chart per setter slot
    else:
        want_keys = {0}                    # single constant key
        if not (isinstance(fixed_setter_slot, int)
                and not isinstance(fixed_setter_slot, bool)
                and 0 <= fixed_setter_slot <= 5):
            raise ValueError(
                "fixed_setter_slot must be 0..5 for a keyless system")

    raw_charts = data.get("charts")
    if not isinstance(raw_charts, dict):
        raise ValueError("charts must be an object")
    charts: dict[Mode, dict[int, dict[int, tuple[float, float]]]] = {}
    for mode in _STORED_MODES:
        raw_mode = raw_charts.get(mode.value)
        if not isinstance(raw_mode, dict):
            raise ValueError(f"missing chart for mode {mode.value!r}")
        parsed: dict[int, dict[int, tuple[float, float]]] = {}
        for k, v in raw_mode.items():
            ki = _int_key(k, mode.value)
            parsed[ki] = _parse_chart(v, mode, ki)
        if set(parsed) != want_keys:
            raise ValueError(
                f"{mode.value}: chart keys must be exactly {sorted(want_keys)}")
        charts[mode] = parsed

    return SystemSpec(
        id=sid, label=label, description=description,
        uses_setter_roles=uses_setter_roles,
        expected_setters=expected_setters, charts=charts,
        fixed_setter_slot=fixed_setter_slot)


# ------------------------------------------------------------------- files

def save_user_system(spec: SystemSpec, base: str | Path | None = None) -> Path:
    """Write ``<id>.json`` atomically. Refuses built-in ids and malformed
    ids so a user system can never mask or corrupt a built-in."""
    if spec.id in BUILTIN_IDS:
        raise ValueError(f"'{spec.id}': built-in systems cannot be overwritten")
    if not _ID_RE.match(spec.id):
        raise ValueError(f"invalid system id {spec.id!r}")
    path = systems_dir(base) / f"{spec.id}.json"
    _atomic_write(path, json.dumps(serialize_system(spec), indent=1))
    return path


def load_user_systems(
        base: str | Path | None = None
) -> tuple[dict[str, SystemSpec], list[str]]:
    """Load every ``*.json`` in the systems folder. Returns the valid
    systems keyed by id plus a list of ``"<filename>: <reason>"`` problem
    strings for the files that were skipped (bad JSON, wrong schema, or an
    id colliding with a built-in). Never raises for a bad file."""
    out: dict[str, SystemSpec] = {}
    problems: list[str] = []
    for p in sorted(systems_dir(base).glob("*.json")):
        try:
            spec = deserialize_system(
                json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError) as e:
            problems.append(f"{p.name}: {e}")
            continue
        if spec.id in BUILTIN_IDS:
            problems.append(
                f"{p.name}: id '{spec.id}' collides with a built-in system")
            continue
        out[spec.id] = spec
    return out, problems


def delete_user_system(system_id: str,
                       base: str | Path | None = None) -> None:
    """Remove a user system's file. Refuses built-in ids."""
    if system_id in BUILTIN_IDS:
        raise ValueError(f"'{system_id}': built-in systems cannot be deleted")
    (systems_dir(base) / f"{system_id}.json").unlink(missing_ok=True)


# ---------------------------------------------------------------- registry

def refresh_registry(base: str | Path | None = None) -> list[str]:
    """Re-merge user systems into ``core.systems.SYSTEMS`` in place: drop
    every non-built-in entry, then re-insert the loaded user systems in
    sorted-id order after the built-ins. Returns the load problem list.
    Idempotent, and the single runtime entry point for this module."""
    user, problems = load_user_systems(base)
    for key in [k for k in SYSTEMS if k not in BUILTIN_IDS]:
        del SYSTEMS[key]
    for sid in sorted(user):
        SYSTEMS[sid] = user[sid]
    return problems
