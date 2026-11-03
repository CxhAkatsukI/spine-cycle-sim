"""Verify a delivered data package without the original experiment paths."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.rq3 import TEN_STAGE_KEYS
from .delivery import read_csv


def verify_archive(path: Path, index: dict) -> int:
    if index.get("parts"):
        with tempfile.TemporaryDirectory() as temporary:
            joined = Path(temporary) / index["path"]
            with joined.open("wb") as target:
                for item in index["parts"]:
                    part = path.parent / item["path"]
                    if part.stat().st_size != item["bytes"] or sha256_file(part) != item["sha256"]:
                        raise ValueError(f"archive part changed: {part.name}")
                    with part.open("rb") as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            target.write(chunk)
            return verify_archive(joined, {key: value for key, value in index.items() if key != "parts"})
    if sha256_file(path) != index["sha256"]:
        raise ValueError(f"archive hash mismatch: {path.name}")
    expected = {member["path"]: member for member in index["members"]}
    if len(expected) != len(index["members"]):
        raise ValueError("duplicate indexed archive member")
    seen = set()
    with tarfile.open(path, "r:gz") as source:
        for member in source:
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise ValueError(f"unexpected archive member: {member.name}")
            seen.add(member.name)
            digest = hashlib.sha256()
            with source.extractfile(member) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            item = expected[member.name]
            if member.size != item["bytes"] or digest.hexdigest() != item["sha256"]:
                raise ValueError(f"archive member changed: {member.name}")
    if seen != set(expected):
        raise ValueError("missing archive members")
    return len(seen)


def verify_comparisons(output: Path) -> dict:
    cross = read_csv(output / "data/fig8_update_cross_dataset.csv")
    sweep = read_csv(output / "data/fig8_update_batch_sensitivity.csv")
    if len(cross) != 5 or len(sweep) != 3:
        raise ValueError("incomplete Figure 8")
    for row in cross + sweep:
        if int(row["batch_count"]) != 1:
            raise ValueError("Figure 8 is a one-batch measurement")
        ratio = float(row["spine_kups"]) / float(row["grasu_kups"])
        if abs(ratio / float(row["spine_speedup"]) - 1) > 1e-12:
            raise ValueError("Figure 8 throughput ratio changed")
    pairs = read_csv(output / "data/fig9_memory_energy_rows.csv")
    arms = read_csv(output / "data/fig9_arms.csv")
    indexed = {(r["algorithm"], r["dataset"], r["arm"]): r for r in arms}
    expected = {(algorithm, dataset) for algorithm in ("SSSP", "CC", "ResPR")
                for dataset in ("AU", "SU", "WK")}
    if len(pairs) != 9 or {(r["algorithm"], r["dataset"]) for r in pairs} != expected:
        raise ValueError("incomplete Figure 9 pairs")
    if len(arms) != 18 or len(indexed) != 18:
        raise ValueError("incomplete Figure 9 arms")
    for row in pairs:
        spine = indexed[row["algorithm"], row["dataset"], "spine"]
        gr = indexed[row["algorithm"], row["dataset"], "gr"]
        for arm, field in ((spine, "spine_memory_bytes"), (gr, "gr_memory_bytes")):
            if int(arm["read_bytes"]) + int(arm["write_bytes"]) != int(row[field]):
                raise ValueError("Figure 9 byte ledger changed")
        memory = int(row["gr_memory_bytes"]) / int(row["spine_memory_bytes"])
        energy = float(gr["total_energy_pj"]) / float(spine["total_energy_pj"])
        if any(abs(actual / float(row[key]) - 1) > 1e-12 for actual, key in (
            (memory, "memory_ratio_gr_over_spine"), (energy, "hbm_energy_ratio_gr_over_spine")
        )):
            raise ValueError("Figure 9 ratio changed")
    return {"fig8_cross_rows": len(cross), "fig8_sweep_rows": len(sweep), "fig9_pairs": len(pairs)}


def verify(output: Path, repository: Path | None = None) -> dict:
    manifest = json.loads((output / "manifest.json").read_text())
    actual = {str(p.relative_to(output)) for p in output.rglob("*")
              if p.is_file() and p.name != "manifest.json"}
    if actual != set(manifest["files"]):
        raise ValueError("manifest file set differs from delivery")
    for name, digest in manifest["files"].items():
        if sha256_file(output / name) != digest:
            raise ValueError(f"package hash mismatch: {name}")
    provenance = json.loads((output / "provenance/package.json").read_text())
    archive_keys = ["fig7_archive", "fig10_11_archive"]
    for key in ("failed_attempt_archive", "superseded_admission_archive"):
        if key in provenance:
            archive_keys.append(key)
    members = sum(verify_archive(output / "evidence" / provenance[key]["path"], provenance[key])
                  for key in archive_keys)
    if repository:
        for item in provenance["external_evidence"]:
            if sha256_file(repository / item["path"]) != item["sha256"]:
                raise ValueError(f"referenced evidence changed: {item['path']}")
    board = read_csv(output / "data/fig7_fpga_speedup.csv")
    if len(board) != 24 or len({(r["algorithm"], r["dataset"]) for r in board}) != 24:
        raise ValueError("incomplete Figure 7")
    for row in board:
        if row["status"] != "RESIDENT_PAIR_PASS" or abs(
            float(row["gr_wall_ms"]) / float(row["spine_wall_ms"])
            / float(row["speedup_gr_over_spine"]) - 1
        ) > 1e-12:
            raise ValueError("invalid Figure 7 ratio or admission")
    stages = read_csv(output / "data/fig10_stage_rows.csv")
    normalized = read_csv(output / "data/fig10_normalized_breakdown_rows.csv")
    if len(stages) != 11 or len(normalized) != 11:
        raise ValueError("incomplete Figure 10")
    for row, norm in zip(stages, normalized):
        if row["execution_id"] != norm["execution_id"]:
            raise ValueError("Figure 10 normalization reordered rows")
        if sum(int(row[key]) for key in TEN_STAGE_KEYS) != int(row["total_cycles"]):
            raise ValueError("Figure 10 stage ledger does not conserve cycles")
        percentages = [float(value) for key, value in norm.items() if key.endswith("_percent")]
        if len(percentages) != 5 or abs(sum(percentages) - 100) > 1e-8:
            raise ValueError("Figure 10 normalization does not sum to 100 percent")
    prediction = read_csv(output / "data/fig11_e2e_prediction_rows.csv")
    roles = Counter(row["role"] for row in prediction)
    if roles != {"synthetic_calibration": 18, "trace_calibration": 6, "trace_holdout": 17}:
        raise ValueError(f"Figure 11 split changed: {roles}")
    model = json.loads((output / "data/fig11_e2e_model.json").read_text())
    if not model["holdout_rows_are_never_used_for_fit"]:
        raise ValueError("holdout fitting is not excluded")
    return {"status": "PASS", "files": len(actual), "archive_members": members,
            **verify_comparisons(output),
            "fig7_pairs": len(board), "fig10_bars": len(stages),
            "fig11_rows": len(prediction), "external_evidence_checked": repository is not None}


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--repository", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.package.resolve(), args.repository), indent=2))


if __name__ == "__main__":
    main()
