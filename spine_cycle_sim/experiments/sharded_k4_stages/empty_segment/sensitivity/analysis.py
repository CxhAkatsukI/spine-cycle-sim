"""Admit complete K4 outputs and conserved counters, not FPGA timing."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.analysis import MATRIX
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed

ARMS = (73, 0)
STATUS = "passed_empty_helper_sensitivity_not_hardware_calibration"
NAMES = ("k4_primary", "k4_source0", "k4_source1")


def admit(stdout: str, directory: Path, geometry: dict, basis: dict, empty_exit: int) -> dict:
    rows = [json.loads(line.removeprefix("REAL_ROUND ")) for line in stdout.splitlines()
            if line.startswith("REAL_ROUND ")]
    metadata = [json.loads(line.removeprefix("SENSITIVITY ")) for line in stdout.splitlines()
                if line.startswith("SENSITIVITY ")]
    expected = {"mode": "legacy_v4_control" if empty_exit == 73 else "empty_helper_bypass_uncalibrated",
                "empty_segment_exit_cycles": empty_exit,
                "hardware_timing_admitted": False, "publication_match_admitted": False}
    if empty_exit not in ARMS or not same_typed(metadata, [expected]) or len(rows) != 1:
        raise ValueError("missing or duplicate K4 path or sensitivity declaration")
    row = rows[0]
    reference = basis["paths"][1]
    if row.keys() != reference.keys():
        raise ValueError("K4 counter schema differs from frozen basis")
    if (row["path"] != "actual_k4" or row["passed"] is not True
            or row["full_state_and_traffic_pass"] is not True or row["replicas"] != 3
            or row["checked_words_per_replica"] != geometry["padded_vertices"]):
        raise ValueError("complete state and traffic not admitted")
    for key, value in row.items():
        if key not in {"path", "passed", "full_state_and_traffic_pass"}:
            if type(value) is not int or value < 0:
                raise ValueError("invalid K4 counter: " + key)
    if not 0 < row["cycles"] <= 100000000:
        raise ValueError("K4 cycles outside fixed budget")
    ignored = set() if empty_exit == 73 else {"cycles"}
    if not same_typed({k: v for k, v in row.items() if k not in ignored},
                      {k: v for k, v in reference.items() if k not in ignored}):
        raise ValueError("legacy cycles or conserved traffic differs from frozen basis")
    outputs = []
    for name in NAMES:
        path = directory / (name + ".u32le")
        frozen, = [item for item in basis["outputs"] if Path(item["path"]).name == path.name]
        if (path.is_symlink() or path.stat().st_size != geometry["padded_vertices"] * 4
                or sha256_file(path) != frozen["sha256"]):
            raise ValueError("complete K4 state differs from frozen basis: " + name)
        outputs.append({"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    if len({item["sha256"] for item in outputs}) != 1:
        raise ValueError("complete K4 replicas differ")
    return {"counters": row, "outputs": outputs,
            "legacy_over_arm_cycles_diagnostic_only": reference["cycles"] / row["cycles"],
            "arm_over_frozen_a4_cycles_diagnostic_only": row["cycles"] / basis["paths"][0]["cycles"]}


def matrix(cases: list[dict]) -> dict:
    expected = [(mode, latency, reverse, arm) for mode, latency, reverse in MATRIX for arm in ARMS]
    if [(c["mode"], c["latency"], c["reverse"], c["empty_exit"]) for c in cases] != expected:
        raise ValueError("sensitivity matrix missing, duplicated or reordered")
    for mode, latency, _ in MATRIX[::2]:
        for arm in ARMS:
            pair = [c for c in cases if (c["mode"], c["latency"], c["empty_exit"]) == (mode, latency, arm)]
            if (not same_typed(pair[0]["counters"], pair[1]["counters"])
                    or pair[0]["outputs"][0]["sha256"] != pair[1]["outputs"][0]["sha256"]):
                raise ValueError("registration order changed state, counters or cycles")
    for arm in ARMS:
        low, high = [c for c in cases if c["mode"] == "warm_update" and c["empty_exit"] == arm and not c["reverse"]]
        if (high["counters"]["cycles"] <= low["counters"]["cycles"]
                or low["outputs"][0]["sha256"] != high["outputs"][0]["sha256"]
                or {k: v for k, v in low["counters"].items() if k != "cycles"} != {
                    k: v for k, v in high["counters"].items() if k != "cycles"}):
            raise ValueError("latency sensitivity or conserved traffic failed")
    return {"status": STATUS, "cases": len(cases), "legacy_exact_replay": True,
            "complete_state_and_traffic": True, "registration_order_identical": True,
            "latency_sensitivity_checked": True, "convergence_comparison": False,
            "hardware_timing_admitted": False, "production_profile_modified": False,
            "publication_match_admitted": False, "strict_resource_match_admitted": False}
