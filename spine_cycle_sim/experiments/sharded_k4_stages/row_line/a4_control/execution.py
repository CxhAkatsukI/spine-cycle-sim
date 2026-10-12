"""One owner for bounded commands and unchanged executable identities."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...link_runtime import run_link
from .contract import ARMS, HARNESS, LIMITS, TARGETS, label


def commands(root: Path, output: Path):
    return [
        ("compiler", ["g++", "--version"], 1, 30),
        ("configure", ["cmake", "-S", str(root / HARNESS), "-B", str(output / "build"),
                       "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_CXX_COMPILER=/usr/bin/g++",
                       "-DBUILD_TESTING=ON", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"], 6, 300),
        ("build", ["cmake", "--build", str(output / "build"), "--target", *TARGETS, "-j2"], 6, 600),
    ]


def binary_paths(output: Path):
    return {"original": output / "build/simulator/cpp/original_regraph_sssp_real_round",
            "legacy_extracted": output / "build/routed_regraph_empty_segment_round",
            **{arm: output / "build/routed_regraph_row_line_round" for arm in ARMS}}


def case_command(output: Path, mode, latency, reverse, arm):
    name = label(mode, latency, reverse, arm)
    command = ["taskset", "-c", LIMITS["affinity"], str(binary_paths(output)[arm]),
               str(output / "inputs" / mode), str(output / "states" / name),
               str(latency), str(reverse), str(LIMITS["max_cycles"])]
    if arm == "legacy_extracted":
        command.append("73")
    elif arm in ARMS:
        command.extend(map(str, ARMS[arm]))
    return command


def require_executors(pins: dict):
    for item in pins.values():
        path = Path(item["path"])
        if path.is_symlink() or sha256_file(path) != item["sha256"]:
            raise ValueError("numerical executable changed")


def execute(root, output, report, name, command, budget, timeout):
    require_executors(report.get("executors", {}))
    prefix = output / "raw" / name
    record = run_link(command, root, prefix, timeout=timeout, tree_memory_gib=budget,
                      reserve_gib=LIMITS["reserve_gib"], poll_seconds=0.5)
    report["runs"].append({"label": name, **record})
    atomic_write_json(output / "results.json", report)
    if record["exit_code"] or record["stop_reason"] != "process_exit" or record["cleanup_snapshot_error"]:
        raise RuntimeError("bounded model control failed; attempt retained: " + name)
    return prefix.with_suffix(".stdout.txt")
