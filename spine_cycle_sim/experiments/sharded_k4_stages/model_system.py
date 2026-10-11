"""Bounded complete SSSP candidate gates, explicitly separate from timing admission."""

import json
from pathlib import Path
import re

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import source_snapshot, verify_source_snapshot
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .execution import identity

REPORT = ("PASS: 13 whole routed SSSP cases (11 convergence, 1 fixed-round, 1 expected limit failure); "
          "full state, source replicas, padding, scheduling and traffic; 9 admission rejections PASS")
FIELDS = ("vertices", "reverse", "stop", "pressure", "fixed", "limit", "rounds", "failed", "cycles", "parents", "beats")


def require_system_report(text: str) -> list[dict]:
    lines = text.strip().splitlines()
    if len(lines) != 14 or lines[-1] != REPORT:
        raise ValueError("complete 13-execution and nine-rejection system gate is required")
    expression = "case " + " ".join(field + r"=(\d+)" for field in FIELDS)
    rows = []
    for line in lines[:-1]:
        match = re.fullmatch(expression, line)
        if not match:
            raise ValueError("invalid whole-system execution record")
        rows.append(dict(zip(FIELDS, map(int, match.groups()))))
    expected = set()
    for vertices, pressure, rounds in ((129, 0, 4), (65569, 0, 4), (262273, 0, 5), (129, 1, 4)):
        for reverse in (0, 1):
            expected.add((vertices, reverse, 1, pressure, 0, 128, rounds, 0))
    expected.update((129, reverse, 0, 0, 0, 128, 4, 0) for reverse in (0, 1))
    expected.update(((129, 0, 1, 0, 0, 128, 1, 0), (129, 0, 1, 0, 2, 128, 2, 0), (129, 0, 1, 0, 0, 1, 1, 1)))
    observed = {tuple(row[field] for field in FIELDS[:8]) for row in rows}
    if observed != expected or len(observed) != len(rows):
        raise ValueError("system gate changed or duplicated its predeclared matrix")
    for row in rows:
        if row["cycles"] <= 0 or row["parents"] <= 0 or row["beats"] < row["parents"]:
            raise ValueError("empty or inconsistent whole-system transaction record")
        if row["reverse"]:
            counterpart = [other for other in rows if other == {**row, "reverse": 0}]
            if len(counterpart) != 1:
                raise ValueError("registration-order execution records differ")
    return rows


def validate_system(root: Path, core_build: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    contract_path = root / "configs/experiments/grasu_component_refactor_v1.json"
    snapshot = source_snapshot(root, contract_path, json.loads(contract_path.read_text()))
    gate_sources = [identity(root / path) for path in (
        "cpp/tests/routed_regraph/system_tests.cpp", "scripts/validate_sharded_k4_system_model.py",
        "scripts/package_sharded_k4_adapter_gates.py")]
    atomic_write_json(output / "source_before.json", snapshot)
    attempts = []
    for name, command, timeout in (
        ("build", ["cmake", "--build", str(core_build), "--target", "routed_regraph_system_tests", "-j2"], 300),
        ("system", ["taskset", "-c", "112-113", str(core_build / "cpp/routed_regraph_system_tests")], 600),
    ):
        resource = run_bounded(command, root, output / name, timeout=timeout, memory_gib=8, reserve_gib=16)
        attempts.append({"name": name, "resources": resource})
        atomic_write_json(output / "attempts.json", attempts)
        if resource["exit_code"] or resource["timed_out"]:
            raise RuntimeError(f"whole-system {name} failed; raw logs retained")
    rows = require_system_report((output / "system.stdout.txt").read_text())
    verify_source_snapshot(root, snapshot)
    if any(identity(Path(pin["path"])) != pin for pin in gate_sources):
        raise ValueError("system fixture or CLI changed during validation")
    artifacts = [core_build / name for name in (
        "cpp/routed_regraph_system_tests", "cpp/libspine_cycle_core.a", "CMakeCache.txt",
        "cpp/CMakeFiles/spine_cycle_core.dir/flags.make",
        "cpp/CMakeFiles/routed_regraph_system_tests.dir/link.txt",
    )]
    result = {"schema_version": 1, "status": "PASS", "source": snapshot,
              "artifacts": [identity(path) for path in artifacts], "gate_sources": gate_sources, "attempts": attempts,
              "report": REPORT, "rows": rows, "source_unchanged": True,
              "converged_executions": 11, "fixed_round_executions": 1, "expected_limit_failures": 1,
              "claim": "complete_candidate_SSSP_functionality_and_finite_ledgers_not_hardware_timing",
              "sst_candidate_profile_selected": False}
    atomic_write_json(output / "summary.json", result)
    return result
