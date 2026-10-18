"""Freeze every prepared K4 case before a separately qualified board launch."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import inputs as source_inputs
from .. import artifact
from ..board_execution.preparation import REPEATS, POLICY, runner_pins, unique
from ..source_build.snapshot import unchanged
from . import analysis, board_analysis, study
from .inputs import GRAPHS

BOUNDARY = "one static binary32 FullPR superstep; resident argument binding/enqueue to completion"
CLAIMS = (*board_analysis.FALSE_CLAIMS, "source_revision_equivalence_claim", "latest_revision_performance_claim")
HEADERS = ("include/weighted_pma_graph.hpp", "include/weighted_pma_runtime_plan.hpp",
           "include/regraph_pagerank/l2.h")


def validate(plan):
    expected = {(graph, binding) for graph in GRAPHS for binding in analysis.BINDINGS}
    cases = plan.get("cases", [])
    if (plan.get("boundary") != BOUNDARY or type(plan.get("repeats")) is not int or
            plan["repeats"] != REPEATS or plan.get("policy") != POLICY or len(cases) != 6 or
            {(case["graph"], case["binding"]) for case in cases} != expected or
            any(plan.get(key) is not False for key in CLAIMS)):
        raise ValueError("all six K4 cases, three repeats and explicit limited claims required")
    for case in cases:
        reference = case["reference"]
        unsupported = reference["duplicates"] > 0
        if case.get("status") != (analysis.UNSUPPORTED if unsupported else board_analysis.PREPARED):
            raise ValueError("K4 eligibility differs from unchanged CSR")
        if not unsupported:
            offline = case["offline"]
            if any(type(offline.get(key)) is not type(value) or offline[key] != value
                   for key, value in analysis.profile(reference, case["binding"]).items()):
                raise ValueError("K4 board profile differs from independent preparation")


def source_contract(preflight, sources):
    manifest = source_inputs.verify(sources)
    indexed = {row["member"]: row for row in manifest["files"]}
    pinned = {row["path"]: row for row in preflight["pins"]}
    pins = [artifact.identity(sources / row["member"]) for row in manifest["files"]]
    headers = []
    for name in HEADERS:
        row = indexed["source/integration/" + name]
        original = row["original"]["path"]
        if original not in pinned or pinned[original]["sha256"] != row["sha256"]:
            raise ValueError("routed and prepared production headers differ: " + name)
        pin = artifact.identity(sources / row["member"])
        headers.append({"member": name, "sha256": pin["sha256"]})
    apply_member = "source/integration/kernels/regraph_pagerank_apply/regraph_pagerank_apply.cpp"
    apply = indexed[apply_member]
    prepared_apply = next(row for row in preflight["source_review"]["pins"]
                         if row["path"] == apply["original"]["path"])
    return {"routed_revision": manifest["integration_revision"],
            "prepared_revision": preflight["source_review"]["production_revision"],
            "headers": headers, "routed_apply_sha256": apply["sha256"],
            "prepared_apply_sha256": prepared_apply["sha256"],
            "apply_source_identical": apply["sha256"] == prepared_apply["sha256"],
            "scope": "shared_header_identity_only; every FPGA output must independently pass",
            "source_revision_equivalence_claim": False, "latest_revision_performance_claim": False}, pins


def prepare(preflight, sources):
    path = preflight / "results.json"
    report = json.loads(path.read_text())
    if (report.get("status") != study.HOST_STATUS or report.get("errors") != [] or
            report.get("board_host_preflight") is not True or
            report.get("negative_controls") != ["unknown_binding"] or
            report.get("summary") != {"predeclared_rows": 24, "passing_offline_rows": 16, "unsupported_rows": 8} or
            any(report.get(key) is not False for key in study.CLAIMS)):
        raise ValueError("complete 24-row K4 board-host preflight required, not an offline timing result")
    board_analysis.matrix(report["rows"])
    owner_pins = [artifact.identity(path) for path in sorted(Path(__file__).parent.glob("*.py"))]
    pins = unique([artifact.identity(path), *report["pins"], *runner_pins(), *owner_pins,
                   artifact.identity(sources / "sources.json")])
    unchanged(pins)
    items = report["inputs"]
    if len(items) != 3 or {item["id"] for item in items} != set(GRAPHS):
        raise ValueError("all three original A4 inputs required")
    references = {item["id"]: analysis.prepare(item) for item in items}
    if references != report["eligibility"]:
        raise ValueError("fresh CSR eligibility differs from prepared matrix")
    for row in report["rows"]:
        reference = references[row["graph"]]
        if reference["duplicates"]:
            if (row["status"] != analysis.UNSUPPORTED or row["duplicates"] != reference["duplicates"] or
                    row["first_duplicate"] != reference["first_duplicate"] or Path(row["directory"]).exists()):
                raise ValueError("unsupported input must retain exact duplicate reason without output")
            continue
        directory = Path(row["directory"])
        observed = json.loads((directory / "result.json").read_text())
        checked = board_analysis.prepared(observed, directory, reference, row["binding"])
        if observed != row["observation"] or checked != row["analysis"]:
            raise ValueError("prepared targets or raw observation differ")
        pins += checked["pins"]
    contract, source_pins = source_contract(report, sources)
    binary = artifact.identity(preflight / "bin/release")
    if binary not in report["pins"]:
        raise ValueError("board host was not pinned by complete preflight")
    cases = []
    for graph in GRAPHS:
        item = next(item for item in items if item["id"] == graph)
        for binding in analysis.BINDINGS:
            row = next(row for row in report["rows"] if row["graph"] == graph and
                       row["binding"] == binding and row["build"] == "release" and row["repetition"] == 0)
            case = {"graph": graph, "binding": binding, "input": item["directory"],
                    "reference": references[graph], "status": row["status"]}
            if row["status"] == board_analysis.PREPARED:
                case.update(offline=row["observation"], expected=row["analysis"])
            cases.append(case)
    plan = {"boundary": BOUNDARY, "repeats": REPEATS, "policy": POLICY, "cases": cases,
            "host": binary, "source_contract": contract, "pins": unique([*pins, *source_pins]),
            **dict.fromkeys(CLAIMS, False)}
    validate(plan)
    unchanged(plan["pins"])
    return plan
