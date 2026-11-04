"""Prepare a one-superstep active-min fixture on a second real topology."""

import argparse
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.evaluation_impact.warm_comparison import a4_preparation
from spine_cycle_sim.experiments.shared_workloads import load_slice
from .. import artifact
from ..source_build.snapshot import unchanged
from ..source_retention.runtime import save
from . import active_min_inputs


def export_edges(source, output):
    graph = load_slice(source)
    if not graph.records or graph.vertices != 1 + max(max(edge.src, edge.dst) for edge in graph.records):
        raise ValueError("A4's edge list must preserve the declared vertex extent")
    with output.open("x", encoding="ascii") as stream:
        for edge in graph.records:
            if min(edge.src, edge.dst) < 0 or edge.diff != 1:
                raise ValueError("the static fixture requires nonnegative endpoints and insertion records")
            stream.write(f"{edge.src} {edge.dst}\n")


def prepare(source, probe, host, output):
    output.mkdir(parents=True, exist_ok=False)
    receipt = output / "results.json"
    report = {"status": "PREPARING", "hardware_timing_measured": False}
    try:
        pins = [artifact.identity(path) for path in (source, probe, host)]
        report["source_pins"] = pins
        edges = output / "graph.edges"
        export_edges(source, edges)
        capture = output / "capture"
        capture.mkdir()
        stdout = output / "a4-layout.stdout.txt"
        command = [str(probe), str(edges), str(capture)]
        report["command"] = command
        with stdout.open("xb") as out, (output / "a4-layout.stderr.txt").open("xb") as err:
            subprocess.run(command, check=True, stdout=out, stderr=err, timeout=180)
        report["layout"] = a4_preparation.describe_layout({"stdout": stdout}, capture, edges)
        report["graph_edges"] = artifact.identity(edges)
        report["fixture"] = active_min_inputs.prepare(capture, host, output / "fixture")
        unchanged(pins)
        report["status"] = "ACTIVE_MIN_REAL_TOPOLOGY_OFFLINE_PASS"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(receipt, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "probe", "host", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.source.resolve(), args.probe.resolve(), args.host.resolve(),
                  args.output.resolve())["status"], flush=True)
