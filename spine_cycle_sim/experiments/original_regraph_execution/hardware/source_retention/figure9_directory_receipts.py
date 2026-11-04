"""Export the nine frozen-versus-directory Figure 9 simulator diagnostics."""

import argparse
import json
import math
from pathlib import Path

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.tables import csv_bytes

from .runtime import identity


KEYS = tuple((algorithm, dataset) for algorithm in ("SSSP", "CC", "ResPR") for dataset in ("AU", "SU", "WK"))
FROZEN = {
    "figure9_multialgorithm_20261023/matrix-v5": "1d70cb7ee64019729430f0815c0debc811da2934d4240a870a37c83f59bbf239",
    "respr_fixed_epsilon_20261023/matrix": "45ba25365f9ef57cd437852b51c47b0786430962d105fbf8a5c53675a3822deb",
}
DIRECTORY = {
    "fig9-directory-au-sssp-v2": "c20287c200d8b14832b552fa443b9a88c55f461e992ea895f5eda5392ee67f3a",
    "fig9-directory-sssp-remaining-v1": "a9910cfa451a47bff6da2536f7a805bcb9a2acf1913004d42d83b5ded4e70f23",
    "fig9-directory-cc-remaining-v1": "133c0dca01a331cbe16df098d264a122f679b0de442ce767f626a821cbdc00bd",
    "fig9-directory-respr-remaining-v1": "6386dbf87d601f3ab44edf72b015be3bd76197a9277a83c3482d531cd39f0186",
}


def case_key(row):
    return row["algorithm"], row["dataset"]


def load_rows(root, sources, directory):
    rows = {}
    for subdir, sha in sources.items():
        path = root / subdir / "results.json"
        if identity(path)["sha256"] != sha:
            raise ValueError(f"unexpected Figure 9 result identity: {path}")
        report = json.loads(path.read_text())
        model = report["model"]
        if (report["status"] != "COMPLETE_SUPPORTED_SCOPE" or not report["pins_unchanged"]
                or report["failures"] or report["baseline_admitted"] is not False
                or model.get("gr_drain_directory", False) is not directory):
            raise ValueError(f"not a complete non-admitted simulation in the requested mode: {path}")
        cases = {case_key(case): case for case in report["matrix"]}
        pins = {pin["path"]: pin["sha256"] for pin in report["pins"]}
        for row in report["rows"]:
            key = case_key(row)
            # The original mixed report's ResPR rows used a different threshold.
            if key[0] == "ResPR" and "residual_epsilon" not in model:
                if directory:
                    raise ValueError("missing fixed epsilon for directory ResPR")
                continue
            if key in rows or (key[0] == "ResPR" and
                               not math.isclose(model["residual_epsilon"], 1e-6, rel_tol=1e-6)):
                raise ValueError(f"duplicate case or incompatible ResPR threshold: {key}")
            case = cases[key]
            inputs = (case["vertices"], case["initial_edges"], case["projection"], case.get("root"),
                      case["physical_update_records"], pins[case["graph"]], pins[case["update_file"]])
            rows[key] = (row, inputs, report["git_head"], sha)
    if set(rows) != set(KEYS):
        raise ValueError("exactly the nine declared Figure 9 cases are required")
    return rows


def comparison(old, new):
    for row in (old, new):
        if row["status"] != "PREDICTION_ONLY" or row["baseline_admitted"] is not False or row["updates"] != 8:
            raise ValueError("expected a prediction-only eight-update comparison")
    out = {}
    for prefix, row in (("frozen", old), ("directory", new)):
        totals = {}
        for arm in ("gr", "spine"):
            data = row[arm]
            if not data["correctness"] or not data["ledger_closed"]:
                raise ValueError("both simulation arms must pass correctness and ledger checks")
            if data["state_hashes"] != old[arm]["state_hashes"]:
                raise ValueError("old, final or expected state changed across snapshots")
            totals[arm] = values = (data["read_bytes"] + data["write_bytes"], data["energy_pj"])
            if not all(math.isfinite(value) and value > 0 for value in values):
                raise ValueError("positive finite accepted bytes and modeled HBM energy required")
            out[f"{prefix}_{arm}_accepted_bytes"], out[f"{prefix}_{arm}_hbm_energy_pj"] = values
        for index, label in enumerate(("accepted_bytes", "hbm_energy")):
            value = totals["gr"][index] / totals["spine"][index]
            if not math.isclose(value, row[f"{label}_ratio"], rel_tol=1e-12):
                raise ValueError(f"recorded {label} ratio differs from the raw totals")
            out[f"{prefix}_{label}_ratio_gr_over_spine"] = value
    return out


def export(frozen, directory):
    old, new = load_rows(frozen, FROZEN, False), load_rows(directory, DIRECTORY, True)
    rows = []
    for algorithm, dataset in KEYS:
        original, inputs, old_commit, old_sha = old[algorithm, dataset]
        diagnostic, new_inputs, new_commit, new_sha = new[algorithm, dataset]
        if inputs != new_inputs:
            raise ValueError(f"graph, update or case parameters changed: {algorithm}/{dataset}")
        rows.append(dict(algorithm=algorithm, dataset=dataset, status="PREDICTION_ONLY",
                         baseline_admitted="false", vertices=inputs[0], initial_edges=inputs[1],
                         physical_updates=inputs[4], graph_sha256=inputs[5], updates_sha256=inputs[6],
                         **comparison(original, diagnostic), frozen_commit=old_commit,
                         directory_commit=new_commit, frozen_receipt_sha256=old_sha,
                         directory_receipt_sha256=new_sha))
    return csv_bytes(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("frozen", "directory", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    data = export(args.frozen, args.directory)
    with args.output.open("xb") as stream:
        stream.write(data)


if __name__ == "__main__":
    main()
