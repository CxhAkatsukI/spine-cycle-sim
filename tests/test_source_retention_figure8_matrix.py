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


def anchor_state(**changes):
    return dict({"LoadState": "loaded", "InvocationID": "1" * 32, "MainPID": "100",
                 "Result": "success", "ExecMainStatus": "0", "ActiveState": "active",
                 "SubState": "running"}, **changes)


def test_wait_for_exact_anchor_to_exit_before_reading_receipt(tmp_path, monkeypatch):
    path = tmp_path / "anchor.json"
    states = iter((anchor_state(), anchor_state(LoadState="not-found", InvocationID="")))
    monkeypatch.setattr(matrix, "service_state", lambda _: next(states))
    observed = []

    def finish(seconds):
        assert 0 < seconds <= 30 and len(observed) == 1
        path.write_text('{"status":"MEASURED_AU512_SETUP_ONLY"}')

    monkeypatch.setattr(matrix.time, "sleep", finish)
    assert matrix.wait_anchor(path, "au.service", "1" * 32, 60, observed.append) == matrix.identity(path)
    assert [state["LoadState"] for state in observed] == ["loaded", "not-found"]


@pytest.mark.parametrize("state", [
    anchor_state(InvocationID="2" * 32),
    anchor_state(ActiveState="failed", SubState="failed", Result="exit-code", MainPID="0"),
    anchor_state(LoadState="not-found", InvocationID=""),
])
def test_wait_rejects_wrong_or_failed_anchor_even_with_receipt(tmp_path, monkeypatch, state):
    path = tmp_path / "anchor.json"
    path.write_text('{"status":"MEASURED_AU512_SETUP_ONLY"}')
    monkeypatch.setattr(matrix, "service_state", lambda _: state)
    with pytest.raises(ValueError, match="service disappeared|terminated unsuccessfully"):
        matrix.wait_anchor(path, "au.service", "1" * 32, 60, lambda _: None)


@pytest.mark.parametrize("bad_oracle", [False, True])
@pytest.mark.parametrize("capacity_retry", [False, True])
def test_one_attempt_per_arm_and_no_ratio_without_oracle(tmp_path, monkeypatch, bad_oracle, capacity_retry):
    path = tmp_path / "file"
    path.write_text("pinned")
    pin = matrix.identity(path)
    case = {"native_g_input": pin}
    hosts = dict(spine=pin, gr=pin)
    clock = dict(bdf=matrix.BDF, uuid="test", binary=pin, driver_reported_mhz=[150, 500, 450])
    clocks = dict(spine=clock, gr=clock)
    row = dict(attempts=[], arms={})
    if capacity_retry:
        row["arms"]["spine"] = {"timer": {"setup_inclusive_ns": 100}}
    arms = ("gr",) if capacity_retry else ("spine", "gr")
    replicas = 1 if capacity_retry else 4
    calls = []

    def execute(command, output, arm, fd, node, bdf, *, memory_gib):
        assert bdf == matrix.BDF and memory_gib == 24
        assert f"XCL_DEVICE_INDEX={matrix.DEVICE}" in command
        if arm == "spine":
            assert f"SPINE_EXPECT_BDF={matrix.BDF}" in command
        else:
            assert f"GRASU_SHARDED_METADATA_REPLICAS={replicas}" in command
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
    kwargs = dict(arms=arms, replicas=replicas)
    if bad_oracle:
        with pytest.raises(ValueError, match="PMA readback"):
            matrix.measure(*args, **kwargs)
        assert "speedup_gr_over_spine" not in row
    else:
        matrix.measure(*args, **kwargs)
        assert row["speedup_gr_over_spine"] == 2.0
    assert calls == row["attempts"] == list(arms)
