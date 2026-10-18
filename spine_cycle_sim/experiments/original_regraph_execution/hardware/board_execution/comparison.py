"""Compare independently replayed 11+3 and A4 board controls, not paper speed."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .. import artifact
from ..source_build.snapshot import unchanged
from . import delivery, preparation

STATUS = "ORIGINAL_R_A4_MEASURED_CONTROL_COMPARISON_NOT_K4_OR_PUBLICATION_MATCH"
INPUTS = ("csr_offsets.u32le", "csr_destinations.u32le", "initial.u32le", "degrees.u32le")
METRICS = ("enqueue_to_completion_ms", "event_span_ns", "event_union_ns")
CLAIMS = ("publication_match", "same_resource_claim", "convergence_measured",
          "host_inclusive_measured", "latest_k4_performance_measured", "spine_speedup_measured")


def runtime_identity(board):
    runtime = board["runtime"]
    # Runner files differ between frozen worktrees; the device and loaded
    # libraries must not. Absolute library paths are part of this local control.
    pins = {pin["path"]: pin["sha256"] for pin in runtime["pins"]
            if "/spine_cycle_sim/" not in pin["path"]}
    if not pins:
        raise ValueError("runtime tool/library identities required")
    return {"device": runtime["device"], "platform": runtime["platform"]["static_region"],
            "libraries_and_tools": pins}


def load(attempt, topology):
    supervisor, board = delivery.recheck(attempt)
    plan = json.loads((attempt / "manifest.json").read_text())
    if plan["configuration"] != topology or board["configuration"] != topology:
        raise ValueError("distinct original 11+3 and A4 controls required")
    pins = preparation.unique([*supervisor["pins"], *board["pins"]])
    cases = {}
    for case in plan["cases"]:
        identities = {name: artifact.identity(Path(case["input"]) / name) for name in INPUTS}
        if any(pin not in pins for pin in identities.values()):
            raise ValueError("logical input/state is not frozen by the board control")
        cases[(case["graph"], case["binding"])] = {
            "vertices": case["reference"]["vertices"], "logical_edges": case["reference"]["logical_edges"],
            "inputs": {name: pin["sha256"] for name, pin in identities.items()}}
    affinity = {tuple(item["command"][:3]) for item in board["attempts"]}
    if len(affinity) != 1 or next(iter(affinity))[:2] != ("/usr/bin/taskset", "-c"):
        raise ValueError("one explicit CPU affinity required for each complete matrix")
    clocks = {row["analysis"]["clock_mhz"] for row in board["rows"]}
    if clocks != {150}:
        raise ValueError("independently admitted 150-MHz board controls required")
    return {"board": board, "cases": cases, "runtime": runtime_identity(board),
            "affinity": next(iter(affinity)), "host": plan["host"], "pins": pins,
            "reports": [artifact.identity(attempt / name) for name in
                        ("results.json", "manifest.json", "board/results.json", "worker.resources.json")]}


def compare(original, a4):
    for name in ("runtime", "affinity", "host", "cases"):
        if original[name] != a4[name]:
            raise ValueError("11+3 and A4 differ in matched " + name)
    indexed = [{(row["graph"], row["binding"]): row for row in item["board"]["summaries"]}
               for item in (original, a4)]
    if any(set(rows) != set(original["cases"]) for rows in indexed):
        raise ValueError("every predeclared case must remain in the comparison")
    rows = []
    for key, case in original["cases"].items():
        selected = [item[key] for item in indexed]
        if any(item["repeats"] != preparation.REPEATS for item in selected):
            raise ValueError("three independently replayed repeats required")
        logical_outputs = [{row["analysis"]["independent_oracle"]["logical_sha256"]
                            for row in item["board"]["rows"]
                            if (row["graph"], row["binding"]) == key} for item in (original, a4)]
        if len(logical_outputs[0]) != 1 or logical_outputs[0] != logical_outputs[1]:
            raise ValueError("logical fixed-point results differ between topologies")
        rows.append({"graph": key[0], "binding": key[1], **case,
            "logical_output_sha256": next(iter(logical_outputs[0])),
            "original_11l3b": selected[0], "a4": selected[1],
            "a4_over_original_ratio_of_medians": {
                metric: selected[1][metric]["median"] / selected[0][metric]["median"] for metric in METRICS}})
    return {"status": STATUS, "errors": [], "boundary": preparation.BOUNDARY,
            "clock_mhz": 150, "repeats_per_case": preparation.REPEATS, "rows": rows,
            "runtime": original["runtime"], "affinity": list(original["affinity"]), "host": original["host"],
            "ratio_definition": "A4 median time / original 11+3 median time; lower is faster",
            "latest_adapter_k4": {"status": "NOT_INCLUDED_NO_MATCHED_BOARD_RESULT"},
            "raw_outputs_independently_replayed": True, "hardware_timing_measured": True,
            **dict.fromkeys(CLAIMS, False),
            "pins": preparation.unique([*original["pins"], *a4["pins"],
                                         *original["reports"], *a4["reports"], artifact.identity(Path(__file__))])}


def markdown(report):
    lines = ["# Original ReGraph And A4: Measured Control", "", report["status"], "",
        "One static fixed-point PR superstep, resident inputs, 150 MHz, three repeats.",
        "Times are medians. Ratios are A4 / original 11+3; lower means A4 is faster.", "",
        "| Graph | Divisor binding | 11+3 wall ms | A4 wall ms | Wall ratio | 11+3 event span ms | A4 event span ms | Span ratio |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["rows"]:
        old, new, ratios = (row[name] for name in ("original_11l3b", "a4", "a4_over_original_ratio_of_medians"))
        lines.append(f"| {row['graph']} | {row['binding']} | {old['enqueue_to_completion_ms']['median']:.6f} | "
            f"{new['enqueue_to_completion_ms']['median']:.6f} | {ratios['enqueue_to_completion_ms']:.3f} | "
            f"{old['event_span_ns']['median'] / 1e6:.6f} | {new['event_span_ns']['median'] / 1e6:.6f} | "
            f"{ratios['event_span_ns']:.3f} |")
    lines += ["", "## Interpretation", "",
        "The resident wall window includes argument binding, enqueue and queue completion; "
        "the event span starts at the first device event and ends at the last. They are "
        "different measured windows, not interchangeable cycle counts. Overlapping events are not added.", "",
        "Input CSR, state, divisors, logical outputs, Release host, CPU affinity, board, "
        "driver and runtime libraries match. Both topologies independently passed full "
        "replica/guard/oracle and strict routed-clock/timing checks. The original topology's "
        "larger publication extent and distinct task schedule remain part of that topology.", "",
        "A4 uses the author's nine-bank layout. This is not an equal-resource comparison "
        "to K4/23 channels, a publication-speed reproduction, convergence, host-inclusive "
        "dynamic latency or a Spine comparison. Latest adapter+K4 hardware is not included; "
        "its performance cannot be inferred from these numbers.", ""]
    return "\n".join(lines)


def run(original, a4, output):
    report = compare(load(original, "original_example"), load(a4, "a4"))
    unchanged(report["pins"])
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "results.json", report)
    (output / "README.md").write_text(markdown(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "a4", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(run(*(getattr(args, name).resolve() for name in ("original", "a4", "output")))["status"], flush=True)
