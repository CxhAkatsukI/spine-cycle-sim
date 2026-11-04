"""The retained AU arm must replay from the exact one-shot FPGA evidence."""

from argparse import Namespace

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    active_min_admission as admission, active_min_resident_follow as queue, cc_resident_wall as wall,
    spine_cc_layout as layout, spine_cc_warm_receipt as warm,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity, save


@pytest.fixture
def screen(tmp_path, monkeypatch):
    def pin(name, text):
        path = tmp_path / name
        path.write_text(text)
        return identity(path)

    binary = pin("warm.xclbin", "binary")
    monkeypatch.setattr(warm, "IMAGE_SHA256", binary["sha256"])
    manifest = pin("warm.xclbin.weighted-manifest", f"build_sha256 {warm.ABI}\ntarget hw\n"
                   f"image_sha256 {binary['sha256']}\n")
    pin("remote-systemd.txt", f"InvocationID={warm.ROUTE_INVOCATION}\nSubState=exited\n"
        "Result=success\nExecMainStatus=0\n")
    pin(warm.TIMING, "All user specified timing constraints are met.\n")
    pin("bus_skew_routed.rpt", "Table of Contents\n2. Bus Skew Report Per Constraint\n"
        " Slow 0.133 0.130 0.003\n2. Bus Skew Report Per Constraint\n")
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
                   execution=dict(command=cmd, host_affinity=list(range(128)), exit_code=0,
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


def test_rejects_missing_taskset_cpu(screen):
    _, receipt, _ = screen
    receipt["execution"]["host_affinity"].remove(warm.AFFINITY[-1])
    with pytest.raises(ValueError, match="one successful"):
        replay(screen)


def test_rejects_same_manifest_build_with_different_image(screen):
    root, receipt, _ = screen
    binary, manifest = receipt["pins"][:2]
    path = root / "warm.xclbin"
    path.write_text("different binary")
    new_binary = identity(path)
    path = root / "warm.xclbin.weighted-manifest"
    path.write_text(path.read_text().replace(binary["sha256"], new_binary["sha256"]))
    binary.update(new_binary)
    manifest.update(identity(path))
    with pytest.raises(ValueError, match="not the warm CC hardware image"):
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


@pytest.mark.parametrize("fault", [None, "host", "route", "workload", "command", "counts"])
def test_warm_non_au_packet_requires_exact_route_host_and_layout(screen, monkeypatch, fault):
    root, receipt, source = screen
    image, _, host = receipt["pins"][:3]
    monkeypatch.setattr(warm, "BALANCED_HOST_SHA256", host["sha256"])
    monkeypatch.setattr(wall, "GR_HOST", host["sha256"])
    inputs = receipt["workload"]
    out = root / "su"
    out.mkdir()
    log = ("CC_BALANCED_PRELOAD hot_vertices=0 hot_edges=0 update_margin=16\n"
           "CC_LAYOUT_PASS max_n=32 family_words=44 graph_aligned_bytes=64 workspace_aligned_bytes=128\n")
    (out / "layout.stdout.txt").write_text(log)
    command = [host["path"], "--layout-only", "--hot", "balanced", "--slice", inputs["graph"]["path"],
               "--update", inputs["update"]["path"]]
    run = dict(command=command, cwd=str(out), exit_code=0, stop_reason="process_exit",
               cleanup_snapshot_error=None, cleanup_signaled_pids=[])
    report = dict(status="LAYOUT_PASS_OFFLINE", performance_admission=False, host=host,
                  rows={"su": dict(input=inputs.copy(), counts=layout.layout_counts(log, 16), execution=run)})
    if fault == "host":
        report["host"] = image
    elif fault == "route":
        (root / warm.TIMING).write_text("timing failed\n")
    elif fault == "workload":
        report["rows"]["su"]["input"]["update"] = image
    elif fault == "command":
        run["command"][2:4] = ["--hot", "0"]
    elif fault == "counts":
        (out / "layout.stdout.txt").write_text(log.replace("max_n=32", "max_n=31"))
    layout_path, packet = root / "layout.json", root / "packet.json"
    save(out / "layout.resources.json", run)
    save(layout_path, report)
    save(packet, dict(spine_host=host["path"], spine_binary=image["path"], gr_host=host["path"],
                      inputs=str(root / "inputs.json")))
    args = Namespace(algorithm="cc", cc_wall_packet=packet, cc_warm_layout=layout_path)
    case = dict(dataset="SU", graph=source["path"], vertices=515281, edges=679246, updates=16)
    if fault:
        with pytest.raises(ValueError):
            wall.configure(args, case, [source])
    else:
        configured, pins = wall.configure(args, case, [source])
        assert configured["spine_binary"] == image["path"]
        assert identity(layout_path) in pins
        assert identity(root / warm.TIMING) in pins
        assert "--samples" in wall.commands(configured | {"source": 0}, {"image": image}, out)["spine"]


def test_warm_non_au_runner_cannot_enter_board_without_additional_controls(tmp_path, monkeypatch):
    resident = queue.resident
    receipt = tmp_path / "layout.json"
    save(receipt, {})
    pin = identity(receipt)
    gate = {"host": pin, "image": pin, "g": {"candidate_clock": {"bdf": warm.BDF},
                                           "report": pin, "reference": pin}, "r": {"report": pin}}
    monkeypatch.setattr(admission, "admit", lambda *args: gate)
    monkeypatch.setattr(resident, "frozen_case", lambda *args: ({}, []))
    monkeypatch.setattr(wall, "configure", lambda *args, **kwargs: ({}, [pin]))
    monkeypatch.setattr(wall, "commands", lambda *args: {})
    args = Namespace(algorithm="cc", dataset="SU", output=tmp_path / "run", previous=None, route=None,
                     host=None, r_report=None, r_inputs=None, g_report=None, g_reference=None, wait_seconds=0,
                     cc_wall_packet=receipt, cc_warm_layout=receipt)
    with pytest.raises(ValueError, match="both the odd Amazon and AU topology R gates"):
        resident.run(args)
    assert not (args.output / "spine.stdout.txt").exists()


@pytest.mark.parametrize("missing, message", [
    (None, "reached containment"),
    ("g", "different producer receipt"),
    ("amazon_odd", "amazon_odd R receipt differs"),
    ("spine", "warm CC receipt differs"),
    ("unexpected", "do not match the replayed stages"),
])
def test_warm_au_runner_replays_all_queued_receipts(tmp_path, monkeypatch, missing, message):
    resident = queue.resident
    names = ("g", "r", "amazon_odd", "au_slice", "spine", "graph")
    paths = {name: tmp_path / f"{name}.json" for name in names}
    for name, path in paths.items():
        save(path, {"name": name})
    pins = {name: identity(path) for name, path in paths.items()}
    receipts = {name: pins[name] for name in names if name != "graph"}
    if missing == "unexpected":
        receipts[missing] = pins["graph"]
    elif missing is not None:
        del receipts[missing]
    clock = {"bdf": warm.BDF, "driver_reported_mhz": [150, 500, 450, 0]}
    gate = {"host": pins["g"], "image": pins["r"], "resident_mhz": clock["driver_reported_mhz"],
            "g": {"candidate_clock": clock, "report": pins["g"], "reference": pins["g"]},
            "r": {"report": pins["r"]}}
    monkeypatch.setattr(admission, "admit", lambda *args: gate)
    monkeypatch.setattr(admission, "pin_odd_queue", lambda *args: (pins["graph"], pins["r"], pins["amazon_odd"]))
    monkeypatch.setattr(admission, "replay_r", lambda path, *args, **kwargs:
                        {"report": identity(path), "candidate_clock": clock})
    monkeypatch.setattr(resident, "frozen_case", lambda *args: ({"graph": str(paths["graph"])}, [pins["graph"]]))
    monkeypatch.setattr(warm, "replay", lambda *args, **kwargs: ({"command": ["spine"]}, []))
    monkeypatch.setattr(wall, "configure", lambda *args, **kwargs: ({"memory_gib": 32}, []))
    monkeypatch.setattr(wall, "commands", lambda *args: {})

    def containment_probe():
        raise ValueError("reached containment")

    monkeypatch.setattr(resident.containment, "current", containment_probe)
    args = Namespace(algorithm="cc", dataset="AU", output=tmp_path / "run", previous=None, route=None,
                     host=None, r_report=None, r_inputs=None, g_report=None, g_reference=None, wait_seconds=0,
                     stage_receipts=receipts, cc_wall_packet=paths["graph"], cc_warm_au_receipt=paths["spine"],
                     cc_warm_r_controls=(paths["amazon_odd"], tmp_path, paths["au_slice"], tmp_path))
    with pytest.raises(ValueError, match=message):
        resident.run(args)


def test_odd_admission_uses_the_producers_identity_schema(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    fixture = tmp_path / "manifest.json"
    save(fixture, dict(frontier="odd-vertices", status="ACTIVE_MIN_COMPONENT_INPUTS_OFFLINE_PASS", input_pins=[]))
    monkeypatch.setattr(admission, "ODD_FIXTURE_SHA256", identity(fixture)["sha256"])
    pair = tmp_path / "pair"
    pair.mkdir()
    receipt = pair / "results.json"
    save(receipt, {})
    queue = tmp_path / "queue.json"
    producer = dict(status="PAIRED_ACTIVE_MIN_R_GATE_PASS", retention_gate_pass=True,
                    pins=[admission.artifact.identity(fixture)], result=admission.artifact.identity(receipt))
    save(queue, producer)
    assert admission.pin_odd_queue(receipt, inputs) == [identity(path) for path in (fixture, queue, receipt)]
    producer["result"]["path"] = str(tmp_path / "other.json")
    save(queue, producer)
    with pytest.raises(ValueError, match="did not admit this hardware receipt"):
        admission.pin_odd_queue(receipt, inputs)


@pytest.mark.parametrize("topology_pass", [True, False])
@pytest.mark.parametrize("completed_spine", [False, True])
def test_queue_requires_all_five_exact_producers(tmp_path, monkeypatch, topology_pass, completed_spine):
    paths = {stage: tmp_path / f"{stage}.json" for stage in ("g", "r", "odd", "au", "spine")}
    invocations = {stage: f"{i:032x}" for i, stage in enumerate(paths, 1)}
    checks = {stage: 0 for stage in paths}

    def state(unit):
        stage = unit.removesuffix(".service")
        checks[stage] += 1
        finished = checks[stage] > 1 or (stage == "spine" and completed_spine)
        if finished:
            status = queue.WARM_PASS if stage == "spine" else queue.STAGE_PASS.get(stage, queue.STAGE_PASS["r"])
            if stage == "au" and not topology_pass:
                status = "PAIRED_ACTIVE_MIN_R_GATE_FAIL"
            save(paths[stage], dict(status=status, algorithm=None if stage == "spine" else "cc"))
        return dict(LoadState="loaded", InvocationID=invocations[stage], finished=finished)

    packet = tmp_path / "packet.json"
    save(packet, dict(spine_host=str(packet), gr_host=str(packet), inputs=str(packet)))
    output = tmp_path / "queued"
    args = Namespace(algorithm="cc", dataset="AU", previous=tmp_path, output=output, stage_wait_seconds=5,
                     cc_wall_packet=packet, cc_warm_unit="spine.service", cc_warm_invocation=invocations["spine"],
                     cc_warm_au_receipt=paths["spine"],
                     g_unit="g.service", g_invocation=invocations["g"], g_report=paths["g"],
                     r_unit="r.service", r_invocation=invocations["r"], r_report=paths["r"],
                     amazon_odd_r=("odd.service", invocations["odd"], paths["odd"], tmp_path),
                     au_slice_r=("au.service", invocations["au"], paths["au"], tmp_path))
    monkeypatch.setattr(queue, "service_state", state)
    monkeypatch.setattr(queue, "route_finished", lambda state, invocation: state["finished"])
    monkeypatch.setattr(queue, "runner_pins", lambda: [])
    monkeypatch.setattr(queue.resident, "frozen_case", lambda *args: ({}, []))
    calls = []

    def run_once(child):
        calls.append(child)
        child.output.mkdir()
        result = dict(status="MEASURED_RESIDENT_PAIR")
        save(child.output / "results.json", result)
        return result

    monkeypatch.setattr(queue.resident, "run", run_once)
    if topology_pass:
        assert queue.run(args)["status"] == "MEASURED_RESIDENT_PAIR"
        (child,) = calls
        assert child.additional_r == ()
        assert child.cc_warm_r_controls == [paths["odd"], tmp_path, paths["au"], tmp_path]
        assert set(child.stage_receipts) == {"g", "r", "amazon_odd", "au_slice", "spine"}
    else:
        with pytest.raises(ValueError, match="au.service did not pass"):
            queue.run(args)
        assert calls == []
