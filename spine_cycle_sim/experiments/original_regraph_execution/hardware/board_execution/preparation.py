"""Freeze the complete offline host and its predeclared eighteen board controls."""

import json
from pathlib import Path
import sys

from .. import artifact, control_analysis, control_delivery, study
from ..source_build import snapshot

GRAPHS = ("boundary_ring", "skewed_sources", "amazon")
REPEATS = 3
POLICY = {"tree_memory_gib": 8, "reserve_gib": 24, "background_memory_gib": 8,
          "allow_bounded_builds": True}
BOUNDARY = "one static signed fixed-point PR superstep, arg=0; resident argument binding/enqueue to completion"


def validate_plan(plan):
    expected = {(graph, binding) for graph in GRAPHS for binding in control_analysis.BINDINGS}
    if (plan.get("boundary") != BOUNDARY or type(plan.get("repeats")) is not int or
            plan["repeats"] != REPEATS or plan.get("policy") != POLICY or
            any(plan.get(key) is not False for key in
                ("publication_match", "convergence_measured", "host_inclusive_measured")) or
            len(plan.get("cases", [])) != len(expected) or
            {(case["graph"], case["binding"]) for case in plan["cases"]} != expected):
        raise ValueError("exact six controls and three repeats at the declared boundary required")
    for case in plan["cases"]:
        offline = case["offline"]
        if (offline.get("little") != 11 or offline.get("big") != 3 or
                offline.get("topology") != "original_example" or offline.get("binding") != case["binding"]):
            raise ValueError("reviewed 11+3 ABI and explicit divisor binding required")


def unique(pins):
    indexed = {}
    for pin in pins:
        if pin["path"] in indexed and indexed[pin["path"]] != pin:
            raise ValueError("conflicting frozen identity")
        indexed[pin["path"]] = pin
    return [indexed[key] for key in sorted(indexed)]


def runner_pins():
    paths = {Path(module.__file__).resolve() for name, module in list(sys.modules.items())
             if name.startswith("spine_cycle_sim.") and (getattr(module, "__file__", "") or "").endswith(".py")}
    paths.update(Path(__file__).parent.glob("*.py"))
    return [artifact.identity(path) for path in sorted(paths)]


def prepare(audit, control, route):
    reference = json.loads((audit / "results.json").read_text())
    validated = json.loads((control / "results.json").read_text())
    if reference["status"] != study.STATUS or reference["errors"]:
        raise ValueError("passing independent original-R audit required")
    control_delivery.terminal(validated)
    audit_pin = artifact.identity(audit / "results.json")
    if audit_pin not in validated["pins"]:
        raise ValueError("guarded host belongs to a different independent audit")
    binary = artifact.identity(control / "bin/release_control")
    if binary not in validated["pins"]:
        raise ValueError("Release host binary was not offline validated")
    route_manifest = route / "manifest.json"
    build = json.loads(route_manifest.read_text())
    pins = unique([audit_pin, artifact.identity(control / "results.json"), artifact.identity(route_manifest),
                   binary, *reference["pins"], *validated["pins"], *build["pins"], *runner_pins()])
    snapshot.unchanged(pins)
    inputs = validated["inputs"]["original_example"]
    if len(inputs) != len(GRAPHS) or {item["id"] for item in inputs} != set(GRAPHS):
        raise ValueError("complete original 11+3 input set required; A4 is a separate board ABI")
    cases = []
    for graph in GRAPHS:
        item = next(item for item in inputs if item["id"] == graph)
        oracle = next(row for row in reference["cases"] if row["id"] == "original_example_" + graph)
        for binding in control_analysis.BINDINGS:
            admitted = next(row for row in validated["rows"] if row["build"] == "release" and
                row["repetition"] == 0 and row["topology"] == "original_example" and
                row["graph"] == graph and row["binding"] == binding)
            directory = Path(admitted["directory"])
            observed = json.loads((directory / "result.json").read_text())
            if observed != admitted["observation"] or \
                    control_analysis.inspect(observed, directory, oracle) != admitted["analysis"]:
                raise ValueError("offline control no longer matches its raw independent oracle")
            if observed["little"] != 11 or observed["big"] != 3 or observed["topology"] != "original_example":
                raise ValueError("only reviewed 11+3 board ABI is admitted")
            pins += [artifact.identity(directory / name) for name in ("result.json", "expected.u32le")]
            cases.append({"graph": graph, "binding": binding, "input": item["directory"],
                          "offline": observed, "reference": oracle, "expected": admitted["analysis"]})
    plan = {"boundary": BOUNDARY, "cases": cases, "repeats": REPEATS, "host": binary,
            "pins": unique(pins), "policy": POLICY, "publication_match": False,
            "convergence_measured": False, "host_inclusive_measured": False}
    validate_plan(plan)
    return plan
