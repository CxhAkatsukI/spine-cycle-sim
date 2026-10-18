"""Bounded complete offline matrix before actual adapter/K4 board controls."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import containment
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from .. import artifact
from ..control_validation import COMPILER, POLICY, wait_for_memory
from ..semantics import sources, study as semantics
from . import analysis, board_analysis, board_build, build, inputs

STATUS = "MATCHED_K4_A4_OFFLINE_MATRIX_COMPLETE_NOT_HARDWARE_OR_PERFORMANCE_MATCH"
HOST_STATUS = "MATCHED_K4_A4_BOARD_HOST_PREFLIGHT_COMPLETE_NOT_FPGA_OR_PERFORMANCE_MATCH"
CLAIMS = ("board_programmed", "hardware_timing_measured", "publication_match",
          "default_profile_equivalence", "adapter_performance_measured")


def run(root, validation, arithmetic, original, production, output, *, wait_seconds=0, poll_seconds=10,
        board_host=False):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {"status": "PREPARING", "errors": [], "pins": [], "rows": [], "steps": [],
              "policy": POLICY, "negative_controls": [], "board_host_preflight": board_host,
              **dict.fromkeys(CLAIMS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    group, lease = None, None
    save()

    def step(name, command, *, exit_code=0):
        record = run_bounded(command, root, output / "steps" / name,
                             timeout=120, memory_gib=2, reserve_gib=32)
        report["steps"].append({"id": name, **record})
        save()
        if record["timed_out"] or record["exit_code"] != exit_code:
            raise ValueError("unexpected bounded K4 control result: " + name)
        return record

    try:
        group = containment.current()
        report["containment"] = containment.verify(group, memory_gib=POLICY["tree_memory_gib"])
        admitted = inputs.admit(validation, arithmetic, original, production)
        source = root / "cpp/tests/original_regraph/integrated"
        report.update(admitted)
        report["pins"] += [artifact.identity(path) for path in sorted(source.glob("*")) if path.is_file()]
        runner = [Path(module.__file__) for name, module in list(sys.modules.items())
                  if name.startswith("spine_cycle_sim.") and getattr(module, "__file__", None)]
        report["pins"] += [artifact.identity(path) for path in (*runner, COMPILER)]
        report["source_kind"] = "git_worktree" if (root / ".git").exists() else "file_pinned_snapshot"
        if report["source_kind"] == "git_worktree":
            report["source_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            report["worktree_status"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines()
        report["affinity"] = sorted(os.sched_getaffinity(0))
        report["compiler_version"] = subprocess.check_output([str(COMPILER), "--version"], text=True)
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        wait_for_memory(lease, report, save, wait_seconds=wait_seconds, poll_seconds=poll_seconds)
        report["eligibility"] = {item["id"]: analysis.prepare(item) for item in admitted["inputs"]}
        (output / "bin").mkdir()
        (output / "cases").mkdir()
        save()
        builder = board_build if board_host else build
        mode, target = ("prepare", "control") if board_host else ("control", "offline")
        checker = board_analysis.prepared if board_host else analysis.inspect
        passed = board_analysis.PREPARED if board_host else analysis.PASS
        for variant in analysis.BUILDS:
            binary, dependency = output / "bin" / variant, output / "bin" / (variant + ".d")
            step("compile_" + variant, builder.command(COMPILER, source, production,
                                                       binary, dependency, variant, target))
            report["pins"] += dependency_identities(dependency, root) + [artifact.identity(binary)]
            if board_host:
                report["pins"] += [artifact.identity(path) for path in board_build.runtime_inputs()]
                linked = step("linked_" + variant, ["/usr/bin/ldd", str(binary)])
                report["pins"] += [artifact.identity(path) for path in board_build.resolved_libraries(
                    Path(linked["stdout"]).read_text(), Path(linked["stderr"]).read_text())]
            for item in admitted["inputs"]:
                expected = report["eligibility"][item["id"]]
                for binding in analysis.BINDINGS:
                    for repetition in range(2):
                        name = f"{variant}_{item['id']}_{binding}_{repetition}"
                        destination = output / "cases" / name
                        unsupported = expected["duplicates"] > 0
                        record = step(name, [str(binary), mode, item["directory"], binding,
                                             str(destination)], exit_code=1 if unsupported else 0)
                        stderr = Path(record["stderr"]).read_text()
                        row = {"build": variant, "graph": item["id"], "binding": binding,
                               "repetition": repetition, "directory": str(destination)}
                        if unsupported:
                            if ("duplicate edge rejected" not in stderr or "runtime error:" in stderr or
                                    destination.exists()):
                                raise ValueError("duplicate graph must fail before any result is emitted")
                            row.update(status=analysis.UNSUPPORTED, duplicates=expected["duplicates"],
                                       first_duplicate=expected["first_duplicate"])
                        else:
                            if stderr:
                                raise ValueError("unexpected offline K4 diagnostics")
                            observed_path = destination / "result.json"
                            observed = json.loads(observed_path.read_text())
                            checked = checker(observed, destination, expected, binding)
                            report["pins"] += (checked["pins"] if board_host else
                                               [artifact.identity(path) for path in destination.iterdir()])
                            row.update(status=passed, observation=observed, analysis=checked)
                        report["rows"].append(row)
                        save()
                        print(name + ": " + row["status"], flush=True)
        (board_analysis.matrix if board_host else analysis.matrix)(report["rows"])
        small = next(item for item in admitted["inputs"] if item["id"] == "skewed_sources")
        record = step("unknown_binding", [str(output / "bin/release"), mode, small["directory"],
                        "implicit", str(output / "negative_binding")], exit_code=1)
        if ("explicit author_initial or csr_degree" not in Path(record["stderr"]).read_text() or
                (output / "negative_binding").exists()):
            raise ValueError("invalid binding must reject before output")
        report["negative_controls"].append("unknown_binding")
        unchanged(report["pins"])
        if sources.review(original, production) != report["source_review"]:
            raise ValueError("original/production sources changed during offline control")
        report["memory_events_after"] = semantics.clean_memory_events(group)
        report["status"] = HOST_STATUS if board_host else STATUS
        report["summary"] = {"predeclared_rows": 24,
            "passing_offline_rows": sum(row["status"] == passed for row in report["rows"]),
            "unsupported_rows": sum(row["status"] == analysis.UNSUPPORTED for row in report["rows"])}
    except BaseException as error:
        report.update(status="FAILED_RETAINED", errors=[repr(error)])
        raise
    finally:
        if lease is not None:
            lease.release()
        if group is not None:
            report["memory_events_after"] = (group / "memory.events").read_text()
        report["wall_seconds"] = time.monotonic() - started
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("validation", "arithmetic", "original", "production", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--wait-seconds", type=float, default=0)
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--board-host-preflight", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[5]
    print(run(root, *(getattr(args, name).resolve() for name in
        ("validation", "arithmetic", "original", "production", "output")),
        wait_seconds=args.wait_seconds, poll_seconds=args.poll_seconds,
        board_host=args.board_host_preflight)["status"], flush=True)
