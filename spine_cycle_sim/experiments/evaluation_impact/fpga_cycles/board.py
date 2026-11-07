"""Reuse the production host and board lease; save all device-event results."""

import argparse
import json
from pathlib import Path

from ...original_regraph_execution.hardware.board_execution import memory_policy, pair_resources
from ...original_regraph_execution.hardware.source_retention import clocks
from ...original_regraph_execution.hardware.source_retention.runtime import check_memory, execute, identity, save


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    plan = json.loads(args.inputs.read_text())
    hardware = json.loads(args.hardware.read_text())
    if args.host:
        hardware["spine_host"] = str(args.host.resolve())
    report = dict(status="RUNNING", plan=identity(args.inputs), hardware=hardware, rows=[],
                  repetitions=1, boundary="maintenance kernel event plus sum of reader/compute event spans; no DMA or host gaps")
    report.update(board_index=args.board_index, bdf=args.bdf,
                  host_identity=identity(Path(hardware["spine_host"])),
                  image_identity=identity(Path(hardware["spine_image"])))
    journal = args.output / "results.json"
    save(journal, report)
    expected = clocks.image(hardware["spine_image"], args.output, "spine")
    def admission(status, observation):
        report.update(status=status, admission=observation)
        save(journal, report)
    with memory_policy.scope(memory_policy.ARC_BACKGROUND):
        group = check_memory(16, require_live_reserve=False)
        with pair_resources.admit(args.board_index, args.bdf, group, 600, admission, memory_gib=16) as (node, fd):
            for case in plan["cases"]:
                if case["split"] != args.split:
                    continue
                output = args.output / case["name"]
                output.mkdir()
                row = dict(case, status="RUNNING")
                report["rows"].append(row)
                save(journal, report)
                command = ["/usr/bin/env", "-u", "XCL_EMULATION_MODE", f"XCL_DEVICE_INDEX={args.board_index}",
                           f"SPINE_EXPECT_BDF={args.bdf}", "LD_LIBRARY_PATH=/opt/xilinx/xrt/lib:/usr/lib/x86_64-linux-gnu",
                           hardware["spine_host"], hardware["spine_image"],
                           "--dynamic-graph", case["graph"], "--source", "0"]
                try:
                    result = execute(command, output, "spine", fd, node, args.bdf, memory_gib=16, timeout=240)
                    log = Path(result["stdout"]["path"]).read_text()
                    lines = [line for line in log.splitlines() if line.startswith("SPINE_HW_TIMING ")]
                    if len(lines) != 1 or "PARTITIONED_ALGORITHM_PASS algorithm=weighted_sssp" not in log:
                        raise ValueError("missing complete oracle or unique event summary")
                    timing = dict(item.split("=", 1) for item in lines[0].split()[1:])
                    evidence = clocks.capture(args.bdf, expected, output, "spine")
                    row.update(result, status="MEASURED", timing=timing,
                               clock_evidence=evidence, clock=clocks.replay(evidence))
                except Exception as error:
                    row.update(status="FAILED_RETAINED", error=repr(error))
                save(journal, report)
                print(case["name"], row["status"], row.get("timing", row.get("error")), flush=True)
    report["status"] = "COMPLETE" if all(row["status"] == "MEASURED" for row in report["rows"]) else "PARTIAL_RETAINED"
    save(journal, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("inputs", "hardware", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--split", choices=("development", "holdout"), required=True)
    parser.add_argument("--host", type=Path)
    parser.add_argument("--board-index", type=int, default=1)
    parser.add_argument("--bdf", default="0000:c1:00.1")
    run(parser.parse_args())
