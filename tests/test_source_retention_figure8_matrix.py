"""Check that the Figure 8 continuation preserves the anchor and one-shot policy."""

from contextlib import nullcontext
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    figure8_matrix as matrix, figure8_qualified_pair as qualified, figure8_spine_follow as follow,
)


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


@pytest.mark.parametrize("changed_speedup", [False, True])
def test_spine_follow_reuses_only_a_matching_verified_anchor(tmp_path, monkeypatch, changed_speedup):
    path = tmp_path / "graph"
    path.write_text("graph")
    pin = matrix.identity(path)
    case = {"native_g_input": pin}
    timers = {"spine": {"setup_inclusive_ns": 100}, "gr": {"setup_inclusive_ns": 200}}
    evidence = {arm: {"timer": timer} for arm, timer in timers.items()}
    dataset, updates = matrix.ANCHOR
    old = dict(dataset=dataset, updates=updates, input=pin, attempts=[], arms={},
               status="REUSED_MEASURED_ANCHOR", timers=timers,
               speedup_gr_over_spine=1.0 if changed_speedup else 2.0)
    prior = dict(boundary=matrix.au.BOUNDARY, requested_runs_per_arm=1, warmups=0,
                 manifest=pin, anchor=pin, cases=[old])
    monkeypatch.setattr(matrix, "load_cases", lambda *_: {matrix.ANCHOR: case})
    monkeypatch.setattr(matrix, "load_anchor", lambda *_: ({}, {}, {}, timers, evidence))
    if changed_speedup:
        with pytest.raises(ValueError, match="independently replayed AU/512"):
            follow.replay_prior(prior, matrix.ANCHOR)
    else:
        assert follow.replay_prior(prior, matrix.ANCHOR)[1]["arms"] == evidence


@pytest.mark.parametrize("mutation", [None, "bdf", "timer", "ratio", "gate"])
def test_spine_follow_same_card_replays_qualified_pair(tmp_path, monkeypatch, mutation):
    path = tmp_path / "pinned"
    path.write_text("evidence")
    pin = matrix.identity(path)
    case = {"native_g_input": pin}
    hosts = dict(spine=pin, gr=pin)
    bdf = "0000:82:00.1"
    board = (0, bdf)
    clock = dict(bdf=bdf, uuid="id", binary=pin, driver_reported_mhz=[150, 500, 450, 0])
    gate = dict(reference=pin, candidate_clock=clock)
    commands = {
        "spine": matrix.spine_command(path, path, path, board=board),
        "gr": matrix.au.gr_command(path, path, path, path, board=board),
    }
    arms = {arm: dict(run=dict(command=matrix.AFFINITY + list(map(str, cmd)), stderr=pin),
                      timer=dict(setup_inclusive_ns=100), clock_evidence=dict(clock))
            for arm, cmd in commands.items()}
    arms["gr"]["pma_oracle"] = pin
    dataset, updates = matrix.ANCHOR
    row = dict(dataset=dataset, updates=updates, input=pin, status="MEASURED_SETUP_ONLY",
               attempts=["spine", "gr"], arms=arms, speedup_gr_over_spine=1.0)
    prior = dict(row=row, hosts=hosts, bdf=bdf, spine_image=pin, stage={},
                 baseline_g=gate, xrt_libraries={})
    monkeypatch.setattr(follow.clocks, "replay", lambda value: value)
    monkeypatch.setattr(follow.qualified, "qualified_g", lambda *_: (gate, pin))
    monkeypatch.setattr(follow.au, "pma_oracle", lambda _: None)
    monkeypatch.setattr(matrix, "inspect", lambda *_, **__: dict(setup_inclusive_ns=100))
    if mutation == "bdf":
        arms["spine"]["clock_evidence"]["bdf"] = matrix.BDF
    elif mutation == "timer":
        arms["gr"]["timer"]["setup_inclusive_ns"] += 1
    elif mutation == "ratio":
        row["speedup_gr_over_spine"] = 0.5
    elif mutation == "gate":
        prior["baseline_g"] = {**gate, "reference": {**pin, "sha256": "different"}}
    if mutation is None:
        assert follow.replay_qualified(prior, matrix.ANCHOR, case)[1:3] == (row, hosts)
    else:
        with pytest.raises(ValueError, match="same-card"):
            follow.replay_qualified(prior, matrix.ANCHOR, case)


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
@pytest.mark.parametrize("board", [(matrix.DEVICE, matrix.BDF), (0, "0000:82:00.1")])
def test_one_attempt_per_arm_and_no_ratio_without_oracle(tmp_path, monkeypatch, bad_oracle, capacity_retry, board):
    path = tmp_path / "file"
    path.write_text("pinned")
    pin = matrix.identity(path)
    case = {"native_g_input": pin}
    hosts = dict(spine=pin, gr=pin)
    device, card = board
    clock = dict(bdf=card, uuid="test", binary=pin, driver_reported_mhz=[150, 500, 450])
    clocks = dict(spine=clock, gr=clock)
    row = dict(attempts=[], arms={})
    if capacity_retry:
        row["arms"]["spine"] = {"timer": {"setup_inclusive_ns": 100}}
    arms = ("gr",) if capacity_retry else ("spine", "gr")
    replicas = 1 if capacity_retry else 4
    calls = []

    def execute(command, output, arm, fd, node, bdf, *, memory_gib):
        assert bdf == card and memory_gib == 24
        assert f"XCL_DEVICE_INDEX={device}" in command
        if arm == "spine":
            assert f"SPINE_EXPECT_BDF={card}" in command
        else:
            assert f"GRASU_REGRAPH_EXPECT_BDF={card}" in command
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
    monkeypatch.setattr(matrix, "inspect",
                        lambda _, arm, __, *, bdf: {"setup_inclusive_ns": 200 if arm == "gr" else 100})
    args = (case, row, tmp_path, 0, reservation, {"tree_memory_gib": 24}, hosts, clocks, {}, lambda: None)
    kwargs = dict(arms=arms, replicas=replicas, board=board)
    if bad_oracle:
        with pytest.raises(ValueError, match="PMA readback"):
            matrix.measure(*args, **kwargs)
        assert "speedup_gr_over_spine" not in row
    else:
        matrix.measure(*args, **kwargs)
        assert row["speedup_gr_over_spine"] == 2.0
    assert calls == row["attempts"] == list(arms)


