"""Consume exact prior controls; never repair or deduplicate captured graphs."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from .. import artifact, control_analysis
from ..semantics import sources, study as semantics

GRAPHS = ("boundary_ring", "skewed_sources", "amazon")
FILES = ("execution.u32le", "tasks.u32le", "initial.u32le", "degrees.u32le",
         "csr_offsets.u32le", "csr_destinations.u32le")


def admit(validation, arithmetic, original, production):
    control_path, arithmetic_path = validation / "results.json", arithmetic / "results.json"
    control, audit = (json.loads(path.read_text()) for path in (control_path, arithmetic_path))
    if (control.get("status") != control_analysis.STATUS or control.get("errors") != [] or
            any(control.get(key) is not False for key in
                ("board_programmed", "hardware_timing_measured", "publication_match"))):
        raise ValueError("passing complete offline original-R control required")
    control_analysis.matrix(control["rows"])
    expected = {topology + "_" + graph for topology in ("a4", "original_example") for graph in GRAPHS}
    if (audit.get("status") != semantics.STATUS or audit.get("errors") != [] or
            audit.get("profile") != semantics.PROFILE or
            len(audit.get("cases", [])) != 6 or
            {row["id"] for row in audit["cases"]} != expected or
            any(audit.get(key) is not False for key in semantics.CLAIMS)):
        raise ValueError("complete exact-profile six-input arithmetic audit required")
    review = sources.review(original, production)
    if review != audit["source_review"]:
        raise ValueError("production/original arithmetic sources differ from audit")
    pins = [*control["pins"], *audit["pins"], artifact.identity(control_path),
            artifact.identity(arithmetic_path), *review["pins"]]
    unchanged(pins)
    admitted = control["inputs"]["a4"]
    if len(admitted) != 3 or {item["id"] for item in admitted} != set(GRAPHS):
        raise ValueError("all three predeclared A4 graphs required")
    ordered = []
    for graph in GRAPHS:
        item = next(item for item in admitted if item["id"] == graph)
        directory = Path(item["directory"])
        unchanged(item["pins"])
        for name in FILES:
            pin = artifact.identity(directory / name)
            if pin not in item["pins"] or pin not in pins:
                raise ValueError("A4 input is not pinned by its full prior control")
        comparisons = [next(row for row in audit["cases"] if row["id"] == topology + "_" + graph)
                       for topology in ("a4", "original_example")]
        if comparisons[0]["bindings"] != comparisons[1]["bindings"]:
            raise ValueError("original A4 and 11+3 arithmetic controls differ")
        ordered.append({"id": graph, "directory": str(directory),
                        "arithmetic": comparisons[0]["bindings"]})
    return {"inputs": ordered, "pins": pins, "source_review": review}
