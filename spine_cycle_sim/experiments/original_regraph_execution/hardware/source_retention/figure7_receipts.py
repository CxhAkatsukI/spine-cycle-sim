"""Export a Figure 7 evidence snapshot from the single-pass FPGA journals."""

import argparse
import csv
import json
import math
from pathlib import Path

from . import active_min_admission, active_min_resident, cc_resident_wall, clocks, resident_matrix, spine_cc_warm_receipt
from .runtime import identity, save


DATASETS = active_min_resident.DATASETS
MEASURED = resident_matrix.MEASURED
ALGORITHMS = ("weighted_sssp", "cc", "respr")
BOUNDARIES = {key: (cc_resident_wall.BOUNDARY if key == "cc" else active_min_resident.BOUNDARY)
              for key in ALGORITHMS}
SPECIAL = {"weighted_sssp": "AU", "cc": "R19", "respr": "R19"}
JOURNALS = {"weighted_sssp": ("sssp_matrix", "sssp_au"),
            "cc": ("cc_matrix", "cc_r19"), "respr": ("respr_matrix", "respr_screen")}
ROLES = tuple(role for roles in JOURNALS.values() for role in roles)
OPTIONAL_SCREENS = {"sssp_au", "cc_r19"}
TERMINAL_BLOCKERS = {"NOT_ADMITTED", "FAILED_RETAINED", "PAIRED_SCREEN_NEEDS_REVIEW"}
PENDING_ROWS = {"NOT_RECORDED", "NOT_REQUESTED", "PREDECLARED", "WAITING_FOR_MATCHED_MATRIX_ADMISSION"}
CSV_FIELDS = ("algorithm", "dataset", "status", "r_validation_scope", "boundary", "graph_sha256", "vertices", "edges",
              "updates", "source", "spine_ms", "gr_ms", "gr_over_spine", "winner", "gr_rounds",
              "spine_rounds", "respr_propagated_on_both", "same_driver_clocks", "comparison_sha256",
              "blocked_by", "error")


def checked(pin):
    path = Path(pin["path"])
    if identity(path) != pin:
        raise ValueError(f"receipt or raw log changed: {path}")
    return path


def load(pin):
    return json.loads(checked(pin).read_text())


def ratio(gate, key):
    value = gate[key]
    if (gate["retention_gate_pass"] is not True or type(value) not in (float, int)
            or not 0 < value <= 1.15):
        raise ValueError("independent G or R retention gate is not a 15% pass")
    return value


def summarize_gates(algorithm, gates, extra):
    if algorithm == "respr":
        r = gates["r_controls"]
        if set(r) != {"amazon", "skewed_sources"}:
            raise ValueError("both independent ResPR R controls are required")
        return {"g_ratio": ratio(gates["g_control"], "current_over_reference"),
                "r_ratios": {key: ratio(row, "current_over_reference") for key, row in r.items()}}
    if gates["status"] != "BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE" or gates["algorithm"] != algorithm:
        raise ValueError("stage admission does not match the algorithm")
    return {"g_ratio": ratio(gates["g"]["comparison"], "current_over_reference"),
            "r_ratios": {"amazon": ratio(gates["r"]["comparison"], "candidate_over_reference"),
                         "amazon_odd": ratio(extra["comparison"], "candidate_over_reference")}}


def stage_receipts(algorithm, gates, extra):
    if algorithm == "respr":
        # The ResPR admission pins the screen, raw board receipt, and frozen
        # controls together with binaries. Recheck the compact receipts here.
        pins = [pin for pin in gates["pins"] if Path(pin["path"]).suffix == ".json"]
        if not any(Path(pin["path"]).parts[-2:] == ("board-once", "results.json") for pin in pins):
            raise ValueError("ResPR admission is missing its pinned R board receipt")
        for pin in pins:
            checked(pin)
        return {"admission": pins}

    stages = {"g": gates["g"], "r_amazon": gates["r"], "r_amazon_odd": extra}
    receipts = {"g_reference": gates["g"]["reference"]}
    checked(receipts["g_reference"])
    for role, stage in stages.items():
        pin = stage["report"]
        report = load(pin)
        clock = stage["candidate_clock"]
        if (report["algorithm"] != algorithm or report["comparison"] != stage["comparison"]
                or clock["binary"] != gates["image"]
                or clock["driver_reported_mhz"] != gates["resident_mhz"]):
            raise ValueError(f"{role} receipt differs from the resident admission")
        receipts[role] = pin
    return receipts


