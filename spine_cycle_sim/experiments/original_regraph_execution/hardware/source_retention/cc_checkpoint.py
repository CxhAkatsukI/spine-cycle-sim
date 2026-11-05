"""Replay the replacement-route CC matrix for a frozen figure-data checkpoint."""

from . import figure7_receipts as figure
from .follow import unchanged


def collect(matrix, expected_image):
    if set(matrix["cases"]) != set(figure.DATASETS):
        raise ValueError("all eight CC statuses required")
    rows, evidence = [], []
    measured = any(row["status"] == figure.MEASURED for row in matrix["cases"].values())
    if measured:
        unchanged(matrix["runner_pins"])
        gate = matrix["baseline"]
        if (gate["algorithm"], gate["image"]["sha256"], gate["resident_mhz"]) != (
                "cc", expected_image, [150, 500, 450, 0]):
            raise ValueError("CC baseline differs from the current G/R controls")
    for dataset in figure.DATASETS:
        entry = matrix["cases"][dataset]
        if entry["status"] != figure.MEASURED:
            row = dict(dataset=dataset, status=entry["status"])
            for key in ("error", "service_exit", "child_status"):
                if key in entry:
                    row[key] = entry[key]
            if matrix["status"] == "FAILED_RETAINED":
                row.update(parent_status=matrix["status"], parent_error=matrix.get("error"))
            rows.append(row)
            continue
        if dataset == "AU":
            if entry.get("kind") != "replacement_au":
                raise ValueError("CC checkpoint requires the replacement-route AU sample")
            checked = figure.cc_replacement_au(matrix, entry)
        else:
            child = figure.load(entry["result"])
            if (child["status"] != figure.MEASURED
                    or child.get("warm_candidate") != matrix["parent"]["route"]
                    or entry.get("attempts") != ["spine", "gr"]):
                raise ValueError("CC sample differs from the new route or single-pass protocol")
            checked = figure.measured("cc", dataset, child, child, gate,
                                      matrix["odd_r"], gate["image"])
            figure.record_cc_topology(checked, matrix, gate, child)
            evidence.append(child)
        workload = checked["workload"]
        if (workload["updates"] != 8 or not checked["same_driver_clocks"]
                or checked["clocks_mhz"]["gr"] != gate["resident_mhz"]
                or checked["images"]["gr"]["sha256"] != expected_image):
            raise ValueError("CC pair changed the batch, matched clocks or baseline image")
        pair = dict(algorithm="cc", logical_updates=8, physical_updates=8,
                    boundary=figure.BOUNDARIES["cc"], spine_wall_ms=checked["spine_ms"],
                    gr_wall_ms=checked["gr_ms"], speedup_gr_over_spine=checked["gr_over_spine"],
                    spine_rounds=checked["spine_rounds"], gr_rounds=checked["gr_rounds"])
        rows.append(dict(dataset=dataset, status="MEASURED", pair=pair,
                         receipt=entry["result"], gr_sample_reused=dataset == "AU"))
        evidence.append(dict(replay=checked, result=entry["result"],
                             report=figure.load(entry["result"])))
    return rows, evidence
