"""Measure existing CC images without requiring a retained routing report."""

import argparse
import json
from pathlib import Path

from ..board_execution import memory_policy, pair_resources
from . import active_min_resident as resident, cc_resident_wall as wall, clocks
from .runtime import check_memory, identity, save


def configure(previous, dataset, inputs, spine_host, spine_image, gr_host):
    case = json.loads((previous / f"cc-{dataset.lower()}.json").read_text())
    split = json.loads(inputs.read_text())
    with Path(case["graph"]).open() as stream:
        vertices, edges, updates = map(int, stream.readline().split())
    if (case["dataset"] != dataset or split["source"]["path"] != case["graph"]
            or (split["vertices"], split["edges"], split["updates"]) != (vertices, edges, updates)):
        raise ValueError("split input does not describe the original CC workload")
    return dict(case, vertices=vertices, edges=edges, updates=updates,
                graph_slice=split["graph"]["path"], update_slice=split["update"]["path"],
                spine_host=str(spine_host), spine_binary=str(spine_image), gr_host=str(gr_host))


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(status="RUNNING", boundary=wall.BOUNDARY, repetitions_per_arm=1, warmups=0,
                  arm_timeout_seconds=args.arm_timeout_seconds,
                  admission_wait_seconds=args.admission_wait_seconds,
                  routing_report_complete=False, timing_qualification="raw routed skew report unavailable",
                  memory_profile=args.memory_profile, bdf="0000:82:00.1", device=0,
                  artifacts={name: identity(getattr(args, name))
                             for name in ("spine_host", "spine_image", "gr_host", "gr_image")},
                  cases={dataset: dict(status="NOT_STARTED") for dataset, _ in args.inputs})
    journal = args.output / "matrix.json"
    write = lambda: save(journal, report)
    write()
    with memory_policy.scope(args.memory_profile):
        group = check_memory(32, require_live_reserve=False)
        try:
            for dataset, manifest in args.inputs:
                output = args.output / dataset.lower()
                output.mkdir()
                row = report["cases"][dataset]
                row.update(status="PREPARING", arms={})
                write()
                try:
                    case = configure(args.previous, dataset, Path(manifest), args.spine_host,
                                     args.spine_image, args.gr_host)
                    row.update(case=case, inputs=str(manifest))
                    expected = {name: clocks.image(path, output, name)
                                for name, path in (("spine", args.spine_image), ("gr", args.gr_image))}
                    commands = wall.commands(case, {"image": report["artifacts"]["gr_image"]}, output)

                    def record(status, observation):
                        row.update(status=status, memory_observation=observation)
                        write()

                    with pair_resources.admit(0, report["bdf"], group,
                                              args.admission_wait_seconds, record, memory_gib=32):
                        for name in ("spine", "gr"):
                            row["status"] = "RUNNING_" + name.upper()
                            write()
                            command = ["/usr/bin/taskset", "-c", "124,125", *commands[name]]
                            row["arms"][name] = resident.arm(name, command, expected[name], output,
                                                              cc_wall=True, bdf=report["bdf"], device=0,
                                                              timeout_seconds=args.arm_timeout_seconds)
                            write()
                        pair, receipt = wall.compare(case, row["arms"], output, report["bdf"])
                        row.update(status="MEASURED_WITHOUT_RAW_SKEW_REPORT", comparison=pair, result=receipt)
                    print(dataset + ": " + json.dumps(pair), flush=True)
                except Exception as error:
                    row.update(status="FAILED", error=repr(error))
                    print(dataset + ": " + repr(error), flush=True)
                write()
            report["status"] = ("MEASURED_WITHOUT_RAW_SKEW_REPORT"
                                if all(row["status"] == "MEASURED_WITHOUT_RAW_SKEW_REPORT"
                                       for row in report["cases"].values()) else "COMPLETED_WITH_FAILURES")
        finally:
            report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
            report["memory_events"] = (group / "memory.events").read_text()
            write()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("previous", "spine-host", "spine-image", "gr-host", "gr-image", "output"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument("--inputs", nargs=2, action="append", required=True, metavar=("DATASET", "JSON"))
    parser.add_argument("--arm-timeout-seconds", type=int, default=1800,
                        help="bounded process timeout including unmeasured old-graph preparation (max 7200)")
    parser.add_argument("--admission-wait-seconds", type=int, default=600,
                        help="wait for the board and safe memory admission before either arm (max 21600)")
    parser.add_argument("--memory-profile", choices=memory_policy.PROFILES,
                        default="zfs-arc-clean-half-background5-v1")
    args = parser.parse_args()
    if not 1 <= args.arm_timeout_seconds <= 7200:
        parser.error("arm timeout must be between 1 and 7200 seconds")
    if not 1 <= args.admission_wait_seconds <= 21600:
        parser.error("admission wait must be between 1 and 21600 seconds")
    if len({dataset for dataset, _ in args.inputs}) != len(args.inputs):
        parser.error("duplicate dataset")
    run(args)


if __name__ == "__main__":
    main()