def record_topology(out, stage, job, gates, algorithm):
    if job["receipt"] != stage["report"] or not job["ready"]:
        raise ValueError("AU topology job does not match the resident admission")
    record_topology_receipt(out, stage, gates, algorithm)


def record_topology_receipt(out, stage, gates, algorithm):
    pin = stage["report"]
    raw = load(pin)
    clock = stage["candidate_clock"]
    if (raw["status"] != "PAIRED_ACTIVE_MIN_R_GATE_PASS" or raw["algorithm"] != algorithm
            or raw["comparison"] != stage["comparison"]
            or raw["comparison"]["equal_driver_reported_clocks"] is not True
            or clock["binary"] != gates["image"]
            or clock["driver_reported_mhz"] != gates["resident_mhz"]):
        raise ValueError("AU topology receipt does not match the resident admission")
    out["stage_ratios"]["r_ratios"]["au_slice"] = ratio(stage["comparison"], "candidate_over_reference")
    out["stage_receipts"]["r_au_slice"] = pin
    out.update(au_topology_stage=pin, r_validation_scope="amazon_and_askubuntu")


def record_cc_topology(out, matrix, gates, child=None):
    job = matrix.get("stages", {}).get("au_slice")
    if child is not None and ("retained_spine" in child or "warm_layout" in child):
        expected = {"amazon_odd": matrix.get("odd_r"), "au_slice": matrix.get("au_slice_r")}
        if job is None or child["additional_r_gates"] != expected:
            raise ValueError("matrix R controls differ from the warm CC pair admission")
    if job is None:
        out["r_validation_scope"] = "amazon_only_diagnostic"
        return
    record_topology(out, matrix["au_slice_r"], job, gates, "cc")
    out["cc_topology_stage"] = out["au_topology_stage"]


def record_sssp_topology(out, matrix, special, gates):
    if not matrix.get("require_au_topology"):
        out["r_validation_scope"] = "amazon_only_diagnostic"
        return
    child = load(special["result"])
    stage = matrix["au_slice_r"]
    if (special["result"] != matrix["au_result"] or child["additional_r_gates"]["au_slice"] != stage
            or child["stage_gates"] != gates):
        raise ValueError("SSSP topology evidence differs from the admitted AU resident pair")
    record_topology(out, stage, special["stages"]["au_slice"], gates, "weighted_sssp")


def pinned_spine_image(algorithm, child):
    if algorithm == "respr":
        return child["pins"]["spine_image"]
    path = child["case"]["spine_binary"]
    pins = [pin for pin in child["pins"] if pin["path"] == path]
    if not pins or any(pin != pins[0] for pin in pins):
        raise ValueError("no unambiguous Spine image pinned before the resident board pair")
    return pins[0]


def pinned_workload(case, pins):
    records = pins.values() if isinstance(pins, dict) else pins
    matches = [pin for pin in records if pin["path"] == case["graph"]]
    if not matches or any(pin != matches[0] for pin in matches):
        raise ValueError("no unambiguous graph and batch pinned before the resident board pair")
    with checked(matches[0]).open() as graph:
        dimensions = tuple(map(int, graph.readline().split()))
    workload = {key: case[key] for key in ("vertices", "edges", "updates", "source")}
    if (dimensions != tuple(workload[key] for key in ("vertices", "edges", "updates"))
            or not 0 <= workload["source"] < workload["vertices"]):
        raise ValueError("paired workload dimensions or source differ from the pinned input")
    return dict(workload, graph=matches[0])


