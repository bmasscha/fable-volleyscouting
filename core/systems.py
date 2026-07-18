"""Registry of playing systems (5-1, 6-2, 6-6, ...).

Engine semantics (rotation, scoring, libero exchanges) never depend on
which system a team plays -- that is a contract kept elsewhere. A
system only changes three display/assist concerns:

  * which formation chart is shown for a given rally situation
    (`system_xy`), since a 6-2's two setters and a 6-6's keyless
    rotation stand differently than a 5-1;
  * who the "acting setter" is for UI assists like the setter-tracker
    highlight (`acting_setter_slot_for`);
  * a soft expectation of how many setters a lineup should carry, for
    setup-time validation (`SystemSpec.expected_setters`).

A `SystemSpec.id` is stored verbatim in `MatchConfig.systems` and is
therefore a stable, persisted contract: renaming or removing an id
would strand saved matches. Adding a new system is one registration
in `SYSTEMS`; nothing else in this module changes.

Chart shape, uniform across every system: `charts[mode][key][slot] ->
(x, y)`, authored on the LEFT half (net x=0, own end line x=-9, y=0
own left sideline, y=9 own right) exactly like core.formations. `key`
is the acting setter's lineup slot 0..5 for systems that key off the
setter (`uses_setter_roles=True`); systems that do not (6-6) use the
single constant key 0. Mode.SERVE_BASE charts hold slots 1..5 only --
slot 0 is always the server, placed by `serve_xy(side)` at lookup
time. Mode.GRID has no chart: it is always the rotational grid.

5-1 and 6-2 differ only in label/description/expected_setters; their
charts are generated at import time from core.formations' private
tables so the two modules can never drift apart. Keyless systems have
no setter role at all -- some fixed lineup slot always sets (P3 for
"6-6", P1 for "6-6-p1"), given by `SystemSpec.fixed_setter_slot`; their
charts are authored directly (see `_SIX_SIX_*` below).
"""
from __future__ import annotations

from dataclasses import dataclass

from core.formations import (Mode, _DEFENSE, _OFFENSE, _OFFSET_CATEGORY,
                             _RECEIVE, _SERVE_BASE, acting_setter_slot,
                             formation_note)
from core.models import Role
from core.rotation import BACK_ROW, position_xy, serve_xy, to_side

Chart = dict[int, tuple[float, float]]
Charts = dict[Mode, dict[int, Chart]]


@dataclass(frozen=True)
class SystemSpec:
    id: str                  # "5-1" -- stored in MatchConfig, stable
    label: str                # e.g. "5-1 (one setter)"
    description: str          # one-liner for setup UI tooltips
    uses_setter_roles: bool   # False => roles ignored, chart key is 0
    expected_setters: int     # soft setup validation (0 for 6-6)
    charts: Charts
    fixed_setter_slot: int | None = None  # acting setter's slot for
                                          # keyless systems; None/ignored
                                          # when uses_setter_roles


# --- 5-1 / 6-2: generated from core.formations' private tables --------
# formations.formation_xy's math, reproduced exactly per setter slot
# (the "key"): RECEIVE is that key's row of _RECEIVE verbatim; for
# OFFENSE/DEFENSE each slot's role is its offset from the setter
# (_OFFSET_CATEGORY) combined with whether it is front row; SERVE_BASE
# is the same slots-1..5 chart regardless of key. 5-1 and 6-2 share
# this object -- they never need different geometry, only different
# setup expectations (1 setter vs 2).
def _generate_setter_keyed_charts() -> Charts:
    serve_base = {i: _SERVE_BASE[i] for i in range(1, 6)}
    receive: dict[int, Chart] = {}
    offense: dict[int, Chart] = {}
    defense: dict[int, Chart] = {}
    for key in range(6):
        receive[key] = dict(_RECEIVE[key])
        off: Chart = {}
        dfn: Chart = {}
        for i in range(6):
            cat = _OFFSET_CATEGORY[(i - key) % 6]
            front = i not in BACK_ROW
            off[i] = _OFFENSE[(cat, front)]
            dfn[i] = _DEFENSE[(cat, front)]
        offense[key] = off
        defense[key] = dfn
    return {
        Mode.RECEIVE: receive,
        Mode.SERVE_BASE: {key: dict(serve_base) for key in range(6)},
        Mode.OFFENSE: offense,
        Mode.DEFENSE: defense,
    }


_SETTER_KEYED_CHARTS = _generate_setter_keyed_charts()

# --- 6-6: no setter role -- whoever rotates through P3 sets ------------
# Classic youth "W" reception, authored directly (not generated): five
# passers, P3 up at the net to set. Coordinates satisfy the FIVB
# overlap rules like every other chart in this module.
_SIX_SIX_RECEIVE: Chart = {
    0: (-7.5, 7.5),   # P1 deep right
    1: (-4.0, 7.0),   # P2 mid right passer
    2: (-1.0, 4.7),   # P3 at the net (sets)
    3: (-4.0, 2.0),   # P4 mid left passer
    4: (-7.5, 1.5),   # P5 deep left
    5: (-7.5, 4.5),   # P6 deep middle
}
_SIX_SIX_OFFENSE: Chart = {
    0: (-6.8, 7.4), 1: (-3.4, 7.4), 2: (-0.9, 5.8),
    3: (-3.4, 1.6), 4: (-6.8, 1.6), 5: (-6.8, 4.5),
}
_SIX_SIX_DEFENSE: Chart = {
    0: (-6.0, 7.5), 1: (-1.4, 7.4), 2: (-1.2, 4.5),
    3: (-1.4, 1.6), 4: (-6.0, 1.8), 5: (-7.8, 4.5),
}
_SIX_SIX_CHARTS: Charts = {
    Mode.RECEIVE: {0: _SIX_SIX_RECEIVE},
    Mode.SERVE_BASE: {0: {i: _SERVE_BASE[i] for i in range(1, 6)}},
    Mode.OFFENSE: {0: _SIX_SIX_OFFENSE},
    Mode.DEFENSE: {0: _SIX_SIX_DEFENSE},
}

