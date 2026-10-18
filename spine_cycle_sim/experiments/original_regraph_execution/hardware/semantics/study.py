"""Audit all frozen original-R inputs before defining the adapter/K4 control."""

import argparse
import json
from pathlib import Path
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import containment
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from .. import artifact, oracle, study
from . import arithmetic, sources

STATUS = "ORIGINAL_R_K4_ARITHMETIC_AUDIT_COMPLETE_NOT_HARDWARE_OR_PERFORMANCE_MATCH"
CLAIMS = ("board_programmed", "hardware_timing_measured", "publication_match",
          "adapter_performance_measured", "production_default_semantics_equal")
PROFILE = {"iterations": 1, "original_arg": 0,
           "original_formula": "floor(floor(108*S/128)*floor(65536/d)/65536)",
           "candidate_formula": "binary32(binary32((108/128)*binary32(S))/binary32(d))",
           "candidate_mode": "FullPR", "candidate_base": 0, "candidate_dangling_share": 0,
           "candidate_damping": 108 / 128,
           "candidate_output": "source_payload_not_rank_state",
           "candidate_input": "numeric_binary32_integer_contributions_not_integer_bit_patterns",
           "production_defaults": "damping_0.85_base_and_dangling_are_not_this_control"}


def validate_reference(reference, document):
    study.validate_matrix(document)
    if (reference.get("status") != study.STATUS or reference.get("errors") != [] or
            len(reference.get("cases", [])) != len(study.EXPECTED) or
            {row["id"] for row in reference["cases"]} != study.EXPECTED):
        raise ValueError("complete passing original-R six-input audit required")


def clean_memory_events(group):
    observed = (group / "memory.events").read_text()
    events = dict(line.split() for line in observed.splitlines())
    if any(events.get(key) != "0" for key in ("max", "oom", "oom_kill", "oom_group_kill")):
        raise ValueError("arithmetic audit memory-limit/OOM events missing or nonzero")
    return observed


def run(inputs, audit, original, production, output):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "profile": PROFILE, "cases": [], "errors": [],
              **dict.fromkeys(CLAIMS, False)}
    group, started = None, time.monotonic()
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        group = containment.current()
        report["containment"] = containment.verify(group, memory_gib=2)
        if available_memory_bytes() < 34 * 1024**3:
            raise ValueError("2-GiB study plus 32-GiB available-memory reserve required")
        reference, document = (json.loads(path.read_text()) for path in (audit / "results.json", inputs))
        validate_reference(reference, document)
        source_review = sources.review(original, production)
        original_pin = next(item for item in reference["source_review"]["identities"]
                            if item["path"].endswith("/acc_udfs/pr/l2.h"))
        if original_pin != source_review["pins"][0]:
            raise ValueError("author UDF differs from the independently audited source")
        runner = [Path(module.__file__) for name, module in list(sys.modules.items())
                  if name.startswith("spine_cycle_sim.") and getattr(module, "__file__", None)]
        pins = [artifact.identity(path) for path in (inputs, audit / "results.json", *runner)]
        report.update(source_review=source_review, pins=[*pins, *source_review["pins"]])
        save()
        for case in document["cases"]:
            first, second = case["runs"]
            directory = Path(first["directory"])
            layout_path = directory / "layout.json"
            layout = json.loads(layout_path.read_text())
            if (case["repeat_all_captures_identical"] is not True or first["analysis"] != second["analysis"] or
                    layout != first["analysis"] or artifact.identity(layout_path)["sha256"] != first["layout_sha256"]):
                raise ValueError("unchanged repeated frozen layout required")
            checked = oracle.audit(directory, layout)
            capture_pins = checked.pop("pins")
            admitted = next(row for row in reference["cases"] if row["id"] == case["id"])
            if {"id": case["id"], **checked} != admitted:
                raise ValueError("CSR/task audit differs from the independent preflight")
            report["pins"] += [artifact.identity(layout_path), *capture_pins]
            vertices, aligned = (layout["summary"][key] for key in ("vertices", "aligned_vertices"))
            read = lambda name, count: oracle.read_words(directory / name, count)
            initial, degrees = read("initial.u32le", aligned), read("degrees.u32le", aligned)
            sums = arithmetic.csr_sums(read("csr_offsets.u32le", vertices + 1),
                read("csr_destinations.u32le", layout["summary"]["logical_edges"]), initial, vertices)
            bindings = {name: arithmetic.compare(sums, values, vertices)
                        for name, values in (("author_initial", initial), ("csr_degree", degrees))}
            for binding, key in (("author_initial", "original_host_result_sha256"),
                                 ("csr_degree", "csr_degree_result_sha256")):
                if bindings[binding]["fixed_aligned_sha256"] != checked["one_superstep_comparison"][key]:
                    raise ValueError("fresh fixed-point oracle digest differs")
            report["cases"].append({"id": case["id"], "logical_edges": layout["summary"]["logical_edges"],
                                    "bindings": bindings})
            save()
            print("Arithmetic-audited " + case["id"] + "; no FPGA or performance claim", flush=True)
        for graph in ("boundary_ring", "skewed_sources", "amazon"):
            selected = [row for row in report["cases"] if row["id"] in ("a4_" + graph, "original_example_" + graph)]
            if len(selected) != 2 or selected[0]["bindings"] != selected[1]["bindings"]:
                raise ValueError("A4 and 11+3 arithmetic controls differ on the same logical graph")
        unchanged(report["pins"])
        if sources.review(original, production) != source_review:
            raise ValueError("arithmetic source profile changed during audit")
        report["memory_events_after"] = clean_memory_events(group)
        report["status"] = STATUS
    except BaseException as error:
        report.update(status="FAILED_RETAINED", errors=[repr(error)])
        raise
    finally:
        if group is not None:
            report["memory_events_after"] = (group / "memory.events").read_text()
        report["wall_seconds"] = time.monotonic() - started
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "audit", "original", "production", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(run(*(path.resolve() for path in vars(args).values()))["status"], flush=True)