def measured(algorithm, dataset, child, row, gates, extra, image, *, topology_miss=None):
    if (child["repetitions_per_arm"], child["warmups"]) != (1, 0):
        raise ValueError("one measured run and no warmups per arm required")
    boundary = BOUNDARIES[algorithm]
    if row["case"]["dataset"] != dataset or child["stage_gates"] != gates:
        raise ValueError("pair uses a different case or stage gate")
    if algorithm == "respr":
        arms = row["rows"]
        attempts = [entry["arm"] for entry in row["attempts"]]
        if row["case"]["algorithm"] != "residual_pagerank" or not row["pair"]["meets_propagation_screen"]:
            raise ValueError("ResPR pair does not satisfy its declared workload")
    else:
        arms = row["arms"]
        attempts = child["attempts"]
        if (child["algorithm"], child["dataset"], child["boundary"]) != (algorithm, dataset, boundary):
            raise ValueError("resident pair identity differs from the matrix")
    retained = child.get("retained_spine")
    expected_attempts = ["spine", "gr"] if retained is None else ["gr"]
    if set(arms) != {"spine", "gr"} or attempts != expected_attempts:
        raise ValueError("expected exactly one Spine run and one G+R run")
    stage = summarize_gates(algorithm, gates, extra)
    receipts = stage_receipts(algorithm, gates, extra)
    if topology_miss is not None:
        pin = topology_miss["report"]
        raw = load(pin)
        decision = topology_miss["comparison"]
        exception = topology_miss["resident_only_exception"]
        cap = active_min_admission.AU_DIAGNOSTIC_MAX_PERCENT
        if (algorithm == "respr" or child["additional_r_gates"] != {"amazon_odd": extra, "au_slice": topology_miss}
                or raw["status"] != "PAIRED_ACTIVE_MIN_R_GATE_FAILED_RETAINED"
                or raw["algorithm"] != algorithm or raw["comparison"] != decision
                or exception != {"max_slowdown_percent": cap - 100, "receipt_sha256": pin["sha256"]}
                or decision["retention_gate_pass"] is not False
                or decision["equal_driver_reported_clocks"] is not True
                or not 1.15 < decision["candidate_over_reference"] <= cap / 100
                or topology_miss["candidate_clock"]["binary"] != image
                or topology_miss["candidate_clock"]["driver_reported_mhz"] != gates["resident_mhz"]):
            raise ValueError("the disclosed AU topology miss does not match the measured pair")
        stage["r_ratios"]["au_slice"] = decision["candidate_over_reference"]
        receipts["r_au_slice"] = pin
    workload = pinned_workload(row["case"], child["pins"])
    if retained is not None:
        if ((algorithm, dataset) != ("cc", "AU") or retained not in child["pins"]
                or set(child["additional_r_gates"]) != {"amazon_odd", "au_slice"}
                or child["additional_r_gates"]["amazon_odd"] != extra):
            raise ValueError("retained Spine CC arm has no matching cross-topology baseline admission")
        original, _ = spine_cc_warm_receipt.replay(
            retained, workload["graph"], bdf=child["bdf"], affinity=child["cpu_affinity"])
        if original != arms["spine"]:
            raise ValueError("retained Spine arm differs from the original board sample")
    evidence = {arm: {stream: arm_row[stream] for stream in ("stdout", "stderr")}
                for arm, arm_row in arms.items()}
    for files in evidence.values():
        for pin in files.values():
            checked(pin)
    observed = {arm: clocks.replay(entry["clock_evidence"]) for arm, entry in arms.items()}
    mhz = {arm: record["driver_reported_mhz"] for arm, record in observed.items()}
    if (any(observed[arm] != entry["clock"] for arm, entry in arms.items())
            or mhz["gr"] != gates["resident_mhz"]
            or {record["bdf"] for record in observed.values()} != {child["bdf"]}
            or observed["gr"]["binary"] != image):
        raise ValueError("measured G+R image, clock or board differs from admission")
    if observed["spine"]["binary"] != pinned_spine_image(algorithm, child):
        raise ValueError("measured Spine image differs from its predeclared pin")
    pair_pin = row["comparison_log"]
    recorded = load(pair_pin)
    pair = row["pair"]
    if any(pair[key] != value for key, value in recorded.items()) or pair["boundary"] != boundary:
        raise ValueError("saved comparison differs from its pinned receipt")
    warm_record = {}
    if "warm_layout" in child:
        if algorithm != "cc" or retained is not None:
            raise ValueError("unexpected new warm CC layout receipt")
        warm_record = cc_resident_wall.replay_warm_pair(child, workload["graph"], observed, recorded)
    if algorithm == "cc":
        gr, spine, published = (pair[key] for key in ("gr_ms", "spine_ms", "gr_over_spine"))
        rounds = (pair["gr_supersteps"], pair["spine_rounds"])
    else:
        gr, spine, published = (pair[key] for key in ("gr_wall_ms", "spine_wall_ms", "speedup_gr_over_spine"))
        rounds = (pair["gr_rounds"], pair["spine_rounds"])
    if algorithm == "respr":
        if not all(type(value) is int and value >= 0 for value in rounds):
            raise ValueError("ResPR propagation rounds must be nonnegative integers")
        propagated = min(rounds) > 0
        requires_propagation = row["case"].get("requires_propagation")
        if (requires_propagation is not (dataset == "Flickr")
                or pair["positive_propagation_on_both"] is not propagated
                or (requires_propagation and not propagated)):
            raise ValueError("ResPR propagation does not match the declared workload")
    if not all(type(value) in (int, float) and math.isfinite(value) and value > 0
               for value in (gr, spine, published)):
        raise ValueError("wall times and speedup must be finite and positive")
    if not math.isclose(gr / spine, published, rel_tol=1e-12):
        raise ValueError("published speedup differs from the measured wall times")
    retained_record = {} if retained is None else {"retained_spine": retained}
    return dict(spine_ms=spine, gr_ms=gr, gr_over_spine=gr / spine,
                winner="Spine" if spine < gr else "G+R" if gr < spine else "tie",
                gr_rounds=rounds[0], spine_rounds=rounds[1],
                respr_propagated_on_both=(pair["positive_propagation_on_both"] if algorithm == "respr" else None),
                clocks_mhz=mhz, same_driver_clocks=mhz["spine"] == mhz["gr"],
                bdf=child["bdf"], workload=workload, stage_ratios=stage, comparison=pair_pin,
                stage_receipts=receipts,
                images={arm: record["binary"] for arm, record in observed.items()},
                clocks={arm: entry["clock_evidence"] for arm, entry in arms.items()}, raw=evidence,
                **retained_record, **warm_record)


