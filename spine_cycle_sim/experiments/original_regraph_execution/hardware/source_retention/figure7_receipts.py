"""Export a Figure 7 evidence snapshot from the single-pass FPGA journals."""

import argparse
import json
import math
from pathlib import Path

from . import active_min_resident, cc_resident_wall, clocks, resident_matrix
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


def pinned_spine_image(algorithm, child):
    if algorithm == "respr":
        return child["pins"]["spine_image"]
    path = child["case"]["spine_binary"]
    pins = [pin for pin in child["pins"] if pin["path"] == path]
    if not pins or any(pin != pins[0] for pin in pins):
        raise ValueError("no unambiguous Spine image pinned before the resident board pair")
    return pins[0]


def measured(algorithm, dataset, child, row, gates, extra, image):
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
    if set(arms) != {"spine", "gr"} or attempts != ["spine", "gr"]:
        raise ValueError("expected exactly one Spine run and one G+R run")
    stage = summarize_gates(algorithm, gates, extra)
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
    if algorithm == "cc":
        gr, spine, published = (pair[key] for key in ("gr_ms", "spine_ms", "gr_over_spine"))
        rounds = (pair["gr_supersteps"], pair["spine_rounds"])
    else:
        gr, spine, published = (pair[key] for key in ("gr_wall_ms", "spine_wall_ms", "speedup_gr_over_spine"))
        rounds = (pair["gr_rounds"], pair["spine_rounds"])
    if not all(type(value) in (int, float) and math.isfinite(value) and value > 0
               for value in (gr, spine, published)):
        raise ValueError("wall times and speedup must be finite and positive")
    if not math.isclose(gr / spine, published, rel_tol=1e-12):
        raise ValueError("published speedup differs from the measured wall times")
    return dict(spine_ms=spine, gr_ms=gr, gr_over_spine=gr / spine,
                winner="Spine" if spine < gr else "G+R" if gr < spine else "tie",
                gr_rounds=rounds[0], spine_rounds=rounds[1],
                respr_propagated_on_both=(pair["positive_propagation_on_both"] if algorithm == "respr" else None),
                clocks_mhz=mhz, same_driver_clocks=mhz["spine"] == mhz["gr"],
                bdf=child["bdf"], stage_ratios=stage, comparison=pair_pin,
                images={arm: record["binary"] for arm, record in observed.items()},
                clocks={arm: entry["clock_evidence"] for arm, entry in arms.items()}, raw=evidence)


def candidate(algorithm, dataset, matrix, special):
    gates = matrix.get("stage_gates" if algorithm == "respr" else "baseline")
    if special is not None and dataset == SPECIAL[algorithm]:
        if algorithm == "respr":
            rows = [row for row in special.get("cases", []) if row["case"]["dataset"] == dataset]
            if len(rows) > 1:
                raise ValueError("duplicate R19 ResPR screen row")
            row = rows[0] if rows else {}
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
        entries = [row for row in rows if row["case"]["dataset"] == dataset]
        if len(entries) > 1:
            raise ValueError(f"duplicate ResPR matrix row: {dataset}")
        entry = entries[0] if entries else {}
    else:
        entry = rows.get(dataset, {})
    if entry.get("status") != MEASURED:
        return entry, None, gates, False
    child = load(entry["result"])
    return (child["row"] if algorithm == "respr" else child), child, gates, True


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
    for algorithm, (matrix_role, screen_role) in JOURNALS.items():
        matrix, special = snapshots[matrix_role], snapshots.get(screen_role)
        if algorithm != "respr":
            in_matrix = SPECIAL[algorithm] in matrix.get("cases", {})
            if in_matrix == (special is not None):
                raise ValueError(f"{algorithm} {SPECIAL[algorithm]} must have exactly one journal source")
        for dataset in DATASETS:
            out = dict(algorithm=algorithm, dataset=dataset, boundary=BOUNDARIES[algorithm])
            try:
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
                        image = matrix["image"] if algorithm == "respr" else gates["image"]
                        out.update(measured(algorithm, dataset, child, row, gates, matrix.get("odd_r"), image))
                        out["status"] = MEASURED
                elif row.get("error"):
                    out["error"] = row["error"]
            except (KeyError, ValueError, OSError, TypeError) as error:
                out.update(status="RECEIPT_REJECTED", error=str(error))
            result["rows"].append(out)
    for pin in pins.values():
        checked(pin)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for role in (*ROLES, "output"):
        parser.add_argument("--" + role.replace("_", "-"), type=Path, required=role not in OPTIONAL_SCREENS)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = export({key: getattr(args, key) for key in ROLES if getattr(args, key) is not None})
    save(args.output, result)
    print(f"{sum(row['status'] == MEASURED for row in result['rows'])}/{len(result['rows'])} admitted pairs")


if __name__ == "__main__":
    main()
