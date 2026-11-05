"""Freeze the selected review checkpoint without copying historical alternatives."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


HANDOFF = Path("docs/experiments/comparisons/grasu_regraph_stage_validation/"
               "evaluation_impact/figure7_11_preview_20261105")
MODULE = Path("spine_cycle_sim/experiments/evaluation_impact/figure_refresh/review_bundle.py")
STYLE = Path("docs/evaluation_refresh_20260810/figure7_10_handoff_v1")
MANIFEST = HANDOFF / "current_review_manifest.json"
ARCHIVE = HANDOFF / "current_review.tar.gz"


def selected_paths():
    files = [HANDOFF / name for name in ("CURRENT.md", "render_review.py", "render.py", "render_current.py")]
    files += [MODULE, STYLE / "render_all.py", STYLE / "reference/GraphyFlow_Plot.zip"]
    current = HANDOFF / "current_fpga"
    files += [current / name for name in ("gr_controls.csv", "gr_scope.json", "gr_receipts.tar.gz")]
    resident = current / "resident_checkpoint_v2"
    files += [resident / name for name in ("fig7_resident_checkpoint.csv", "scope.json", "receipts.tar.gz")]
    fresh = HANDOFF / "fresh_simulator"
    files += [fresh / name for name in (
        "fig9_memory_energy_rows.csv", "fig9_arms.csv", "fig9_scope.json", "fig9_receipts.tar.gz",
        "fig10_normalized_breakdown_rows.csv", "fig10_stage_rows.csv", "fig10_11_scope.json",
        "fig10_11_receipts.tar.gz", "fig11_work_rows.csv", "fig11_e2e_prediction_rows.csv",
        "fig11_coverage_rows.csv", "fig11_e2e_model.json", "fig11_regression_rows.csv",
        "fig11_representative_rows.csv", "fig11_summary.json", "fig11_e2e_metric_rows.csv",
        "fig11_latency_rows.csv", "fresh_summary.json", "measurement_origins.json")]
    headroom = fresh / "portable_fig8_headroom_v1"
    files += [headroom / name for name in ("fig8_ten_batch.csv", "scope.json", "receipts.tar.gz",
        "batch_sweep/fig8_batch_sensitivity.csv", "batch_sweep/scope.json", "batch_sweep/receipts.tar.gz")]
    for directory, stems in (
        (current / "figures", ("gr_current_source_controls",)),
        (resident / "figures", ("fig7_resident_checkpoint",)),
        (headroom / "figures", ("fig8_update_prediction_headroom",)),
        (fresh / "figures", ("fig9_memory_hbm_prediction", "fig10_simulator_breakdown", "fig11_realized_work_model")),
    ):
        files += [directory / (stem + "." + suffix) for stem in stems for suffix in ("pdf", "png")]
    return sorted(files)


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or str(path) != name:
        raise ValueError("unsafe review member: " + name)
    return path


def checkpoint(root):
    def read(relative):
        return json.loads((root / HANDOFF / relative).read_bytes())

    scope = read("current_fpga/resident_checkpoint_v2/scope.json")
    with (root / HANDOFF / "current_fpga/resident_checkpoint_v2/fig7_resident_checkpoint.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    keys = {(row["algorithm"], row["dataset"]) for row in rows}
    expected = {(algorithm, dataset) for algorithm in ("weighted_sssp", "cc", "residual_pagerank")
                for dataset in ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")}
    if len(rows) != 24 or keys != expected or scope["expected_pairs"] != 24:
        raise ValueError("review must retain all twenty-four Fig. 7 slots")
    measured = [row for row in rows if row["status"] == "MEASURED"]
    for row in rows:
        fields = ("spine_wall_ms", "gr_wall_ms", "speedup_gr_over_spine")
        if row["status"] != "MEASURED":
            if any(row.get(field) for field in fields):
                raise ValueError("missing slot has timing data")
            continue
        spine, gr, ratio = (float(row[field]) for field in fields)
        if (not all(math.isfinite(value) and value > 0 for value in (spine, gr, ratio))
                or not math.isclose(gr / spine, ratio, rel_tol=1e-9)):
            raise ValueError("resident ratio disagrees with wall times")
    if scope["measured_pairs"] != len(measured):
        raise ValueError("resident measured count differs from scope")
    summary = read("fresh_simulator/fresh_summary.json")
    if summary["fpga_stage_calibrated"] is not False or summary["no_holdout_used_for_fit"] is not True:
        raise ValueError("stage/model evidence boundary changed")
    return dict(status="INCOMPLETE_REVIEW_CHECKPOINT", fpga_pairs=len(measured), expected_fpga_pairs=24,
                missing_fpga_pairs=24 - len(measured), complete=False,
                fpga_stage_calibrated=False, publication_throughput_reproduced=False,
                simulator_executions=summary["executions"],
                limitations=["Fig. 7 still lacks CC and LJ08 ResPR; no all-win matrix claim.",
                    "Fig. 8 is the same-host L4 prediction, including its 1000-batch loss; not routed G parity.",
                    "Fig. 9 uses modeled traffic/energy and zero-active ResPR, not measured board power.",
                    "Fig. 10 is simulator attribution; Fig. 11 predicts simulator output, not FPGA counters.",
                    "Historical losses and failed attempts remain documented; this is not a replacement for them."])


def verify_manifest(manifest, read):
    if manifest.get("schema") != 1 or manifest.get("selection") != "nov05-review-v1":
        raise ValueError("unsupported review selection")
    members = manifest["members"]
    names = [row["path"] for row in members]
    if len(names) != len(set(names)) or sorted(names) != [str(path) for path in selected_paths()]:
        raise ValueError("changed or duplicate review inventory")
    if (manifest["checkpoint"].get("complete") is not False
            or manifest["checkpoint"].get("status") != "INCOMPLETE_REVIEW_CHECKPOINT"):
        raise ValueError("checkpoint is not a completed evaluation")
    for row in members:
        safe_name(row["path"])
        blob = read(row["path"])
        if len(blob) != row["bytes"] or digest(blob) != row["sha256"]:
            raise ValueError("changed review member: " + row["path"])
    return manifest


def verify_files(root):
    def read(name):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("non-file review member: " + name)
        return path.read_bytes()

    manifest = json.loads(read(str(MANIFEST)))
    verify_manifest(manifest, read)
    if checkpoint(root) != manifest["checkpoint"]:
        raise ValueError("review checkpoint summary differs from selected data")
    return manifest


def verify_archive(path):
    with tarfile.open(path) as archive:
        names = archive.getnames()
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive members")
        for member in archive.getmembers():
            safe_name(member.name)
            if not member.isfile():
                raise ValueError("archive contains non-file member")

        def read(name):
            return archive.extractfile(archive.getmember(name)).read()

        manifest = json.loads(read(str(MANIFEST)))
        if set(names) != {str(MANIFEST), *(row["path"] for row in manifest["members"])}:
            raise ValueError("archive membership differs from manifest")
        return verify_manifest(manifest, read)


def build(root):
    destination, index = root / ARCHIVE, root / MANIFEST
    if destination.exists() or index.exists():
        raise FileExistsError("review archive/index already exist; do not rewrite a frozen package")
    members = []
    for relative in selected_paths():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing regular source: " + str(relative))
        blob = path.read_bytes()
        members.append(dict(path=str(relative), bytes=len(blob), sha256=digest(blob)))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True).stdout.strip()
    manifest = dict(schema=1, selection="nov05-review-v1", base_git_commit=head,
                    authority="Per-file hashes include the new uncommitted review entry; base commit is not their source pin.",
                    checkpoint=checkpoint(root), members=members,
                    external="Large graphs, state arrays, binaries and toolchains are hash-indexed in receipts, not embedded.")
    blob = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("ascii")
    with destination.open("xb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for name, payload in [(str(MANIFEST), blob), *[(row["path"], (root / row["path"]).read_bytes())
                                                            for row in members]]:
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    info.mode = 0o644
                    archive.addfile(info, io.BytesIO(payload))
    verify_archive(destination)
    index.write_bytes(blob)
    return verify_files(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--verify-archive", type=Path)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.verify_archive:
        if args.build or args.root:
            parser.error("archive verification is standalone")
        result = verify_archive(args.verify_archive)
    elif args.root:
        result = build(args.root) if args.build else verify_files(args.root)
    else:
        parser.error("supply --root or --verify-archive")
    print(json.dumps(result["checkpoint"], sort_keys=True))