def respr_case(rows, dataset):
    entries = [row for row in rows if row["case"]["dataset"] == dataset]
    if len(entries) > 1:
        raise ValueError(f"duplicate ResPR row: {dataset}")
    return entries[0] if entries else {}


def record_terminal_blocker(out, *journals):
    if out["status"] not in PENDING_ROWS or out.get("error"):
        return
    for role, journal in journals:
        status = journal["status"]
        if status in TERMINAL_BLOCKERS:
            reason = journal.get("error")
            out.update(status="BLOCKED_BY_TERMINAL_JOURNAL", blocked_by=role,
                       error=f"{status}: {reason}" if reason else status)
            return


def respr_propagation_screen(matrix, screen, screen_pin):
    out = dict(algorithm="respr", dataset="Flickr", boundary=BOUNDARIES["respr"])
    try:
        row = respr_case(screen.get("cases", []), "Flickr")
        out["status"] = row.get("status", "NOT_RECORDED")
        if out["status"] != "MEASURED":
            if row.get("error"):
                out["error"] = row["error"]
        elif not matrix.get("stage_gates"):
            out["status"] = "WAITING_FOR_MATCHED_MATRIX_ADMISSION"
        elif matrix.get("parent") != screen_pin:
            raise ValueError("matrix did not pin this ResPR propagation screen")
        else:
            out.update(measured("respr", "Flickr", screen, row, matrix["stage_gates"], None, matrix["image"]))
            out["status"] = MEASURED
        record_terminal_blocker(out, ("respr_screen", screen), ("respr_matrix", matrix))
    except (KeyError, ValueError, OSError, TypeError) as error:
        out.update(status="RECEIPT_REJECTED", error=str(error))
    return out


def candidate(algorithm, dataset, matrix, special):
    gates = matrix.get("stage_gates" if algorithm == "respr" else "baseline")
    if special is not None and dataset == SPECIAL[algorithm]:
        if algorithm == "respr":
            row = respr_case(special.get("cases", []), dataset)
            return row, special, gates, row.get("status") == "MEASURED"
        if special.get("status") != MEASURED:
            return special, None, gates, False
        pin = special["result"]
        if special.get("requested_pair") is not True:
            raise ValueError("screen did not request a board pair")
        if algorithm == "weighted_sssp" and gates and matrix.get("au_result") != pin:
            raise ValueError("matrix did not pin this AU pair")
        child = load(pin)
        return child, child, gates, True
    rows = matrix.get("cases", {})
    if algorithm == "respr":
        entry = respr_case(rows, dataset)
    else:
        entry = rows.get(dataset, {})
    if entry.get("status") != MEASURED:
        return entry, None, gates, False
    child = load(entry["result"])
    return (child["row"] if algorithm == "respr" else child), child, gates, True


