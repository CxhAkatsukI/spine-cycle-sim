"""Measure the frozen AU 131K public-source G arm once on the leased U55C."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import clocks
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.analysis import profiled_runs, records
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import (
    check_memory, execute, identity, lease, save,
)


IMAGE_SHA256 = "89c682cea8520453abd9038f7b8026bdc27298ad768a05f069f91a69a691e6ed"
INPUT_SHA256 = "33b08ea14fb244d6abe9069a6ac821e887b71f987bc27d765b3b5da084019033"
BDF = "0000:c1:00.1"
DEVICE = 1


def run(host_manifest, image, graph, output):
    group = check_memory()
    host_build = json.loads(host_manifest.read_text())
    binary = Path(host_build["binary"]["path"])
    if (host_build["status"] != "HOST_BUILD_PASS_NOT_BOARD"
            or host_build["repetitions"] != 1
            or identity(binary) != host_build["binary"]):
        raise ValueError("the exact one-shot G host is required")
    pins = {key: identity(path) for key, path in
            {"input": graph, "image": image, "host": binary, "host_build": host_manifest,
             "runner": Path(__file__)}.items()}
    if (pins["image"]["sha256"] != IMAGE_SHA256 or pins["input"]["sha256"] != INPUT_SHA256):
        raise ValueError("unexpected public-source G image or AU update batch")
    output.mkdir(parents=True, exist_ok=False)
    result = output / "results.json"
    report = {"status": "PREDECLARED", "bdf": BDF, "device": DEVICE, "pins": pins,
              "board_launch_attempted": False, "repetitions": 1, "partition_vertices": 65536,
              "boundary": "first update CU start through last update CU end; initial residency/readback excluded"}
    save(result, report)
    try:
        expected = clocks.image(image, output, "reference")
        with lease(DEVICE, BDF) as (node, fd):
            report.update(status="RUNNING_REFERENCE", board_launch_attempted=True)
            save(result, report)
            row = execute([binary, image, graph, 65536, 0, 1, DEVICE, 0],
                          output, "reference", fd, node, BDF)
            row.update(stage="G", arm="reference", repetitions=1,
                       clock_evidence=clocks.capture(BDF, expected, output, "reference"))
        report["row"] = row
        config, = records(row["stdout"]["path"], "G_CONTROL_CONFIG ")
        if (config["vertices"], config["updates"], config["shards"], config["metadata_replicas"]) != (
                515281, 131072, 8, 4):
            raise ValueError("unexpected executed reference workload")
        report["profile"] = profiled_runs(row)[0]
        if any(identity(pin["path"]) != pin for pin in pins.values()):
            raise ValueError("input, image, host or runner changed")
        report.update(status="REFERENCE_MEASURED_AWAITING_CANDIDATE", config=config)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events_final"] = (group / "memory.events").read_text()
        save(result, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("host-manifest", "image", "graph", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(run(*(path.resolve() for path in vars(args).values()))["status"])
