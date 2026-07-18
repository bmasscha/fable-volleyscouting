"""User-authored playing systems: overlap legality reporting,
serialize/deserialize round-tripping, file persistence and the in-place
registry merge."""
import dataclasses
import json

import pytest

from core import user_systems
from core.formations import Mode, overlap_violations
from core.rotation import LEFT, RIGHT, to_side
from core.systems import SYSTEMS, get_system, system_ids

# A stable snapshot of the built-in specs, taken before any test merges a
# user system into the (mutable, module-global) registry.
BUILTIN_SPECS = {sid: SYSTEMS[sid] for sid in sorted(user_systems.BUILTIN_IDS)}
SIDES = (LEFT, RIGHT)


def _sided(chart, side):
    """A left-authored chart mapped onto a given half's coordinates."""
    return {slot: to_side(x, y, side) for slot, (x, y) in chart.items()}


@pytest.fixture
def clean_registry():
    """Snapshot and restore core.systems.SYSTEMS so a refresh_registry
    test never leaks its mutations into the rest of the suite."""
    snapshot = dict(SYSTEMS)
    yield SYSTEMS
    SYSTEMS.clear()
    SYSTEMS.update(snapshot)


# --------------------------------------------------------------- overlap

class TestOverlapViolations:
    @pytest.mark.parametrize("side", SIDES)
    @pytest.mark.parametrize("sid", sorted(BUILTIN_SPECS))
    def test_builtin_receive_charts_are_legal(self, sid, side):
        for chart in BUILTIN_SPECS[sid].charts[Mode.RECEIVE].values():
            assert overlap_violations(_sided(chart, side), side) == []

    @pytest.mark.parametrize("side", SIDES)
    @pytest.mark.parametrize("sid", sorted(BUILTIN_SPECS))
    def test_builtin_serve_base_charts_are_legal_server_exempt(self, sid, side):
        for chart in BUILTIN_SPECS[sid].charts[Mode.SERVE_BASE].values():
            pos = _sided(chart, side)          # slots 1..5, no server
            assert overlap_violations(pos, side, exempt=(0,)) == []

    @pytest.mark.parametrize("side", SIDES)
    def test_p3_behind_p6_is_reported_and_exempt_suppresses_it(self, side):
        # Start from a legal chart and push P3 (front middle) behind P6
        # (back middle) without touching any y, so only the P3/P6 front
        # pair is violated. On the left half "closer to net" is a larger
        # x, so a smaller x than P6 puts P3 behind; to_side flips x for
        # the right half, so mirroring the same broken chart must produce
        # the identical single message (mirror-correctness).
        chart = dict(BUILTIN_SPECS["5-1"].charts[Mode.RECEIVE][0])
        chart[2] = (chart[5][0] - 1.0, chart[2][1])
        pos = _sided(chart, side)
        assert overlap_violations(pos, side) == ["P3 must be in front of P6"]
        assert overlap_violations(pos, side, exempt=(2,)) == []

    def test_p1_right_of_p6_lateral_message_format(self):
        # Push P1 to P6's left (smaller y on the left half): breaks the
        # P1>P6 lateral order only.
        chart = dict(BUILTIN_SPECS["5-1"].charts[Mode.RECEIVE][0])
        chart[0] = (chart[0][0], chart[5][1] - 1.0)
        assert overlap_violations(chart, LEFT) == ["P1 must be right of P6"]


# ------------------------------------------------------- serialize/deserialize

class TestRoundTrip:
    @pytest.mark.parametrize("sid", sorted(BUILTIN_SPECS))
    def test_deserialize_of_serialize_equals_original(self, sid):
        spec = BUILTIN_SPECS[sid]
        assert user_systems.deserialize_system(
            user_systems.serialize_system(spec)) == spec

    def test_serialized_shape_is_json_and_stringified(self):
        data = user_systems.serialize_system(BUILTIN_SPECS["6-6"])
        text = json.dumps(data)               # must be JSON-serializable
        again = json.loads(text)
        assert again["format"] == 1
        assert again["id"] == "6-6"
        # keys and slots are strings; coordinates are [x, y] lists
        recv0 = again["charts"]["receive"]["0"]
        assert set(recv0) == {"0", "1", "2", "3", "4", "5"}
        assert isinstance(recv0["0"], list) and len(recv0["0"]) == 2
        # serve_base holds slots 1..5 only (slot 0 is the server)
        assert set(again["charts"]["serve_base"]["0"]) == {"1", "2", "3", "4", "5"}

    def test_out_of_bounds_x_is_rejected(self):
        data = user_systems.serialize_system(BUILTIN_SPECS["6-6"])
        data["charts"]["receive"]["0"]["0"] = [-20.0, 4.5]   # x < -13
        with pytest.raises(ValueError):
            user_systems.deserialize_system(data)

    def test_newer_format_is_rejected(self):
        data = user_systems.serialize_system(BUILTIN_SPECS["5-1"])
        data["format"] = 2
        with pytest.raises(ValueError, match="newer version"):
            user_systems.deserialize_system(data)

    def test_keyless_needs_fixed_setter_slot(self):
        data = user_systems.serialize_system(BUILTIN_SPECS["6-6"])
        data["fixed_setter_slot"] = None
        with pytest.raises(ValueError, match="fixed_setter_slot"):
            user_systems.deserialize_system(data)

    def test_setter_keyed_needs_all_six_keys(self):
        data = user_systems.serialize_system(BUILTIN_SPECS["5-1"])
        del data["charts"]["receive"]["5"]
        with pytest.raises(ValueError, match="keys"):
            user_systems.deserialize_system(data)