def cc_replacement_au(matrix, entry):
    from . import cc_au_revision, cc_spine_route

    parent = matrix["parent"]
    comparison, route = parent["comparison"], parent["route"]
    if entry["result"] != comparison or entry.get("reused") is not True:
        raise ValueError("matrix did not reuse its exact replacement AU comparison")
    cc_spine_route.matrix_route(route)
    prepared, replayed = cc_au_revision.replay_comparison(comparison, route)
    anchor = load(prepared["arm"])
    gates = matrix["baseline"]
    if anchor["stage_gates"] != gates or entry["comparison"] != replayed["new_pair"]:
        raise ValueError("AU replacement differs from the admitted matrix pair")
    pair = replayed["new_pair"]
    smoke = load(replayed["candidate_smoke"])
    prior = prepared["prior"]
    out = dict(prior, comparison=comparison, spine_ms=pair["spine_ms"], gr_ms=pair["gr_ms"],
               gr_over_spine=pair["gr_over_spine"], spine_rounds=pair["spine_rounds"],
               gr_rounds=pair["gr_supersteps"],
               winner="Spine" if pair["spine_ms"] < pair["gr_ms"] else
                      "G+R" if pair["spine_ms"] > pair["gr_ms"] else "tie",
               images=dict(prior["images"], spine=prepared["files"]["image"]),
               clocks=dict(prior["clocks"], spine=smoke["clock_evidence"]),
               clocks_mhz=dict(prior["clocks_mhz"], spine=prior["clocks_mhz"]["gr"]),
               same_driver_clocks=True, replacement_spine=replayed["candidate_smoke"],
               raw=dict(prior["raw"], spine={key: smoke[key] for key in ("stdout", "stderr")}))
    del out["retained_spine"]
    record_cc_topology(out, matrix, gates, anchor)
    return out


def export(paths):
    required = set(ROLES) - OPTIONAL_SCREENS
    if not required <= paths.keys() <= set(ROLES):
        raise ValueError("supply the three matrices and the ResPR screen, with optional legacy AU/R19 screens")
    pins = {name: identity(path) for name, path in paths.items()}
    snapshots = {name: load(pin) for name, pin in pins.items()}
    result = {"status": "SNAPSHOT_NOT_FINAL_EVALUATION", "inputs": pins,
              "journal_status": {name: data["status"] for name, data in snapshots.items()},
              "journal_errors": {name: data["error"] for name, data in snapshots.items() if data.get("error")},
              "rows": []}
    result["respr_propagation_screen"] = respr_propagation_screen(
        snapshots["respr_matrix"], snapshots["respr_screen"], pins["respr_screen"])
    for algorithm, (matrix_role, screen_role) in JOURNALS.items():
        matrix, special = snapshots[matrix_role], snapshots.get(screen_role)
        if algorithm != "respr":
            in_matrix = SPECIAL[algorithm] in matrix.get("cases", {})
            if in_matrix == (special is not None):
                raise ValueError(f"{algorithm} {SPECIAL[algorithm]} must have exactly one journal source")
        for dataset in DATASETS:
            out = dict(algorithm=algorithm, dataset=dataset, boundary=BOUNDARIES[algorithm])
            try:
                entry = matrix.get("cases", {}).get("AU", {}) if algorithm == "cc" and dataset == "AU" else {}
                if entry.get("kind") == "replacement_au":
                    out.update(cc_replacement_au(matrix, entry), status=MEASURED)
                    result["rows"].append(out)
                    continue
                row, child, gates, ready = candidate(algorithm, dataset, matrix, special)
                out["status"] = row.get("status", "NOT_RECORDED")
                if ready:
                    if not gates:
                        out["status"] = "WAITING_FOR_MATCHED_MATRIX_ADMISSION"
                    else:
                        if algorithm != "respr" and child["status"] != MEASURED:
                            raise ValueError("resident child did not pass")
                        if algorithm == "respr" and dataset != "R19" and child["status"] != MEASURED:
                            raise ValueError("resident ResPR child did not pass")
                        if algorithm == "respr" and dataset == "R19" and matrix.get("parent") != pins["respr_screen"]:
                            raise ValueError("matrix did not pin this ResPR R19 screen")
                        image = matrix["image"] if algorithm == "respr" else gates["image"]
                        row_data = measured(algorithm, dataset, child, row, gates, matrix.get("odd_r"), image)
                        if algorithm == "cc":
                            route = matrix.get("parent", {}).get("route")
                            if route is not None and child.get("warm_candidate") != route:
                                raise ValueError("CC matrix row uses a different Spine route than AU")
                            record_cc_topology(row_data, matrix, gates, child)
                        elif algorithm == "weighted_sssp":
                            record_sssp_topology(row_data, matrix, special, gates)
                        out.update(row_data)
                        out["status"] = MEASURED
                elif row.get("error"):
                    out["error"] = row["error"]
                journals = [(matrix_role, matrix)]
                if special is not None and dataset == SPECIAL[algorithm]:
                    journals.insert(0, (screen_role, special))
                record_terminal_blocker(out, *journals)
            except (KeyError, ValueError, OSError, TypeError) as error:
                out.update(status="RECEIPT_REJECTED", error=str(error))
            result["rows"].append(out)
    for pin in pins.values():
        checked(pin)
    return result


