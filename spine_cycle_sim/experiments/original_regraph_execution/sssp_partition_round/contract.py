"""Bind reported experiment declarations to the commands actually executed."""

from pathlib import Path

from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from .analysis import MATRIX


SCOPE = "multi_partition_extension_of_unchanged_single_round_model_not_hardware_performance"
TIMEOUT = 180
MAX_CYCLES = 100000000


def worker_command(python, run, source, basis, maximum):
    return [python, "-m", __package__ + ".study", "--worker", "--output", str(run),
            "--source", str(source), "--baseline", str(basis), "--max-cycles", str(maximum)]


def execution_contract(root: Path, run: Path, report: dict, basis: dict, contract: dict) -> None:
    for key in ("memory", "model", "boundary", "compiler_version", "cmake_cache"):
        if not same_typed(report[key], basis[key]):
            raise ValueError("reported numerical contract differs from basis: " + key)
    if (report["scope"] != SCOPE or report["schema_version"] != 2
            or not same_typed(report["declared_matrix"], [list(row) for row in MATRIX])
            or type(report["maximum_cycles_per_path"]) is not int
            or not 0 < report["maximum_cycles_per_path"] <= MAX_CYCLES
            or report["subprocess_timeout_seconds"] != TIMEOUT):
        raise ValueError("declared matrix or execution budget changed")
    if [item["path"] for item in report["inputs"]] != [str(run / "inputs" / mode) for mode in ("cold", "warm_update")]:
        raise ValueError("initial-state paths differ from declared scenarios")
    expected = [("author_layout", [basis["probe"]["binary"], str(run / "topology.txt"),
                                 str(run / "author_capture"), str(contract["seed"]), "1"])]
    for mode, latency, reverse in MATRIX:
        label = f"{mode}_lat{latency}_reverse{reverse}"
        expected.append((label, [report["executor"]["path"], str(run / "inputs" / mode),
                                str(run / "states" / label), str(latency), str(reverse),
                                str(report["maximum_cycles_per_path"])]))
    if len(report["runs"]) != len(expected):
        raise ValueError("raw execution matrix length changed")
    for record, (label, command) in zip(report["runs"], expected, strict=True):
        if (record["label"] != label or record["command"] != command or record["cwd"] != str(root)
                or record["stdout"] != str(run / "raw" / (label + ".stdout.txt"))
                or record["stderr"] != str(run / "raw" / (label + ".stderr.txt"))):
            raise ValueError("raw command or path differs from declared case: " + label)
    if [(case["mode"], case["latency"], case["reverse"]) for case in report["cases"]] != list(MATRIX):
        raise ValueError("case declarations differ from actual commands")
    for case in report["cases"]:
        if len(case["paths"]) != 2 or any(type(path["cycles"]) is not int or not
                0 < path["cycles"] <= report["maximum_cycles_per_path"] for path in case["paths"]):
            raise ValueError("observed path cycles exceed the declared execution budget")


def watchdog_contract(root, run, report, watchdog):
    command = worker_command(report["python_executable"], run, report["selection"]["source"]["path"],
                             report["basis"]["path"], report["maximum_cycles_per_path"])
    if (watchdog["command"] != command or watchdog["cwd"] != str(root)
            or watchdog["timeout_seconds"] != 1500
            or watchdog["cleanup_scope"] != "pidfd_bound_observed_workers_not_cgroup_containment"):
        raise ValueError("outer command or watchdog contract changed")
