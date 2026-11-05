"""Export a frozen, explicitly incomplete FPGA checkpoint without filling missing rows."""

import argparse
import csv
import gzip
import io
import json
import math
import tarfile
from pathlib import Path

import export_banked_sssp as sssp
import export_controls as controls
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    cc_checkpoint, correction_matrix, host_correction,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.follow import unchanged
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity


ALGORITHMS = ("weighted_sssp", "cc", "residual_pagerank")
FIELDS = ("algorithm", "dataset", "status", "boundary", "spine_wall_ms", "gr_wall_ms",
          "speedup_gr_over_spine", "spine_rounds", "gr_rounds", "fresh_spine_samples",
          "fresh_gr_samples", "gr_sample_reused", "resident_cache_bytes",
          "old_graph_cache_preparation_ms", "dense_dangling_fallback", "data_mhz",
          "kernel_mhz", "hbm_mhz", "nominal_timing_pass", "receipt_sha256")


def measured_row(algorithm, dataset, pair, pin, profile, *, reused=False, correction=None):
    spine, gr = (pair[key] for key in ("spine_wall_ms", "gr_wall_ms"))
    if (not all(type(value) in (int, float) and math.isfinite(value) and value > 0
                for value in (spine, gr, pair["speedup_gr_over_spine"]))
            or not math.isclose(pair["speedup_gr_over_spine"], gr / spine)
            or (pair["algorithm"], pair["logical_updates"], pair["physical_updates"]) != (algorithm, 8, 8)):
        raise ValueError("invalid paired times, algorithm, batch or round scope")
    row = dict(algorithm=algorithm, dataset=dataset, status="MEASURED",
               boundary=pair["boundary"], spine_wall_ms=spine, gr_wall_ms=gr,
               speedup_gr_over_spine=gr / spine, spine_rounds=pair["spine_rounds"],
               gr_rounds=pair["gr_rounds"], fresh_spine_samples=1,
               fresh_gr_samples=0 if reused else 1, gr_sample_reused=reused,
               data_mhz=profile[0], kernel_mhz=profile[1], hbm_mhz=profile[2],
               nominal_timing_pass=algorithm != "residual_pagerank", receipt_sha256=pin["sha256"])
    if correction is not None:
        row.update(correction)
    return row


def retime_fragments(paths):
    paths = [paths] if isinstance(paths, Path) else paths
    cases, members, sources = {}, {}, {}
    for number, path in enumerate(paths):
        raw = path.read_bytes()
        report = json.loads(raw)
        unchanged(report["pins"])
        declared = report["cases"]
        if (not declared or not set(declared) <= set(sssp.DATASETS)
                or number == 0 and set(declared) != set(sssp.DATASETS)):
            raise ValueError("first retime matrix must declare all eight; fragments need known datasets")
        name = "retime-matrix.json" if number == 0 else f"retime-fragments/{number:02d}.json"
        members[name] = raw
        for dataset, case in declared.items():
            previous = cases.get(dataset, {})
            if previous.get("status") == correction_matrix.MEASURED:
                if case.get("status") == correction_matrix.MEASURED and case != previous:
                    raise ValueError("conflicting measured retime samples for " + dataset)
                continue
            cases[dataset], sources[dataset] = case, name
    if set(cases) != set(sssp.DATASETS):
        raise ValueError("all eight retime statuses required")
    return cases, members, sources


def collect(args):
    with args.controls.open(newline="") as stream:
        stage_rows = list(csv.DictReader(stream))
    expected_images = {row["algorithm"]: row["current_image_sha256"]
                       for row in stage_rows if row["stage"] == "G"}
    if set(expected_images) != set(ALGORITHMS):
        raise ValueError("current G/R controls for all three algorithms required")
    host_correction.admit(args.qualification, args.spine_host)
    matrix_bytes = args.sssp_matrix.read_bytes()
    sssp_rows, sssp_members = sssp.collect(matrix_bytes)
    retime_paths = [args.retimes] if isinstance(args.retimes, Path) else args.retimes
    retimes, retime_members, retime_sources = retime_fragments(retime_paths)
    cc_bytes = args.cc_matrix.read_bytes()
    cc = json.loads(cc_bytes)
    cc_rows, cc_evidence = cc_checkpoint.collect(cc, expected_images["cc"])
    members = {"sssp/" + name: data for name, data in sssp_members.items()}
    members.update(retime_members)
    members["cc-matrix.json"] = cc_bytes
    index, evidence, rows = {}, cc_evidence, []
    for row in sssp_rows:
        if expected_images["weighted_sssp"] != sssp.GR_IMAGE:
            raise ValueError("SSSP controls and resident baseline differ")
        rows.append(measured_row("weighted_sssp", row["dataset"], row,
                                 dict(sha256=row["receipt_sha256"]), sssp.CLOCKS))
    for row in cc_rows:
        if row["status"] == "MEASURED":
            rows.append(measured_row("cc", row["dataset"], row["pair"], row["receipt"],
                                     [150, 500, 450, 0], reused=row["gr_sample_reused"]))
        else:
            rows.append(dict(algorithm="cc", dataset=row["dataset"], status=row["status"]))
    for dataset in sssp.DATASETS:
        case = retimes[dataset]
        if case["status"] != correction_matrix.MEASURED:
            rows.append(dict(algorithm="residual_pagerank", dataset=dataset, status=case["status"]))
            continue
        pin = case["result"]
        unchanged([pin])
        report = json.loads(Path(pin["path"]).read_text())
        checked = correction_matrix.validate_result(Path(pin["path"]),
            Path(report["reference_pair"]["path"]), args, dataset)
        if (case["pair"] != checked["pair"] or case["correction"] != checked["correction"]
                or report["stage_gates"]["image"]["sha256"] != expected_images["residual_pagerank"]):
            raise ValueError("retime summary or baseline image differs from admitted source controls")
        rows.append(measured_row("residual_pagerank", dataset, checked["pair"], pin,
            report["stage_gates"]["resident_mhz"], reused=True, correction=checked["correction"]))
        evidence.append(dict(result=pin, report=report))
    controls.small_evidence(evidence, members, index)
    status = ("MEASURED_CURRENT_FPGA_MATRIX" if all(row["status"] == "MEASURED" for row in rows)
              else "INCOMPLETE_CURRENT_FPGA_CHECKPOINT")
    return rows, members, dict(status=status, measured_pairs=sum(row["status"] == "MEASURED" for row in rows),
        expected_pairs=24, inputs=[identity(path) for path in
            (args.sssp_matrix, *retime_paths, args.cc_matrix, args.controls, args.qualification)],
        retime_sources=retime_sources,
        evidence=evidence, artifact_index=list(index.values()),
        limitation="ResPR host-only single-batch cache, old-graph preparation excluded/reported; G+R reused",
        cc="replacement-route measurements replayed when present; old AU loss and seven row-overflow failures retained",
        publication_throughput_reproduced=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sssp-matrix", "cc-matrix", "controls", "qualification",
                 "spine-host", "comparator", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--retimes", type=Path, action="append", required=True,
                        help="Full original matrix, then explicit retained remainder fragments")
    args = parser.parse_args()
    rows, members, scope = collect(args)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "fig7_resident_checkpoint.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "scope.json").write_text(json.dumps(scope, indent=2) + "\n")
    with (args.output / "receipts.tar.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for name, data in sorted(members.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))


if __name__ == "__main__":
    main()
