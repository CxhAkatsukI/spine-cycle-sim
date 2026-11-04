"""The retained AU arm must replay from the exact one-shot FPGA evidence."""

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    spine_cc_warm_receipt as warm,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity, save


@pytest.fixture
def screen(tmp_path, monkeypatch):
    def pin(name, text):
        path = tmp_path / name
        path.write_text(text)
        return identity(path)

    binary = pin("warm.xclbin", "binary")
    manifest = pin("warm.xclbin.weighted-manifest", f"build_sha256 {warm.ABI}\ntarget hw\n"
                   f"image_sha256 {binary['sha256']}\n")
    pin("remote-systemd.txt", f"InvocationID={warm.ROUTE_INVOCATION}\nSubState=exited\n"
        "Result=success\nExecMainStatus=0\n")
    pin(warm.TIMING, "All user specified timing constraints are met.\n")
    pin("bus_skew_routed.rpt", " Slow 0.133 0.130 0.003\n2. Bus Skew Report Per Constraint\n")
    source, graph, update, host = (pin(name, name) for name in ("source", "graph", "update", "host"))
    workload = dict(source=source, graph=graph, update=update, vertices=515281, edges=679246, updates=16)
    save(tmp_path / "inputs.json", workload)
    inputs = identity(tmp_path / "inputs.json")
    runner = pin("runner", "runner")
    monkeypatch.setattr(warm, "HOST_SHA256", host["sha256"])
    monkeypatch.setattr(warm, "INPUTS_SHA256", inputs["sha256"])
    monkeypatch.setattr(warm, "RUNNER_SHA256", runner["sha256"])
    mode = "sample=0 order=0 hot=0 full=0 batch=0"
    log = (f"CC_BOOTSTRAP_PASS {mode} valid=1\n"
           f"CC_UPDATE_PASS {mode} update_until_converged_ms=1 physical_records=16 "
           "logical_deletions=0 rounds=2 valid=1\n"
           f"CC_RESIDENT_WALL {mode} vertices=515281 physical_records=16 "
           "host_pack_to_final_readback_ms=2 batch_resident_to_final_readback_ms=1.5\n"
           "CC_REPAIR_PASS vertices=515281 updates=1 all_raw_labels_checked=1 all_raw_graphs_checked=1 "
           "all_round_work_checked=1\n")
    stdout, stderr = pin("stdout", log), pin("stderr", "")
    cmd = ["/usr/bin/taskset", "-c", "124,125", host["path"], "--xclbin", binary["path"], "--hot", "0",
           "--mode", "partial", "--samples", "1", "--slice", graph["path"], "--update", update["path"]]
    observed = dict(binary=binary, bdf=warm.BDF, driver_reported_mhz=[150, 500, 450])
    monkeypatch.setattr(warm.clocks, "replay", lambda evidence: observed)
    receipt = dict(status="RESIDENT_CC_STATE_WORK_AND_CLOCK_PASS_NOT_PERFORMANCE_ADMISSION",
                   performance_admission=False, errors=[], bdf=warm.BDF, device=0, workload=workload,
                   pins=[binary, manifest, host, inputs, source, graph, update, runner], clock_evidence={},
                   execution=dict(command=cmd, host_affinity=list(warm.AFFINITY), exit_code=0,
                                  stop_reason="process_exit", cleanup_snapshot_error=None, cleanup_signaled_pids=[]),
                   memory_events="low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n",
                   stdout=stdout, stderr=stderr,
                   batches=warm.spine_smoke.validate(log, vertices=515281, batches=1, physical_updates=16),
                   resident_wall_ms=dict(host_pack_to_final_readback_ms=2, batch_resident_to_final_readback_ms=1.5))
    return tmp_path, receipt, source


def replay(screen, **overrides):
    root, receipt, source = screen
    path = root / "results.json"
    save(path, receipt)
    return warm.replay(identity(path), source, **dict({"bdf": warm.BDF, "affinity": warm.AFFINITY}, **overrides))


def test_returns_exact_spine_arm(screen):
    _, receipt, _ = screen
    arm, pins = replay(screen)
    assert arm["command"] == receipt["execution"]["command"]
    assert arm["stdout"] == receipt["stdout"]
    assert pins[0]["path"].endswith("/results.json")


@pytest.mark.parametrize("override", [{"bdf": "0000:c1:00.1"}, {"affinity": (0, 1)}])
def test_rejects_nonmatching_card_or_affinity(screen, override):
    with pytest.raises(ValueError, match="same board and CPU affinity"):
        replay(screen, **override)


def test_rejects_multiple_samples(screen):
    _, receipt, _ = screen
    cmd = receipt["execution"]["command"]
    cmd[cmd.index("--samples") + 1] = "2"
    with pytest.raises(ValueError, match="one successful"):
        replay(screen)


def test_rejects_old_image_abi(screen):
    root, receipt, _ = screen
    path = root / "warm.xclbin.weighted-manifest"
    path.write_text(path.read_text().replace(warm.ABI, "old"))
    receipt["pins"][1] = identity(path)
    with pytest.raises(ValueError, match="not the warm CC hardware image"):
        replay(screen)


def test_rejects_unreplayable_wall_time(screen):
    _, receipt, _ = screen
    receipt["resident_wall_ms"]["host_pack_to_final_readback_ms"] = 3
    with pytest.raises(ValueError, match="does not replay"):
        replay(screen)


def test_rejects_invalid_old_state(screen):
    root, receipt, _ = screen
    path = root / "stdout"
    path.write_text(path.read_text().replace("batch=0 valid=1", "batch=0 valid=0", 1))
    receipt["stdout"] = identity(path)
    with pytest.raises(ValueError, match="bootstrap was not validated"):
        replay(screen)