@pytest.mark.parametrize("passes", [False, True])
def test_qualified_pair_waits_for_exact_g_and_uses_its_board_and_clocks(tmp_path, monkeypatch, passes):
    graph = tmp_path / "graph"
    graph.write_text("pinned graph")
    pin = matrix.identity(graph)
    group = tmp_path / "group"
    group.mkdir()
    (group / "memory.peak").write_text("1024\n")
    (group / "memory.events").write_text("high 0\n")
    out = tmp_path / "out"
    args = SimpleNamespace(**dict.fromkeys(
        ("manifest", "spine_host", "gr_host", "spine_image", "g_report", "g_reference"), graph),
        **dict.fromkeys(("manifest_sha256", "spine_host_sha256", "gr_host_sha256", "spine_image_sha256"),
                        pin["sha256"]),
        output=out, g_unit="g.service", g_invocation="1" * 32, g_wait_seconds=30, board_wait_seconds=60)
    monkeypatch.setattr(matrix, "exact_service", Mock())
    monkeypatch.setattr(matrix, "load_cases", lambda *_: {matrix.ANCHOR: {"native_g_input": pin}})
    monkeypatch.setattr(matrix, "service_state", lambda _: {})
    ready = Mock(return_value=True) if passes else Mock(side_effect=ValueError("failed G gate"))
    monkeypatch.setattr(qualified.follow, "ready", ready)
    candidate = dict(bdf="0000:82:00.1", driver_reported_mhz=[150, 500, 450, 0], binary=pin)
    monkeypatch.setattr(qualified, "qualified_g",
                        lambda *_: (dict(candidate_clock=candidate, report=pin, reference=pin), pin))
    monkeypatch.setattr(qualified.au, "memory_group", lambda: group)
    monkeypatch.setattr(qualified.containment, "verify", lambda *_, **__: {"limits": {}})
    monkeypatch.setattr(qualified, "Lease", Mock())
    monkeypatch.setattr(qualified, "paired_loader", lambda *_: {})
    monkeypatch.setattr(qualified.clocks, "image", lambda *_: {"uuid": "spine", "binary": pin})
    measure = Mock()
    monkeypatch.setattr(matrix, "measure", measure)
    if not passes:
        with pytest.raises(ValueError, match="failed G gate"):
            qualified.run(args)
        measure.assert_not_called()
        report = json.loads((out / "results.json").read_text())
        assert report["row"]["attempts"] == []
        assert report["status"] == "FAILED_RETAINED"
        return
    result = qualified.run(args)
    assert result["status"] == "MEASURED_QUALIFIED_AU512_SETUP_ONLY"
    measure.assert_called_once()
    assert measure.call_args.kwargs["board"] == (0, candidate["bdf"])
    clocks = measure.call_args.args[7]
    assert clocks["gr"] == candidate
    assert clocks["spine"]["driver_reported_mhz"] == candidate["driver_reported_mhz"]
