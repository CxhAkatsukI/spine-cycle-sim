"""Replay current G/R hardware controls; never substitute the older ResPR image."""

import argparse
import csv
import gzip
import io
import json
import math
import tarfile
from pathlib import Path

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    active_min_admission, dual_clock_resident,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity


def stage_row(algorithm, stage, workload, comparison, image, profile, *, nominal_timing_pass):
    ratio = comparison.get("candidate_over_reference", comparison.get("current_over_reference"))
    if (type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 < ratio <= 1.15
            or comparison.get("at_most_15_percent_slower") is not True):
        raise ValueError("current control does not pass the one-sided retention screen")
    return dict(algorithm=algorithm, stage=stage, workload=workload,
                current_over_public=ratio, slowdown_percent=100 * (ratio - 1),
                at_most_15_percent_slower=True, absolute_15_percent_parity=abs(ratio - 1) <= 0.15,
                current_image_sha256=image["sha256"], data_mhz=profile[0], kernel_mhz=profile[1],
                hbm_mhz=profile[2], nominal_timing_pass=nominal_timing_pass,
                repetitions_per_arm=1, publication_throughput_reproduced=False)


def small_evidence(value, members, index):
    if isinstance(value, list):
        for item in value:
            small_evidence(item, members, index)
    elif isinstance(value, dict):
        if {"path", "sha256", "bytes"} <= value.keys():
            pin = {key: value[key] for key in ("path", "sha256", "bytes")}
            index[pin["path"]] = pin
            path = Path(pin["path"])
            if pin["bytes"] <= 2 * 2**20 and path.suffix in (".json", ".txt", ".log"):
                if identity(path) != pin:
                    raise ValueError("small evidence changed: " + str(path))
                members[f"objects/{pin['sha256']}/{path.name}"] = path.read_bytes()
        else:
            for item in value.values():
                small_evidence(item, members, index)


def replay_active(gate, controls, members, index):
    algorithm = gate["algorithm"]
    image, host = gate["image"], gate["host"]
    g = gate["g"]
    observed = active_min_admission.replay_g(Path(g["report"]["path"]),
        Path(g["reference"]["path"]), algorithm, host, image)
    if observed != g:
        raise ValueError("G gate changed since the resident sample")
    row = stage_row(algorithm, "G", "AU-131K", g["comparison"], image,
                    gate["resident_mhz"], nominal_timing_pass=True)
    row.update(public_ms=g["comparison"]["reference_ms"], current_ms=g["comparison"]["current_ms"])
    rows = [row]
    for workload, control, geometry in controls:
        report_path = Path(control["report"]["path"])
        if identity(report_path) != control["report"]:
            raise ValueError("R receipt digest changed")
        report = json.loads(report_path.read_text())
        inputs = Path(report["arms"]["candidate"]["execution"]["command"][-3])
        replayed = active_min_admission.replay_r(report_path, algorithm, inputs, host, image,
                                                 geometry=geometry)
        if replayed != control:
            raise ValueError("R gate changed since the resident sample")
        row = stage_row(algorithm, "R", workload, control["comparison"], image,
                        gate["resident_mhz"], nominal_timing_pass=True)
        for arm, field in (("reference", "public_ms"), ("candidate", "current_ms")):
            row[field] = report["arms"][arm]["analysis"]["event_span_ns"] / 1e6
        rows.append(row)
        small_evidence(report, members, index)
    small_evidence(gate, members, index)
    for pin in (g["report"], g["reference"]):
        small_evidence(json.loads(Path(pin["path"]).read_text()), members, index)
    return rows


def collect(sssp_path, cc_path, respr_g, respr_r, route):
    members, index, rows = {}, {}, []
    for path in (sssp_path, cc_path, respr_g, respr_r):
        pin = identity(path)
        members[f"receipts/{path.parent.name}/{path.name}"] = path.read_bytes()
        small_evidence(pin, members, index)
    sssp, cc = (json.loads(path.read_text()) for path in (sssp_path, cc_path))
    for gate, controls in (
        (sssp["baseline"], (("AM", sssp["baseline"]["r"], active_min_admission.AMAZON_GEOMETRY),
                            ("AM+", sssp["odd_r"], active_min_admission.AMAZON_GEOMETRY),
                            ("AU", sssp["au_slice_r"], active_min_admission.AU_SLICE_GEOMETRY))),
        (cc["stage_gates"], (("AM", cc["stage_gates"]["r"], active_min_admission.AMAZON_GEOMETRY),
                             ("AM+", cc["additional_r_gates"]["amazon_odd"], active_min_admission.AMAZON_GEOMETRY),
                             ("AU", cc["additional_r_gates"]["au_slice"], active_min_admission.AU_SLICE_GEOMETRY))),
    ):
        rows += replay_active(gate, controls, members, index)
    gate = dual_clock_resident.admit(respr_r, respr_g, route)
    for stage, workload, control in [("G", "AU-131K", gate["g_control"])] + [
            ("R", control["case"], control) for control in gate["r_controls"]]:
        row = stage_row("residual_pagerank", stage, workload, control, gate["image"],
                        gate["resident_mhz"], nominal_timing_pass=False)
        row.update(public_ms=control["reference_ms"], current_ms=control["current_ms"])
        rows.append(row)
    for path in (respr_g, respr_r):
        report = json.loads(path.read_text())
        small_evidence(report, members, index)
        if "measurement" in report:
            small_evidence(json.loads(Path(report["measurement"]["path"]).read_text()), members, index)
    if len(rows) != 11 or {row["algorithm"] for row in rows} != {
            "weighted_sssp", "cc", "residual_pagerank"}:
        raise ValueError("expected all eleven declared current stage controls")
    for row in rows:
        if not math.isclose(row["current_ms"] / row["public_ms"], row["current_over_public"]):
            raise ValueError("elapsed times and replayed ratio disagree")
    scope = dict(status="REPLAYED_CURRENT_STAGE_CONTROLS", rows=len(rows),
                 criterion="current/public <= 1.15, not absolute +/-15% parity",
                 publication_throughput_reproduced=False, convergence_measured=False,
                 boundary="resident update-CU span (G); resident adapter+R superstep span (R)",
                 clock_note="ResPR both arms at 140/500/430 MHz; nominal route timing failed",
                 excluded_large_evidence="graphs, state arrays, binaries and large reports indexed by hash",
                 inputs=[identity(path) for path in (sssp_path, cc_path, respr_g, respr_r)],
                 artifact_index=list(index.values()))
    return rows, members, scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sssp-matrix", "cc-anchor", "respr-g", "respr-r", "respr-route", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    rows, members, scope = collect(args.sssp_matrix, args.cc_anchor, args.respr_g,
                                    args.respr_r, args.respr_route)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "gr_controls.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "gr_scope.json").write_text(json.dumps(scope, indent=2) + "\n")
    with (args.output / "gr_receipts.tar.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for name, content in sorted(members.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))


if __name__ == "__main__":
    main()
