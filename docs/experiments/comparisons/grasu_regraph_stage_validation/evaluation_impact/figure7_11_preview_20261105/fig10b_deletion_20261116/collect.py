"""Collect the frozen Fig. 10(b) software inputs and validated AU CC board logs."""

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path


RATIOS = (0, 25, 50, 75, 100)
SYSTEMS = ("ligra_I", "ligra_R", "gunrock_I", "gunrock_R")
IDENTITY = ("graph_sha256", "batch_sha256", "before_state_sha256", "after_state_sha256")
COUNTERS = ("rounds", "reset", "affected", "changed", "relax_edges", "admission_discovery_ms",
            "maintenance_ms", "reset_cleanup_ms", "relaxation_ms", "upload_ms")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def record(lines, name):
    (line,) = (line for line in lines if line.startswith(f"{name} "))
    return dict(pair.split("=", 1) for pair in line.split()[1:])


def board_result(board, output, pct, expected_changed):
    log = board / f"{pct}.retry.board.log"
    status = board / f"{pct}.retry.exit"
    if not status.is_file():
        return {"board_status": "NOT_MEASURED"}
    for path in (log, status, board / f"{pct}.retry.command"):
        if path.is_file():
            shutil.copyfile(path, output / "raw" / path.name)
    code = status.read_text().strip()
    if code != "0":
        return {"board_status": "SKIPPED_RESOURCE_CHECK" if code == "75" else "FAILED",
                "board_log": f"raw/{log.name}"}
    lines = log.read_text().splitlines()
    wall = record(lines, "CC_RESIDENT_WALL")
    detail = record(lines, "CC_UPDATE_PASS")
    passed = record(lines, "CC_REPAIR_PASS")
    expected = {"logical_deletions": 512 * pct // 100, "physical_records": 1024,
                "changed": expected_changed}
    expected["logical_insertions"] = 512 - expected["logical_deletions"]
    if any(int(detail[key]) != value for key, value in expected.items()):
        raise ValueError(f"wrong AU CC batch/counters at {pct}%: {detail}")
    if any(passed[key] != "1" for key in ("all_raw_labels_checked", "all_raw_graphs_checked",
                                          "all_round_work_checked", "updates")):
        raise ValueError(f"missing AU CC oracle checks at {pct}%")
    return {
        "board_status": "PASS", "board_log": f"raw/{log.name}",
        "board_host_pack_to_readback_ms": wall["host_pack_to_final_readback_ms"],
        "board_batch_resident_to_readback_ms": wall["batch_resident_to_final_readback_ms"],
        "board_path": {"1": "component_local_deletion", "2": "warm_insertion",
                       "4": "mixed_full_fallback"}[detail["kind"]],
        **{f"board_{key}": detail[key] for key in COUNTERS},
    }


def au_rows(frozen, reference, metadata, output):
    board = frozen / "board"
    ref = {row["deletion_pct"]: row for row in json.loads(reference.read_text()) if row["algorithm"] == "cc"}
    followup = [row for row in read_csv(metadata / "followup_latency_pair_index.csv")
                if row["case"] in ("C_AU_cc_I_512", "C_AU_cc_R_512")]
    zero = board / "frozen0"
    manifest = json.loads((zero / "inputs/AU_cc_u512/manifest.json").read_text())
    files = manifest["files"]
    file_keys = ("base.bin", "batch.txt", "oracle.before", "oracle.after")
    csv_keys = ("graph_sha256", "batch_sha256", "oracle_before_sha256", "oracle_after_sha256")
    zero_id = tuple(files[key] for key in file_keys)
    if len(followup) != 2 or any(tuple(r[k] for k in csv_keys) != zero_id for r in followup):
        raise ValueError("AU 0% provenance mismatch")
    shutil.copyfile(board / "build.sha256", output / "raw/build.sha256")
    shutil.copyfile(board / "100.board.log", output / "raw/100.8g-allocation-failed.log")
    for pct in RATIOS:
        if pct == 0:
            identity = dict(zip(IDENTITY, zero_id))
            changed = manifest["reference"]["changed_vertices"]
            batch = zero / "batch.txt"
            medians = {f"{system}_{r['mode']}": r[f"{system}_wall_median_ms"]
                       for r in followup for system in ("ligra", "gunrock")}
            graph_format = "board_reference_base_bin"
        else:
            r = ref[pct]
            identity = {key: r[key] for key in IDENTITY}
            changed = r["vertices_changed"]
            path = frozen / "cc"
            batch = path / f"delete{pct}_u512_k0.txt"
            generated = json.loads((path / f"delete{pct}.json").read_text())
            old = json.loads((path / "before.json").read_text())
            if (sha(board / "canonical.txt") != r["graph_sha256"] or
                    old["sha256_uncompressed_little_endian"] != r["before_state_sha256"] or
                    generated["sha256_uncompressed_little_endian"] != r["after_state_sha256"]):
                raise ValueError(f"AU CC state provenance mismatch at {pct}%")
            medians = {system: r["samples"][system]["median_wall_ms"] for system in SYSTEMS}
            graph_format = "unit_weight_reciprocal_edge_text"
        if sha(batch) != identity["batch_sha256"]:
            raise ValueError(f"AU CC signed input mismatch at {pct}%")
        shutil.copyfile(batch, output / "raw" / f"au_cc_{pct}.updates.txt")
        yield {
            "graph": "AU", "algorithm": "CC", "batch_size": 512, "deletion_pct": pct,
            "sssp_source": "", "graph_hash_format": graph_format, **identity, "oracle_changed": changed,
            **{f"{system}_median_ms": ms for system, ms in medians.items()},
            **board_result(board, output, pct, changed),
        }


def lj08_rows(metadata):
    rows = read_csv(metadata / "lj_sssp_fraction_summary.csv")
    csv_keys = ("graph_sha256", "batch_sha256", "oracle_before_sha256", "oracle_after_sha256")
    for pct in RATIOS:
        points = [r for r in rows if r["graph"] == "LJ08" and int(r["deletion_pct"]) == pct]
        (keys,) = {tuple(r[k] for k in csv_keys) for r in points}
        (source,) = {r["source"] for r in points}
        medians = {f"{r['framework']}_{r['mode']}_median_ms": r["wall_median_ms"] for r in points}
        if len(points) != len(SYSTEMS) or source != "26":
            raise ValueError(f"unexpected LJ08 reference rows at {pct}%")
        yield {
            "graph": "LJ08", "algorithm": "SSSP", "batch_size": 512, "deletion_pct": pct,
            "sssp_source": source, "graph_hash_format": "board_reference_base_bin",
            **dict(zip(IDENTITY, keys)), **medians, "board_status": "MISSING_SHARED_INPUT_AND_IMAGE",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen", type=Path, help="fig10b-au-cc-frozen runtime directory")
    parser.add_argument("reference", type=Path, help="cpu-gpu-deletion-sweep.json")
    parser.add_argument("metadata", type=Path, help="paper e15_trifoliate_cpu_gpu_20261115 directory")
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    (output / "raw").mkdir(exist_ok=True)
    rows = [*au_rows(args.frozen, args.reference, args.metadata, output), *lj08_rows(args.metadata)]
    columns = ["graph", "algorithm", "batch_size", "deletion_pct", "sssp_source", "board_status",
               "board_path", "board_host_pack_to_readback_ms", "board_batch_resident_to_readback_ms",
               *[f"{system}_median_ms" for system in SYSTEMS], "oracle_changed",
               *[f"board_{key}" for key in COUNTERS], "graph_hash_format", *IDENTITY, "board_log"]
    with (output / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