# --- 6-6 (P1 sets): no setter role -- whoever rotates through P1 -------
# penetrates from the back right to set. Reception is a five-passer W
# with P1 tucked short in the right-back corner, ready to run in;
# defense is identical to the plain 6-6 chart (everyone digs/blocks the
# zone they stand in).
_SIX_SIX_P1_RECEIVE: Chart = {
    0: (-6.8, 8.2),   # P1 hides right back, runs in to set
    1: (-4.0, 7.0),   # P2 mid right passer
    2: (-4.0, 4.5),   # P3 mid middle passer
    3: (-4.0, 2.0),   # P4 mid left passer
    4: (-7.5, 1.8),   # P5 deep left
    5: (-7.5, 4.5),   # P6 deep middle
}
_SIX_SIX_P1_OFFENSE: Chart = {
    0: (-1.6, 6.2), 1: (-3.4, 7.4), 2: (-2.6, 4.4),
    3: (-3.4, 1.6), 4: (-6.8, 1.6), 5: (-6.8, 4.5),
}
_SIX_SIX_P1_DEFENSE: Chart = _SIX_SIX_DEFENSE
_SIX_SIX_P1_CHARTS: Charts = {
    Mode.RECEIVE: {0: _SIX_SIX_P1_RECEIVE},
    Mode.SERVE_BASE: {0: {i: _SERVE_BASE[i] for i in range(1, 6)}},
    Mode.OFFENSE: {0: _SIX_SIX_P1_OFFENSE},
    Mode.DEFENSE: {0: _SIX_SIX_P1_DEFENSE},
}


# --- registry -----------------------------------------------------------
SYSTEMS: dict[str, SystemSpec] = {
    "5-1": SystemSpec(
        id="5-1", label="5-1 (one setter)",
        description="One setter plays every rotation; the opposite "
                    "always lines up across from them.",
        uses_setter_roles=True, expected_setters=1,
        charts=_SETTER_KEYED_CHARTS, fixed_setter_slot=None),
    "6-2": SystemSpec(
        id="6-2", label="6-2 (two setters)",
        description="Two setters, diagonal from each other; whichever "
                    "one is back row runs the offence.",
        uses_setter_roles=True, expected_setters=2,
        charts=_SETTER_KEYED_CHARTS, fixed_setter_slot=None),
    "6-6": SystemSpec(
        id="6-6", label="6-6 (no dedicated setter)",
        description="No setter role: whoever rotates through zone 3 "
                    "sets that rally.",
        uses_setter_roles=False, expected_setters=0,
        charts=_SIX_SIX_CHARTS, fixed_setter_slot=2),
    "6-6-p1": SystemSpec(
        id="6-6-p1", label="6-6 (P1 sets)",
        description="No setter role: whoever rotates through P1 "
                    "penetrates from the back right to set.",
        uses_setter_roles=False, expected_setters=0,
        charts=_SIX_SIX_P1_CHARTS, fixed_setter_slot=0),
}
DEFAULT_SYSTEM = "5-1"


def get_system(system_id: str | None) -> SystemSpec:
    """Look up a system by id, falling back to the default for an
    unknown or missing id -- forward compat with save files written by
    a newer version that added a system this build does not know."""
    if system_id is None:
        return SYSTEMS[DEFAULT_SYSTEM]
    return SYSTEMS.get(system_id, SYSTEMS[DEFAULT_SYSTEM])


def system_ids() -> list[str]:
    """Registered system ids in registry (menu) order."""
    return list(SYSTEMS.keys())


def chart_key(spec: SystemSpec, roles: dict[int, Role]) -> int | None:
    """Which chart row to use for this lineup: the acting setter's
    slot for setter-keyed systems, or the constant 0 for keyless
    ones."""
    if not spec.uses_setter_roles:
        return 0
    return acting_setter_slot(roles)


def system_xy(spec: SystemSpec, roles: dict[int, Role], mode: Mode,
             side: str) -> dict[int, tuple[float, float]]:
    """Court coordinates (metres) for lineup slots 0..5 (= P1..P6) of a
    team on `side`, playing `spec`, in the given rally situation."""
    key = None if mode is Mode.GRID else chart_key(spec, roles)
    if key is None:
        return {i: position_xy(i, side) for i in range(6)}
    chart = spec.charts[mode][key]
    if mode is Mode.SERVE_BASE:
        out = {0: serve_xy(side)}
        for i in range(1, 6):
            out[i] = to_side(*chart[i], side)
        return out
    return {i: to_side(*chart[i], side) for i in range(6)}


def system_note(spec: SystemSpec, roles: dict[int, Role]) -> str | None:
    """Why the realistic charts are unavailable, or None while they
    are in use. Keyless systems have no setter to misidentify, so
    they never produce a note."""
    if not spec.uses_setter_roles:
        return None
    return formation_note(roles)


def acting_setter_slot_for(spec: SystemSpec,
                          roles: dict[int, Role]) -> int | None:
    """Lineup slot of whoever is setting this rally. Setter-keyed
    systems delegate to role identification; a keyless system always
    has the same fixed lineup slot set, per `spec.fixed_setter_slot`."""
    if not spec.uses_setter_roles:
        return spec.fixed_setter_slot
    return acting_setter_slot(roles)