# ------------------------------------------------------------ file persistence

def _custom(sid="my-6-6", from_id="6-6"):
    """A user spec built by renaming a built-in (charts unchanged)."""
    return dataclasses.replace(BUILTIN_SPECS[from_id], id=sid,
                               label=f"{sid} custom")


class TestPersistence:
    def test_save_then_load_round_trips(self, tmp_path):
        spec = _custom()
        path = user_systems.save_user_system(spec, base=tmp_path)
        assert path == tmp_path / "my-6-6.json"
        loaded, problems = user_systems.load_user_systems(base=tmp_path)
        assert problems == []
        assert loaded == {"my-6-6": spec}

    def test_save_refuses_builtin_id(self, tmp_path):
        with pytest.raises(ValueError, match="built-in"):
            user_systems.save_user_system(BUILTIN_SPECS["5-1"], base=tmp_path)

    def test_save_refuses_malformed_id(self, tmp_path):
        bad = dataclasses.replace(BUILTIN_SPECS["6-6"], id="bad id!")
        with pytest.raises(ValueError, match="invalid system id"):
            user_systems.save_user_system(bad, base=tmp_path)

    def test_load_skips_bad_files_but_keeps_good_sibling(self, tmp_path):
        # a good sibling that must survive
        user_systems.save_user_system(_custom("good"), base=tmp_path)
        # corrupt JSON
        (tmp_path / "corrupt.json").write_text("{ not json", encoding="utf-8")
        # valid JSON, wrong schema
        (tmp_path / "wrongschema.json").write_text(
            json.dumps({"format": 1, "id": "wrongschema"}), encoding="utf-8")
        # valid file whose id collides with a built-in
        (tmp_path / "collide.json").write_text(
            json.dumps(user_systems.serialize_system(BUILTIN_SPECS["5-1"])),
            encoding="utf-8")

        loaded, problems = user_systems.load_user_systems(base=tmp_path)
        assert set(loaded) == {"good"}
        names = {p.split(":")[0] for p in problems}
        assert names == {"corrupt.json", "wrongschema.json", "collide.json"}

    def test_delete_removes_file_and_refuses_builtins(self, tmp_path):
        user_systems.save_user_system(_custom("gone"), base=tmp_path)
        user_systems.delete_user_system("gone", base=tmp_path)
        loaded, problems = user_systems.load_user_systems(base=tmp_path)
        assert loaded == {} and problems == []
        # missing_ok: deleting again is a no-op, not an error
        user_systems.delete_user_system("gone", base=tmp_path)
        with pytest.raises(ValueError, match="built-in"):
            user_systems.delete_user_system("5-1", base=tmp_path)


# ----------------------------------------------------------------- registry

class TestRefreshRegistry:
    def test_registers_user_system_after_builtins(self, tmp_path, clean_registry):
        user_systems.save_user_system(_custom("zzz-custom"), base=tmp_path)
        problems = user_systems.refresh_registry(base=tmp_path)
        assert problems == []
        assert get_system("zzz-custom").id == "zzz-custom"
        ids = system_ids()
        # built-ins keep their order and come first; user ids follow
        assert ids[:len(BUILTIN_SPECS)] == list(BUILTIN_SPECS)
        assert ids[-1] == "zzz-custom"

    def test_deletion_is_reflected_on_next_refresh(self, tmp_path, clean_registry):
        user_systems.save_user_system(_custom("temp"), base=tmp_path)
        user_systems.refresh_registry(base=tmp_path)
        assert "temp" in SYSTEMS
        user_systems.delete_user_system("temp", base=tmp_path)
        user_systems.refresh_registry(base=tmp_path)
        assert "temp" not in SYSTEMS
        # unknown id degrades to the default, never raises
        assert get_system("temp").id == "5-1"

    def test_idempotent(self, tmp_path, clean_registry):
        user_systems.save_user_system(_custom("dup"), base=tmp_path)
        user_systems.refresh_registry(base=tmp_path)
        first = list(SYSTEMS.keys())
        user_systems.refresh_registry(base=tmp_path)
        assert list(SYSTEMS.keys()) == first

    def test_never_mutates_builtins(self, tmp_path, clean_registry):
        before = {sid: SYSTEMS[sid] for sid in BUILTIN_SPECS}
        user_systems.save_user_system(_custom("extra"), base=tmp_path)
        user_systems.refresh_registry(base=tmp_path)
        for sid, spec in before.items():
            assert SYSTEMS[sid] is spec
