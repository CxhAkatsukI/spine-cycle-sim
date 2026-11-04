"""Check that the Figure 8 continuation preserves the anchor and one-shot policy."""

from contextlib import nullcontext
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import figure8_matrix as matrix


def test_manifest_requires_all_seven_once(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    rows = [dict(dataset=dataset, updates=updates, native_g_input={"sha256": matrix.au.AU_SHA})
            for dataset, updates in matrix.CASES]
    data = dict(schema="figure8-native-input-identity-v1", cases=rows)
    manifest.write_text(json.dumps(data))
    pin = matrix.identity(manifest)
    assert tuple(matrix.load_cases(pin, pin["sha256"])) == matrix.CASES
    data["cases"] = [*rows, rows[0]]
    manifest.write_text(json.dumps(data))
    pin = matrix.identity(manifest)
    with pytest.raises(ValueError, match="exact seven"):
        matrix.load_cases(pin, pin["sha256"])


def test_anchor_cannot_start_before_a_valid_pair(tmp_path):
    anchor = tmp_path / "anchor.json"
    anchor.write_text('{"status": "WAITING_FOR_G_GATE"}')
    with pytest.raises(ValueError, match="has not been admitted"):
        matrix.load_anchor(matrix.identity(anchor), {})


@pytest.mark.parametrize("bad_oracle", [False, True])
def test_one_attempt_per_arm_and_no_ratio_without_oracle(tmp_path, monkeypatch, bad_oracle):
    path = tmp_path / "file"
    path.write_text("pinned")
    pin = matrix.identity(path)
    case = {"native_g_input": pin}
    hosts = dict(spine=pin, gr=pin)
    clock = dict(bdf=matrix.BDF, uuid="test", binary=pin, driver_reported_mhz=[150, 500, 450])
    clocks = dict(spine=clock, gr=clock)
    row = dict(attempts=[], arms={})
    calls = []

    def execute(command, output, arm, fd, node, bdf, *, memory_gib):
        assert bdf == matrix.BDF and memory_gib == 24
        calls.append(arm)
        if arm == "gr":
            (output / "gr-oracle.txt").write_text(
                f"status=PASS mismatches={int(bad_oracle)} checked_words=2 touched_segments=1\n")
        return arm

    reservation = SimpleNamespace(own=tmp_path, sample=Mock(return_value={"admitted": True}))
    monkeypatch.setattr(matrix, "lease", lambda *_: nullcontext(("render", 3)))
    monkeypatch.setattr(matrix, "unthrottled", lambda _: None)
    monkeypatch.setattr(matrix.containment, "other_builds", lambda: [])
    monkeypatch.setattr(matrix, "paired_loader", lambda *_: {})
    monkeypatch.setattr(matrix.clocks, "image", lambda *_: {})
    monkeypatch.setattr(matrix.clocks, "capture", lambda *_: clock)
    monkeypatch.setattr(matrix.clocks, "replay", lambda evidence: evidence)
    monkeypatch.setattr(matrix, "execute", execute)
    monkeypatch.setattr(matrix, "inspect", lambda _, arm, __: {"setup_inclusive_ns": 200 if arm == "gr" else 100})
    args = (case, row, tmp_path, 0, reservation, {"tree_memory_gib": 24}, hosts, clocks, {}, lambda: None)
    if bad_oracle:
        with pytest.raises(ValueError, match="PMA readback"):
            matrix.measure(*args)
        assert "speedup_gr_over_spine" not in row
    else:
        matrix.measure(*args)
        assert row["speedup_gr_over_spine"] == 2.0
    assert calls == row["attempts"] == ["spine", "gr"]
