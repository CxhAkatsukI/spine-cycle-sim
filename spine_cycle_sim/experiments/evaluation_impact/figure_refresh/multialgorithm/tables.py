"""One explicit nine-pair Figure 9 view, retaining SSSP source provenance."""

import csv
import io


def csv_bytes(rows):
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode()


def export_rows(summary):
    ratios, absolute = [], []
    rows = [*summary["retained_sssp"], *summary["comparisons"]]
    for row in rows:
        case = row["case"]
        scope = "retained_pinned_SSSP" if row["algorithm"] == "SSSP" else "fresh_CC_ResPR"
        common = dict(dataset=row["dataset"], algorithm=row["algorithm"], updates=row["updates"],
                      projection=case.get("projection", "directed"), provenance=scope)
        ratios.append(dict(**common, memory_ratio_gr_over_spine=row["accepted_bytes_ratio"],
            hbm_energy_ratio_gr_over_spine=row["hbm_energy_ratio"],
            spine_memory_bytes=row["spine"]["read_bytes"] + row["spine"]["write_bytes"],
            gr_memory_bytes=row["gr"]["read_bytes"] + row["gr"]["write_bytes"],
            source_report_sha256=row["source_report_sha256"]))
        for arm in ("spine", "gr"):
            data = row[arm]
            energy = (summary["retained_energy_details"][row["dataset"]][arm]
                      if row["algorithm"] == "SSSP" else data["energy_details"])
            absolute.append(dict(**common, arm=arm, vertices=case["vertices"],
                initial_edges=case["initial_edges"], physical_update_records=case.get("physical_update_records", 8),
                device_cycles=data["cycles"], rounds=data["rounds"], read_bytes=data["read_bytes"],
                write_bytes=data["write_bytes"], **energy,
                correction_oracle_directed=data.get("correction_oracle_directed", False),
                evidence=data["evidence"], source_report_sha256=row["source_report_sha256"]))
    return {"fig9_memory_energy_rows.csv": csv_bytes(ratios), "fig9_arms.csv": csv_bytes(absolute)}
