"""Qualification of a new AU CC image must not change the original baseline."""

import json
from pathlib import Path

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    cc_au_revision as revision,
    spine_cc_warm_receipt as warm,
    spine_smoke,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity, save


def file(root, name, text):
    path = root / name
    path.write_text(text)
    return identity(path)


@pytest.fixture
def route(tmp_path):
    host = file(tmp_path, "host", "executable")
    Path(host["path"]).chmod(0o700)
    image = file(tmp_path, "candidate.xclbin", "different bitstream")
    spec = dict(host=host, image=image, abi="a" * 64, linked_image="/route/candidate.xclbin")
    spec["manifest"] = file(tmp_path, "candidate.xclbin.weighted-manifest",
                            f"build_sha256 {spec['abi']}\nimage_sha256 {image['sha256']}\ntarget hw\n")
    spec["link"] = file(tmp_path, "link.log", f"INFO: [v++ 60-586] Created {spec['linked_image']}\n"
                       "INFO: [v++ 60-1307] Run completed. Additional information can be found in:\n")
    spec["timing"] = file(tmp_path, "timing.rpt", "All user specified timing constraints are met.\n")
    spec["skew"] = file(tmp_path, "skew.rpt", " Slow 0.133 0.130 0.003\n2. Bus Skew Report Per Constraint\n")
    return spec


@pytest.mark.parametrize("fault", [None, "image", "abi", "wrong_link", "unfinished_link", "skew", "timing"])
def test_route_must_match_declared_successful_hardware(tmp_path, route, fault):
    if fault == "image":
        file(tmp_path, "candidate.xclbin", "substitution")
    elif fault == "abi":
        route["abi"] = "other"
    elif fault == "wrong_link":
        route["linked_image"] = "/other/candidate.xclbin"
    elif fault == "unfinished_link":
        route["link"] = file(tmp_path, "link.log", f"INFO: [v++ 60-586] Created {route['linked_image']}\n")
    elif fault == "skew":
        route["skew"] = file(tmp_path, "skew.rpt", " Slow 0.133 0.139 -0.006\n")
    elif fault == "timing":
        route["timing"] = file(tmp_path, "timing.rpt", "Timing constraints are not met.\n")
    if fault:
        with pytest.raises(ValueError):
            revision.candidate_route(route)
    else:
        assert revision.candidate_route(route)["image"] == route["image"]


@pytest.mark.parametrize("diagnostic", [False, True])
@pytest.mark.parametrize("fault", [None, "miss", "mismatched_receipt", "image", "wrong_case"])
def test_anchor_preserves_stage_screen_scope(tmp_path, monkeypatch, diagnostic, fault):
    figure = revision.figure
    image = {"sha256": "a" * 64}
    gates = {"image": image, "resident_mhz": [150, 500, 450, 0]}
    miss = diagnostic or fault == "miss"
    decision = dict(retention_gate_pass=not miss, candidate_over_reference=1.21 if miss else 1.12,
                    equal_driver_reported_clocks=True)
    report = dict(status=f"PAIRED_ACTIVE_MIN_R_GATE_{'FAILED_RETAINED' if miss else 'PASS'}",
                  algorithm="cc", comparison=decision)
    pin = file(tmp_path, "au-r", json.dumps(report))
    stage = dict(report=pin, comparison={**decision}, candidate_clock=dict(binary=image,
                 driver_reported_mhz=gates["resident_mhz"]))
    if fault == "mismatched_receipt":
        stage["comparison"]["candidate_over_reference"] = 1.1
    if fault == "image":
        stage["candidate_clock"]["binary"] = {}
    extra = {"amazon_odd": {}, "au_slice": stage}
    child = dict(status=figure.MEASURED, algorithm="cc", dataset="R19" if fault == "wrong_case" else "AU",
                 additional_r_gates=extra, stage_gates=gates, retained_spine={})
    arm = file(tmp_path, "arm", json.dumps(child))
    if diagnostic:
        anchor = file(tmp_path, "matrix", json.dumps(dict(algorithm="cc", r_retention_all_controls_pass=False,
                      cases={"AU": {"result": arm, "status": figure.MEASURED}}, baseline=gates,
                      additional_r_gates=extra)))
    else:
        anchor = arm

    def measured(*args, topology_miss):
        assert topology_miss == (stage if diagnostic else None)
        return dict(stage_ratios={"r_ratios": {}}, stage_receipts={})

    monkeypatch.setattr(figure, "measured", measured)
    if fault and (not diagnostic or fault == "wrong_case"):
        with pytest.raises(ValueError):
            revision.anchor_pair(anchor)
    else:
        actual, _, pair, status = revision.anchor_pair(anchor)
        assert actual == arm
        assert status == (revision.DIAGNOSTIC if diagnostic else revision.MATCHED)
        if not diagnostic:
            assert pair["stage_ratios"]["r_ratios"]["au_slice"] == 1.12
            assert pair["stage_receipts"]["r_au_slice"] == pin


