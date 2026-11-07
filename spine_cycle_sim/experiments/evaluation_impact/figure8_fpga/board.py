"""One measured pair per Fig. 8 case, with finite memory and board ownership."""

import argparse
import json
from pathlib import Path
import time

from ...original_regraph_execution.hardware.board_execution import memory_policy, pair_resources
from ...original_regraph_execution.hardware.source_retention import clocks
from ...original_regraph_execution.hardware.source_retention.runtime import check_memory, execute, identity, save
from . import analysis


BOUNDARY = ("initial native layout and graph upload once, then chronological batch packing, "
            "upload and update maintenance through completion; excludes parsing, FPGA programming "
            "and final validation readback; no algorithm propagation")


def command(arm, binding, case, output, args):
    device = [f"XCL_DEVICE_INDEX={args.device}", f"SPINE_EXPECT_BDF={args.bdf}",
              f"GRASU_REGRAPH_EXPECT_BDF={args.bdf}"]
    environment = ["/usr/bin/env", "-u", "XCL_EMULATION_MODE", "-u", "GRASU_RESIDENT_BATCH_WALL",
                   *device, "GRASU_UPDATE_REPEATS=1", "GRASU_SHARDED_PREMIGRATE_INPUTS=1",
                   f"GRASU_SHARDED_METADATA_REPLICAS={args.metadata_replicas}",
                   "GRASU_SHARDED_EVENT_TRACE=0", "LD_LIBRARY_PATH=/opt/xilinx/xrt/lib:/usr/lib/x86_64-linux-gnu"]
    host, image, graph = binding[arm + "_host"], binding[arm + "_image"], case["graph"]["path"]
    if arm == "spine":
        return [*environment, host, image, "--persistent-update", "--dynamic-graph", graph,
                "--batches", str(case["batches"])]
    return [*environment, host, "--persistent-update", image, graph, str(case["batches"]),
            str(output / "gr-oracle.txt")]


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    plan = json.loads(args.inputs.read_text())
    binding = json.loads(args.hardware.read_text())
    if plan["status"] != "READY":
        raise ValueError("prepared Fig. 8 input manifest required")
    report = dict(status="PREPARING", boundary=BOUNDARY, samples_per_arm=1, warmups=0,
                  timing_source="FPGA_MEASURED", metadata_replicas=args.metadata_replicas,
                  bdf=args.bdf, device=args.device, inputs=identity(args.inputs),
                  hardware=identity(args.hardware), memory_gib=args.memory_gib,
                  memory_profile=args.memory_profile, cases=[])
    journal = args.output / "results.json"
    save(journal, report)
    report["artifacts"] = {key: identity(value) for key, value in binding.items()}
    expected = {arm: clocks.image(binding[arm + "_image"], args.output, arm) for arm in ("spine", "gr")}

    def admission(status, observation):
        report.update(status=status, admission=observation)
        save(journal, report)

    with memory_policy.scope(args.memory_profile):
        group = check_memory(args.memory_gib, require_live_reserve=False)
        with pair_resources.admit(args.device, args.bdf, group, args.wait_seconds, admission,
                                  memory_gib=args.memory_gib) as (node, fd):
            for index, case in enumerate(plan["cases"]):
                if args.case and case["name"] not in args.case:
                    continue
                if identity(case["graph"]["path"]) != case["graph"]:
                    raise ValueError("input changed after preparation")
                output = args.output / case["name"]
                output.mkdir()
                row = dict(case, status="RUNNING", arms={}, order=("spine", "gr") if index % 2 == 0 else ("gr", "spine"))
                report["cases"].append(row)
                report["status"] = "RUNNING"
                save(journal, report)
                for arm in row["order"]:
                    started = time.time()
                    record = dict(status="RUNNING", started_unix=started)
                    row["arms"][arm] = record
                    save(journal, report)
                    try:
                        result = execute(command(arm, binding, case, output, args), output, arm,
                                         fd, node, args.bdf, memory_gib=args.memory_gib,
                                         timeout=args.timeout_seconds)
                        clock_evidence = clocks.capture(args.bdf, expected[arm], output, arm)
                        clock = clocks.replay(clock_evidence)
                        timing = analysis.timing(Path(result["stdout"]["path"]).read_text(), arm, case)
                        record.update(result, status="PASS", timing=timing,
                                      clock_evidence=clock_evidence, clock=clock)
                    except Exception as error:
                        record.update(status="FAILED_RETAINED", error=repr(error))
                        for stream in ("stdout", "stderr"):
                            path = output / f"{arm}.{stream}.txt"
                            if path.exists():
                                record[stream] = identity(path)
                    record["process_seconds_including_parse_program_check"] = time.time() - started
                    save(journal, report)
                    print(case["name"], arm, record["status"], record.get("timing", record.get("error")), flush=True)
                if all(arm["status"] == "PASS" for arm in row["arms"].values()):
                    frequencies = [row["arms"][arm]["clock"]["driver_reported_mhz"] for arm in row["order"]]
                    if frequencies[0] != frequencies[1]:
                        row.update(status="CLOCK_MISMATCH", error="driver-reported clock sets differ")
                    else:
                        row.update(status="MEASURED", speedup=row["arms"]["gr"]["timing"]["setup_inclusive_ns"] /
                                   row["arms"]["spine"]["timing"]["setup_inclusive_ns"])
                else:
                    row["status"] = "FAILED_RETAINED"
                analysis.write_table(report, args.output / "fig8_fpga.csv")
                save(journal, report)
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events"] = (group / "memory.events").read_text()
    report["status"] = "COMPLETED" if all(row["status"] == "MEASURED" for row in report["cases"]) else "COMPLETED_WITH_FAILURES"
    save(journal, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "hardware", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--device", type=int, choices=(0, 1), default=1)
    parser.add_argument("--bdf", default="0000:c1:00.1")
    parser.add_argument("--metadata-replicas", type=int, choices=(1, 4), default=4)
    parser.add_argument("--memory-gib", type=int, choices=(16, 24, 32), default=24)
    parser.add_argument("--memory-profile", choices=memory_policy.PROFILES, default=memory_policy.ARC_BACKGROUND)
    parser.add_argument("--wait-seconds", type=int, default=1800)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    arguments = parser.parse_args()
    if (arguments.device, arguments.bdf) not in ((0, "0000:82:00.1"), (1, "0000:c1:00.1")):
        parser.error("device and BDF disagree")
    run(arguments)