def write_csv(path, rows):
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            record = {field: row[field] for field in CSV_FIELDS if field in row}
            if row["status"] == MEASURED:
                workload = row["workload"]
                record.update({key: workload[key] for key in ("vertices", "edges", "updates", "source")},
                              graph_sha256=workload["graph"]["sha256"],
                              comparison_sha256=row["comparison"]["sha256"])
            writer.writerow(record)


def export_diagnostic(paths):
    """Record the two explicitly non-parity matrices, leaving ResPR unmeasured."""
    algorithms = ("weighted_sssp", "cc")
    pins = {key: identity(path) for key, path in zip(algorithms, paths, strict=True)}
    snapshots = {key: load(pin) for key, pin in pins.items()}
    result = {"status": "DIAGNOSTIC_SNAPSHOT_NOT_FINAL_EVALUATION", "inputs": pins, "rows": []}
    for algorithm in ALGORITHMS:
        matrix = snapshots.get(algorithm)
        if matrix and (matrix["algorithm"] != algorithm or matrix["r_retention_all_controls_pass"] is not False):
            raise ValueError("expected the explicitly non-parity resident matrix")
        for dataset in DATASETS:
            out = dict(algorithm=algorithm, dataset=dataset, boundary=BOUNDARIES[algorithm],
                       status="NOT_RECORDED")
            if matrix:
                entry = matrix["cases"][dataset]
                out.update(status=entry["status"], r_validation_scope="amazon_pass_au_outside_15_percent")
                if entry.get("result"):
                    try:
                        child = load(entry["result"])
                        if entry["status"] == MEASURED:
                            gates, extra = matrix["baseline"], matrix["additional_r_gates"]
                            out.update(measured(algorithm, dataset, child, child, gates, extra["amazon_odd"],
                                                gates["image"], topology_miss=extra["au_slice"]))
                        elif child.get("error"):
                            out["error"] = child["error"]
                    except (KeyError, ValueError, OSError, TypeError) as error:
                        out.update(status="RECEIPT_REJECTED", error=str(error))
                elif entry.get("error"):
                    out["error"] = entry["error"]
            result["rows"].append(out)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic-matrices", nargs=2, type=Path, metavar=("SSSP", "CC"))
    for role in (*ROLES, "output"):
        parser.add_argument("--" + role.replace("_", "-"), type=Path, required=role == "output")
    parser.add_argument("--csv", type=Path, help="optional flat data table with all declared rows")
    args = parser.parse_args()
    outputs = [args.output] + ([args.csv] if args.csv is not None else [])
    if len({path.resolve() for path in outputs}) != len(outputs):
        parser.error("the JSON and CSV must be different files")
    for path in outputs:
        if path.exists():
            raise FileExistsError(path)
    strict = {key: getattr(args, key) for key in ROLES if getattr(args, key) is not None}
    if args.diagnostic_matrices and strict:
        parser.error("choose strict receipts or the explicitly non-parity diagnostic matrices")
    result = export_diagnostic(args.diagnostic_matrices) if args.diagnostic_matrices else export(strict)
    save(args.output, result)
    if args.csv is not None:
        write_csv(args.csv, result["rows"])
    print(f"{sum(row['status'] == MEASURED for row in result['rows'])}/{len(result['rows'])} "
          "receipt-verified pairs; not final evaluation")


if __name__ == "__main__":
    main()
