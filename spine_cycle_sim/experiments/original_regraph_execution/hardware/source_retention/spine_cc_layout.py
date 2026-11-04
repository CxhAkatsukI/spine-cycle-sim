"""Prepare and verify frozen Spine CC layouts without opening an FPGA."""

import argparse
import json
import os
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import containment
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes

from . import spine_cc_input
from .runtime import identity, save


def frozen_source(matrix, dataset):
    pins = json.loads((matrix / f"cc-{dataset}/manifest.json").read_text())["pins"]
    sources = {(Path(pin["path"]), pin["sha256"]) for pin in pins
               if Path(pin["path"]).name == f"{dataset}_connected_components_insert_u8.graph"}
    if len(sources) != 1:
        raise ValueError(f"{dataset}: expected exactly one frozen workload identity")
    return sources.pop()


def layout_counts(stdout, updates):
    preload = re.findall(r"^CC_BALANCED_PRELOAD hot_vertices=(\d+) hot_edges=(\d+) update_margin=(\d+)$",
                         stdout, re.MULTILINE)
    layout = re.findall(r"^CC_LAYOUT_PASS max_n=(\d+) family_words=(\d+) graph_aligned_bytes=(\d+) "
                        r"workspace_aligned_bytes=(\d+)$", stdout, re.MULTILINE)
    if len(preload) != 1 or len(layout) != 1 or int(preload[0][2]) != updates:
        raise ValueError("expected a single balanced layout pass with the frozen update margin")
    return dict(zip(("hot_vertices", "hot_edges", "update_margin", "max_n", "family_words",
                     "graph_aligned_bytes", "workspace_aligned_bytes"), map(int, preload[0] + layout[0])))


def layout(host, data, output, memory):
    for name in ("source", "graph", "update"):
        if identity(data[name]["path"]) != data[name]:
            raise ValueError(f"{name} identity changed before layout")
    argv = [host, "--layout-only", "--hot", "balanced", "--slice", data["graph"]["path"],
            "--update", data["update"]["path"]]
    run = run_link(list(map(str, argv)), output, output / "layout", timeout=1200,
                   tree_memory_gib=memory, reserve_gib=32,
                   environment=dict(os.environ, MALLOC_ARENA_MAX="2"))
    if run["exit_code"] or run["stop_reason"] != "process_exit" or run["cleanup_snapshot_error"]:
        raise RuntimeError("CC layout check failed; raw logs retained")
    return {"counts": layout_counts((output / "layout.stdout.txt").read_text(), data["updates"]),
            "execution": run}


def wait_for_inputs(inputs, datasets, deadline):
    receipt = inputs / "results.json"
    while True:
        if receipt.is_file():
            prepared = json.loads(receipt.read_text())
            if prepared["status"] == "INPUTS_PREPARED":
                if not set(datasets).issubset(prepared["rows"]):
                    raise ValueError("input campaign did not cover the requested datasets")
                return prepared["rows"]
            if prepared["status"] == "FAILED_RETAINED":
                raise RuntimeError(f"input preparation failed; see {receipt}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"waiting for completed input preparation: {receipt}")
        time.sleep(min(30, remaining))


def campaign(args):
    args.output.mkdir(parents=True, exist_ok=False)
    group = containment.current()
    memory = args.memory_gib or (2 if args.host is None else 24)
    guard = containment.verify(group, memory)
    if int(guard["limits"]["memory.max"]) != memory * containment.GIB:
        raise ValueError("service memory.max must equal the offline budget")
    host = identity(args.host) if args.host else None
    report = {"status": "WAITING_FOR_INPUTS" if host else "WAITING_FOR_MEMORY",
              "performance_admission": False, "host": host, "memory_budget_gib": memory, "rows": {}}
    report_path = args.output / "results.json"
    save(report_path, report)
    reservation = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    policy = dict(tree_memory_gib=memory, reserve_gib=32, allow_bounded_builds=True)
    deadline = time.monotonic() + args.wait_seconds
    try:
        prepared = wait_for_inputs(args.inputs, args.datasets, deadline) if host else None
        report["status"] = "WAITING_FOR_MEMORY"
        while True:
            report["admission"] = reservation.sample(available_memory_bytes(), containment.other_builds(),
                                                       policy, commit=True)
            if report["admission"]["admitted"]:
                break
            save(report_path, report)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MemoryError("offline layout and complete peer reservations do not fit")
            time.sleep(min(30, remaining))
        report["status"] = "RUNNING"
        save(report_path, report)
        for dataset in args.datasets:
            if available_memory_bytes() < 32 * containment.GIB:
                raise MemoryError("live reserve dropped below 32 GiB")
            source, sha = frozen_source(args.matrix, dataset)
            out = args.output / dataset
            if host is None:
                if identity(source)["sha256"] != sha:
                    raise ValueError(f"{dataset}: frozen source SHA-256 mismatch")
                data = spine_cc_input.prepare(source, out)
                if data["source"]["sha256"] != sha:
                    raise ValueError(f"{dataset}: source changed before preparation")
                report["rows"][dataset] = data
            else:
                data = json.loads((args.inputs / dataset / "inputs.json").read_text())
                if (data != prepared[dataset] or data["source"]["path"] != str(source.resolve())
                        or data["source"]["sha256"] != sha):
                    raise ValueError(f"{dataset}: frozen source pin mismatch")
                if identity(args.host) != host:
                    raise ValueError("layout host changed")
                out.mkdir()
                report["rows"][dataset] = {"input": data, **layout(args.host, data, out, memory)}
            save(report_path, report)
        report["status"] = "LAYOUT_PASS_OFFLINE" if host else "INPUTS_PREPARED"
    except Exception as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        reservation.release()
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events"] = (group / "memory.events").read_text()
        save(report_path, report)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("matrix", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--datasets", nargs="+", choices=("au", "su", "wk", "so", "pk", "lj", "lj08", "r19"),
                        required=True)
    parser.add_argument("--host", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--memory-gib", type=int, choices=(2, 24),
                        help="must match the service cap; defaults to 2 for preparation and 24 for layout")
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args(argv)
    if bool(args.host) != bool(args.inputs) or len(set(args.datasets)) != len(args.datasets):
        parser.error("provide host and prepared inputs together, and unique datasets")
    if args.host is None and args.memory_gib == 24:
        parser.error("input preparation requires a 2-GiB cap")
    if not 0 <= args.wait_seconds <= 86400:
        parser.error("wait must be between zero and 86400 seconds")
    return args


if __name__ == "__main__":
    campaign(arguments())
