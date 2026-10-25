"""Repeat Amazon controls using frozen original-R host and oracle artifacts.

Execute this file with PYTHONPATH pointing at the admitted original-R worktree.
The historical runner's render-node mapping is deliberately not reused: DRM
minor numbers changed after reboot, while the PCI identity remained stable.
"""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess


def identity(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def save(path, value):
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


@contextmanager
def lease(device, bdf):
    nodes = [node for node in Path("/sys/class/drm").glob("renderD*")
             if (node / "device").resolve().name == bdf]
    if len(nodes) != 1:
        raise ValueError("exactly one render node must match the requested PCI BDF")
    fd = os.open(f"/tmp/chuxiao-sharded-k4-board-{device}.lock",
                 os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield Path("/dev/dri") / nodes[0].name, fd
    finally:
        os.close(fd)


def run(args):
    from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import runtime
    from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import analysis
    from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "publication_match": False,
              "scope": "Amazon static fixed-point PR, one superstep, no convergence",
              "rows": [], "errors": [], "runner": identity(__file__),
              "device_index": args.device, "expected_bdf": args.bdf,
              "repeats": 3, "clock_mhz": 150, "affinity": "124,125",
              "boundary": "resident enqueue-to-finish wall and overlap-aware device event span; no preparation/DMA/readback"}
    save(output / "results.json", report)
    try:
        with lease(args.device, args.bdf) as (render, fd):
            require_idle_board(render)
            for manifest_path in args.manifest:
                job = json.loads(manifest_path.read_text())
                host = Path(job["host"]["path"])
                for pin in (job["host"], job["xclbin"]):
                    if identity(pin["path"])["sha256"] != pin["sha256"]:
                        raise ValueError("frozen host or xclbin identity changed")
                runtime.require_clean_environment(host, output)
                topology = job["configuration"]
                captured = runtime.capture(host, render, output / (topology + "_runtime"))
                if captured["device"]["bdf"] != args.bdf:
                    raise ValueError("runtime board identity differs")
                cases = [case for case in job["cases"] if case["graph"] == "amazon"]
                if {case["binding"] for case in cases} != {"author_initial", "csr_degree"} or len(cases) != 2:
                    raise ValueError("both predeclared Amazon bindings are required")
                report.setdefault("manifests", []).append({"identity": identity(manifest_path),
                    "host": identity(host), "xclbin": identity(job["xclbin"]["path"]), "runtime": captured})
                for repeat in range(3):
                    for case in cases:
                        available = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                                             if line.startswith("MemAvailable:"))) * 1024
                        if available < 24 * 2**30:
                            raise MemoryError("less than 24 GiB available; no board launch")
                        require_idle_board(render)
                        runtime.unchanged(captured, render)
                        name = f"{topology}_{case['binding']}_r{repeat}"
                        destination = output / name
                        command = ["/usr/bin/taskset", "-c", "124,125", str(host), "board", case["input"],
                                   topology, case["binding"], str(destination), job["xclbin"]["path"], str(args.device)]
                        environment = dict(os.environ, ORIGINAL_R_LEASE_FD=str(fd),
                                           ORIGINAL_R_EXPECT_BDF=args.bdf, MALLOC_ARENA_MAX="2")
                        report["status"] = "RUNNING_" + name
                        report["current_command"] = command
                        save(output / "results.json", report)
                        with (output / (name + ".stdout.txt")).open("w") as stdout, \
                             (output / (name + ".stderr.txt")).open("w") as stderr:
                            subprocess.run(command, cwd=output, env=environment, pass_fds=(fd,),
                                           stdout=stdout, stderr=stderr, timeout=180, check=True)
                        observed = json.loads((destination / "result.json").read_text())
                        checked = analysis.inspect(observed, destination, case, args.bdf)
                        report["rows"].append({"topology": topology, "binding": case["binding"],
                            "repeat": repeat, "logical_edges": case["offline"]["logical_edges"],
                            "analysis": checked, "observation": observed})
                        save(output / "results.json", report)
                        print(name + " correctness PASS", flush=True)
            report["summaries"] = []
            for topology in sorted({row["topology"] for row in report["rows"]}):
                for binding in ("author_initial", "csr_degree"):
                    selected = [row for row in report["rows"] if (row["topology"], row["binding"]) == (topology, binding)]
                    if len(selected) != 3:
                        raise ValueError("all three repeats are required")
                    span_ms = statistics.median(row["analysis"]["event_span_ns"] / 1e6 for row in selected)
                    report["summaries"].append({"topology": topology, "binding": binding,
                        "event_span_ms": span_ms, "event_gteps": selected[0]["logical_edges"] / span_ms / 1e6,
                        "resident_wall_ms": statistics.median(row["analysis"]["enqueue_to_completion_ms"] for row in selected),
                        "minimum_event_ms": min(row["analysis"]["event_span_ns"] / 1e6 for row in selected),
                        "maximum_event_ms": max(row["analysis"]["event_span_ns"] / 1e6 for row in selected)})
        report["status"] = "CORRECTNESS_PASS_DIAGNOSTIC_NOT_PUBLICATION_MATCH"
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save(output / "results.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", required=True, type=int, choices=(0, 1))
    parser.add_argument("--bdf", required=True)
    print(json.dumps(run(parser.parse_args())["summaries"], indent=2))