@pytest.mark.parametrize("status,fault", [(revision.MATCHED, None), *(
    (revision.DIAGNOSTIC, fault) for fault in [None, "clock", "abi", "host", "throttled", "baseline_wall", "oracle"]
)])
def test_replay_pins_arms_and_keeps_zero_round_wins(tmp_path, monkeypatch, route, status, fault):
    files = revision.candidate_route(route)
    data = {key: file(tmp_path, key, key) for key in ("source", "graph", "update")}
    data.update(vertices=20, edges=30, updates=2)
    inputs = file(tmp_path, "inputs.json", json.dumps(data))
    gr_log = file(tmp_path, "gr.stdout", f"GRASU_REGRAPH_DEVICE bdf={warm.BDF}\n"
                  "GRASU_SHARDED_UPDATE_REPEAT_CONFIG repeats=1 restore_pma_between_repeats=1\n"
                  "CC_PMA_NATIVE_SHARDED_INPUT vertices=20 static_edges=30 logical_updates=2 physical_updates=2 "
                  "final_edges=32 resident_state=old_graph_converged oracle_converged=1\n"
                  "CC_PMA_NATIVE_SHARDED_RESULT vertices=20 logical_updates=2 physical_updates=2 final_edges=32 "
                  "resident_state=old_graph_converged oracle_converged=1 status=PASS mismatches=0 hardware_converged=1 "
                  "k4_frontends=4 shared_regraph_downstream=1 conversion_cost=absent executed_supersteps=1\n"
                  "SHARDED_RESIDENT_BATCH_WALL algorithm=CC_PMA_NATIVE status=PASS layout=trace_aware "
                  "physical_update_mapping=offline pack_upload_and_host_seed_ms=1 pack_to_final_readback_ms=2\n")
    anchor, arm, spec = (file(tmp_path, key, key) for key in ("anchor", "arm", "spec"))
    previous = dict(gr_ms=3 if fault == "baseline_wall" else 2, spine_ms=4, comparison=arm,
                    boundary="resident_old_graph_host_pack_to_final_readback",
                    raw={"gr": {"stdout": gr_log}}, clocks_mhz={"gr": [150, 500, 450]})
    prepared = dict(anchor=anchor, prior=previous, inputs=inputs, arm=arm, candidate=spec, files=files, abi=route["abi"],
                    result_status=status)
    previous["stage_ratios"] = {"r_ratios": {"au_slice": 1.21}}
    clock = dict(binary=files["image"], bdf=warm.BDF, driver_reported_mhz=[150, 500, 450])
    if fault == "clock":
        clock["driver_reported_mhz"][0] = 145
    monkeypatch.setattr(revision.clocks, "replay", lambda evidence: clock)
    command = ["/usr/bin/taskset", "-c", "124,125", files["host"]["path"], "--xclbin", files["image"]["path"],
               "--hot", "0", "--mode", "partial", "--samples", "1",
               "--slice", data["graph"]["path"], "--update", data["update"]["path"]]
    if fault == "host":
        command[3] = "another-host"
    mode = "sample=0 order=0 hot=0 full=0 batch=0"
    abi = "wrong" if fault == "abi" else route["abi"]
    spine_log = file(tmp_path, "spine.stdout", f"CC_SETUP vertices=20 source_config_sha256={abi}\n"
                     f"CC_BOOTSTRAP_PASS {mode} valid=1\n"
                     f"CC_UPDATE_PASS {mode} physical_records=2 logical_deletions=0 rounds=0 valid=1\n"
                     f"CC_RESIDENT_WALL {mode} vertices=20 physical_records=2 "
                     "host_pack_to_final_readback_ms=1 batch_resident_to_final_readback_ms=0.8\n"
                     f"CC_REPAIR_PASS vertices=20 updates=1 all_raw_labels_checked={int(fault != 'oracle')} "
                     "all_raw_graphs_checked=1 all_round_work_checked=1\n")
    smoke = dict(status="RESIDENT_CC_STATE_WORK_AND_CLOCK_PASS_NOT_PERFORMANCE_ADMISSION",
                 performance_admission=False, errors=[], workload=data, bdf=warm.BDF, device=0, clock_evidence={},
                 execution=dict(host_affinity=list(warm.AFFINITY), command=command, exit_code=0,
                                stop_reason="process_exit", cleanup_snapshot_error=None, cleanup_signaled_pids=[]),
                 pins=[files["host"], files["image"], files["manifest"], inputs, data["source"], data["graph"],
                       data["update"], identity(spine_smoke.__file__)],
                 memory_events=f"high {int(fault == 'throttled')}\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n",
                 stdout=spine_log, stderr=file(tmp_path, "spine.stderr", ""))
    path = tmp_path / "smoke.json"
    save(path, smoke)
    if fault:
        with pytest.raises(ValueError):
            revision.replay(prepared, identity(path))
    else:
        result = revision.replay(prepared, identity(path))
        assert result["status"] == status
        assert result["old_spine_ms"] == 4
        assert result["new_pair"]["gr_over_spine"] == 2
        assert result["new_pair"]["spine_rounds"] == 0
