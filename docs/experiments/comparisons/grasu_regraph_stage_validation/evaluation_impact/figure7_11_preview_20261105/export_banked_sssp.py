"""Export only the finished banked-source-burst weighted-SSSP FPGA matrix."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import tarfile
from pathlib import Path

DATASETS = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
ALGORITHM = "weighted_sssp"
BOUNDARY = "resident_update_to_final_readback_wall_including_host_relaunch"
MEASURED = "MEASURED_RESIDENT_PAIR"
GR_IMAGE = "2c01a79c3229ef6af7dcb45661a173c05de9b78d973517b11e5923d63a273784"
SPINE_IMAGE = "2000ded183adffce4880792a3edcefa82eb462c460777fd536602397a77cf5dd"
BOARD = "0000:82:00.1"
CLOCKS = [150, 500, 450, 0]


def checked(pin):
    content = Path(pin["path"]).read_bytes()
    if len(content) != pin["bytes"] or hashlib.sha256(content).hexdigest() != pin["sha256"]:
        raise ValueError(f"receipt changed: {pin['path']}")
    return content


def check_control(control, max_ratio=1.15, min_ratio=0):
    comparison = control["comparison"]
    ratio = comparison.get("candidate_over_reference", comparison.get("current_over_reference"))
    if comparison["retention_gate_pass"] is not True or not min_ratio < ratio <= max_ratio:
        raise ValueError("G/R retention gate was not passed")
    clock = control["candidate_clock"]
    if (clock["binary"]["sha256"], clock["bdf"], clock["driver_reported_mhz"]) != (
            GR_IMAGE, BOARD, CLOCKS):
        raise ValueError("stage control did not use the matrix baseline")


def collect(matrix_bytes):
    matrix = json.loads(matrix_bytes)
    if ((matrix["status"], matrix["repetitions_per_arm"], matrix["warmups"],
         matrix["require_au_topology"]) != ("MEASURED_SSSP_MATRIX", 1, 0, True)
            or set(matrix["cases"]) != set(DATASETS[1:])):
        raise ValueError("need the complete banked SSSP matrix plus the separate AU pair")
    gate = matrix["baseline"]
    if (gate["status"], gate["algorithm"], gate["image"]["sha256"]) != (
            "BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE", ALGORITHM, GR_IMAGE):
        raise ValueError("unexpected admitted G+R image")
    check_control(gate["g"])
    for control in (gate["r"], matrix["odd_r"], matrix["au_slice_r"]):
        check_control(control, min_ratio=0.85)

    rows, members = [], {"matrix.json": matrix_bytes}
    for dataset in DATASETS:
        case = matrix["cases"].get(dataset)
        pin = matrix["au_result"] if case is None else case["result"]
        if case is not None and case["status"] != MEASURED:
            raise ValueError(f"{dataset}: case not admitted")
        raw = checked(pin)
        receipt = json.loads(raw)
        if ((receipt["status"], receipt["algorithm"], receipt["dataset"], receipt["boundary"],
             receipt["bdf"], receipt["repetitions_per_arm"], receipt["warmups"], receipt["attempts"])
            != (MEASURED, ALGORITHM, dataset, BOUNDARY, BOARD, 1, 0, ["spine", "gr"])
                or receipt["stage_gates"] != gate):
            raise ValueError(f"{dataset}: changed scope or baseline")
        logs = {"results.json": raw, "pair.json": checked(receipt["comparison_log"])}
        for arm, image in (("spine", SPINE_IMAGE), ("gr", GR_IMAGE)):
            details = receipt["arms"][arm]
            clock = details["clock"]
            if (clock["binary"]["sha256"], clock["bdf"], clock["driver_reported_mhz"]) != (
                    image, BOARD, CLOCKS):
                raise ValueError(f"{dataset}: clock or {arm} image mismatch")
            logs[f"{arm}.clock-raw.json"] = checked(clock["raw"])
            for stream in ("stdout", "stderr"):
                logs[f"{arm}.{stream}.txt"] = checked(details[stream])
        pair = json.loads(logs["pair.json"])
        gr, spine = pair["gr_wall_ms"], pair["spine_wall_ms"]
        if (pair != receipt["pair"] or (pair["algorithm"], pair["boundary"]) != (ALGORITHM, BOUNDARY)
                or (pair["logical_updates"], pair["physical_updates"]) != (8, 8)
                or min(pair["spine_rounds"], pair["gr_rounds"]) < 1
                or not all(math.isfinite(value) and value > 0 for value in (gr, spine))
                or not math.isclose(pair["speedup_gr_over_spine"], gr / spine)):
            raise ValueError(f"{dataset}: invalid resident pair")
        rows.append(dict(dataset=dataset, status=MEASURED, **pair, receipt_sha256=pin["sha256"]))
        members.update({f"{dataset}/{name}": data for name, data in logs.items()})
    return rows, members


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows, members = collect(args.matrix.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "fig7_sssp_banked.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with (args.output / "fig7_sssp_banked_receipts.tar.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for name, content in sorted(members.items()):
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))


if __name__ == "__main__":
    main()
