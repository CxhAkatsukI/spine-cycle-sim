"""Run frozen affected-fraction points with existing resident FPGA hosts."""

import argparse
import importlib.util
import json
from pathlib import Path
import statistics

from ...original_regraph_execution.hardware.board_execution import memory_policy, pair_resources
from ...original_regraph_execution.hardware.source_retention import active_min_resident, clocks
from ...original_regraph_execution.hardware.source_retention.follow import unchanged
from ...original_regraph_execution.hardware.source_retention.runtime import check_memory, identity, save
from . import hardware


def load_comparator(path):
    spec = importlib.util.spec_from_file_location("resident_comparison", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counters(text):
    records = {}
    for line in text.splitlines():
        fields = dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)
        records.setdefault(line.split()[0] if line.split() else "", []).append(fields)
    rounds = records.get("KERNEL_PAIR_RESULT", [])
    return dict(processed_edges=sum(int(row["processed_edges"]) for row in rounds)
                if rounds and all("processed_edges" in row for row in rounds) else None,
                source_requests=sum(int(row["source_requests"]) for row in rounds)
                if rounds and all("source_requests" in row for row in rounds) else None,
                timing_records={key: value for key, value in records.items()
                                if "TIMING" in key or "WALL" in key})


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(status="PREPARING", workloads=identity(args.workloads),
                  template=identity(args.template), comparator=identity(args.comparator),
                  runner=identity(__file__), memory_gib=args.memory_gib,
                  memory_profile=args.memory_profile, bdf=args.bdf, device=args.device,
                  warmup_pairs=1, measured_pairs=args.repetitions, cases=[])
    journal = args.output / "campaign.json"
    save(journal, report)
    workloads = json.loads(args.workloads.read_text())
    template = json.loads(args.template.read_text())
    binding = template["hardware"][workloads["algorithm"]]
    comparator = load_comparator(args.comparator)
    pins = [report[key] for key in ("workloads", "template", "comparator", "runner")]
    pins += [binding[key] for key in ("spine_host", "spine_image", "gr_host", "gr_image")]
    pins += [identity(hardware.__file__), identity(memory_policy.__file__)]
    report["artifacts"] = pins
    report["hardware_limitation"] = binding["limitation"]
    expected = {name: clocks.image(binding[name + "_image"]["path"], args.output, name)
                for name in ("spine", "gr")}

    def admission(status, observation):
        report.update(status=status, admission=observation)
        save(journal, report)

    try:
        with memory_policy.scope(args.memory_profile):
            group = check_memory(args.memory_gib, require_live_reserve=False)
            with pair_resources.admit(args.device, args.bdf, group, args.wait_seconds, admission,
                                      memory_gib=args.memory_gib):
                for point in workloads["points"]:
                    if args.point and point["name"] not in args.point:
                        continue
                    unchanged([*pins, point["graph"]])
                    row = dict(point, status="RUNNING", samples=[])
                    report["cases"].append(row)
                    report["status"] = "RUNNING"
                    save(journal, report)
                    for sample in range(args.repetitions + 1):
                        output = args.output / point["name"] / f"sample-{sample}"
                        output.mkdir(parents=True, exist_ok=False)
                        commands, prepared = hardware.commands(binding, workloads, point, output)
                        order = ("spine", "gr") if sample % 2 == 0 else ("gr", "spine")
                        result = dict(sample_index=sample, warmup=sample == 0, order=order, arms={},
                                      split_inputs=prepared)
                        row["samples"].append(result)
                        save(journal, report)
                        try:
                            for name in order:
                                command = ["/usr/bin/taskset", "-c", "124,125", *commands[name]]
                                result["arms"][name] = active_min_resident.arm(
                                    name, command, expected[name], output, bdf=args.bdf,
                                    device=args.device, timeout_seconds=args.timeout_seconds,
                                    cc_wall=workloads["algorithm"] == "connected_components")
                                save(journal, report)
                            texts = {name: Path(arm["stdout"]["path"]).read_text()
                                     for name, arm in result["arms"].items()}
                            pair = hardware.compare(comparator, workloads, point, texts, args.bdf)
                            frequencies = [result["arms"][name]["clock"]["driver_reported_mhz"] for name in order]
                            if frequencies[0] != frequencies[1]:
                                raise ValueError("FPGA arms used different clocks")
                            result.update(status="PASS", pair=pair,
                                          counters={name: counters(text) for name, text in texts.items()})
                            save(output / "sample.json", result)
                        except Exception as error:
                            result.update(status="FAILED_RETAINED", error=repr(error))
                            row["status"] = "FAILED_RETAINED"
                            save(journal, report)
                            if not args.continue_on_case_error:
                                raise
                            break
                        save(journal, report)
                    if row["status"] == "FAILED_RETAINED":
                        continue
                    measured = [sample["pair"] for sample in row["samples"] if not sample["warmup"]]
                    medians = {name: statistics.median(pair[name + "_wall_ms"] for pair in measured)
                               for name in ("gr", "spine")}
                    row.update(status="MEASURED", medians_ms=medians,
                               speedup=medians["gr"] / medians["spine"])
                    save(journal, report)
                    print(point["name"], point["changed_fraction"], row["speedup"], flush=True)
        if not report["cases"]:
            raise ValueError("no requested workloads were selected")
        report["status"] = ("COMPLETED_WITH_FAILURES" if any(
            row["status"] == "FAILED_RETAINED" for row in report["cases"]) else "COMPLETED")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(journal, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workloads", "template", "comparator", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--point", action="append")
    parser.add_argument("--continue-on-case-error", action="store_true",
                        help="retain a failed point and attempt the remaining frozen inputs")
    parser.add_argument("--repetitions", type=int, choices=(1, 3), default=3)
    parser.add_argument("--memory-gib", type=int, choices=(8, 16, 24, 32), default=8)
    parser.add_argument("--memory-profile", choices=memory_policy.PROFILES, default=memory_policy.ARC_BACKGROUND)
    parser.add_argument("--wait-seconds", type=int, default=1800)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--device", type=int, choices=(0, 1), default=0)
    parser.add_argument("--bdf", choices=("0000:82:00.1", "0000:c1:00.1"), default="0000:82:00.1")
    args = parser.parse_args()
    if (args.device, args.bdf) not in ((0, "0000:82:00.1"), (1, "0000:c1:00.1")):
        parser.error("device and PCI address disagree")
    run(args)


if __name__ == "__main__":
    main()
