"""Package the fixed pilot, including unsuccessful development hypotheses."""

import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

from ...original_regraph_execution.hardware.source_retention.runtime import identity, save
from . import analysis

ROOT = Path(__file__).resolve().parents[4]
CHANGED = ("cpp/sst/online_memory_probe.cpp", "scripts/run_sst_spine_vertical.py",
           "sst/spine_vertical_slice.py", "tests/test_fpga_cycle_validation.py")
ARCHIVE = "fpga_cycle_validation_data_code.zip"


def regression(runs):
    baseline = json.loads((runs / "sim-dev-batch/results.json").read_text())
    current = json.loads((runs / "sim-zero-regression/results.json").read_text())
    if baseline["status"] != "COMPLETE" or current["status"] != "COMPLETE":
        raise ValueError("incomplete zero-override regression")
    old = {row["name"]: row for row in baseline["rows"]}
    new = {row["name"]: row for row in current["rows"]}
    if old.keys() != new.keys():
        raise ValueError("zero-override case mismatch")
    rows = []
    for name, row in old.items():
        before = json.loads(Path(row["result_path"]).read_text())
        after = json.loads(Path(new[name]["result_path"]).read_text())
        if before != after:
            raise ValueError(f"default behavior changed: {name}")
        rows.append(dict(case=name, status="EXACT_ALL_RESULT_FIELDS", fields=len(before),
                         baseline=identity(row["result_path"]), current=identity(new[name]["result_path"])))
    return dict(status="PASS", rows=rows)


def build(runs, output, host_source):
    runs, output = runs.resolve(), output.resolve()
    default_check = regression(runs)
    output.mkdir(parents=True, exist_ok=False)
    excluded = shutil.ignore_patterns("*.so", "*.host", "__pycache__", "*.pyc")
    for path in sorted(runs.iterdir()):
        if path.is_dir() and path.name not in ("reader-transport-plugin", "transport-plugin"):
            shutil.copytree(path, output / "raw" / path.name, ignore=excluded)
    shutil.copytree(runs / "analysis-reader-final", output / "data")
    save(output / "zero_override_regression.json", default_check)
    source = output / "code"
    for relative in CHANGED:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    module = Path(__file__).parent.relative_to(ROOT)
    shutil.copytree(ROOT / module, source / module, ignore=excluded)
    base = Path("configs/architectures/spine_owner_fifo_sssp_hls_v1.json")
    (source / base).parent.mkdir(parents=True)
    shutil.copy2(ROOT / base, source / base)
    production = host_source.read_text().splitlines(keepends=True)
    diagnostic = (runs / "diagnostic-host/host.cpp").read_text().splitlines(keepends=True)
    (output / "diagnostic_host.patch").write_text("".join(difflib.unified_diff(
        production, diagnostic, fromfile=str(host_source), tofile="diagnostic-host/host.cpp")))
    (output / "simulator_changes.patch").write_bytes(subprocess.check_output(
        ["git", "diff", "--binary", "HEAD", "--", *CHANGED[:3]], cwd=ROOT))
    save(output / "provenance.json", dict(
        source_base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        original_run_root=str(runs),
        status="PASS_LIMITED_SSSP_PILOT",
        actual_image_authority="raw/board-dev-diagnostic/results.json and raw/board-holdout/results.json",
        inherited_profile_warning="Base profile contains historical HLS/image anchors; these are not the measured image identity. Use the board receipts above.",
        plugins=[identity(runs / name / "build/libspine_cycle.so")
                 for name in ("reader-transport-plugin", "transport-plugin")],
        diagnostic_host=identity(runs / "diagnostic-host/weighted_sssp.host"),
        diagnostic_host_source=identity(runs / "diagnostic-host/host.cpp"),
        production_host_source=identity(host_source),
        compiler=subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
        simulator_build_command="make -C cpp/sst BUILD_DIR=<fresh-dir> (default -O3 -DNDEBUG -flto, C++20)",
        host_build_receipt="Diagnostic source and binary hash retained; original diagnostic compilation command was not saved.",
        hypotheses=[
            dict(name="baseline", scope="development", path="raw/sim-dev-batch/results.json"),
            dict(name="all-port delay", scope="failed development diagnostic; never used on holdout",
                 path="raw/sim-transport-development/results.json"),
            dict(name="reader-only delay", scope="frozen before holdout prediction/comparison",
                 path="raw/frozen-reader-transport/freeze.json")]))
    replay = analysis.pair(
        [output / "raw" / name / "results.json" for name in ("board-dev-diagnostic", "board-holdout")],
        [output / "raw" / name / "results.json" for name in
         ("sim-reader-transport-development", "sim-reader-transport-holdout")],
        (runs, output / "raw"))
    selected = json.loads((output / "data/summary.json").read_text())["all_rows"]
    numeric = ("case", "split", "fpga_cycles", "simulator_cycles", "abs_error_percent", "work_match")
    if [[row[key] for key in numeric] for row in replay] != [[row[key] for key in numeric] for row in selected]:
        raise ValueError("archived replay does not reproduce the selected values")


def archive(folder):
    files = [path for path in sorted(folder.rglob("*"))
             if path.is_file() and path.name not in (ARCHIVE, "manifest.json")]
    save(folder / "manifest.json", dict(files=[dict(
        path=str(path.relative_to(folder)), sha256=identity(path)["sha256"],
        bytes=path.stat().st_size) for path in files]))
    with ZipFile(folder / ARCHIVE, "w", compression=ZIP_DEFLATED) as bundle:
        for path in [*files, folder / "manifest.json"]:
            bundle.write(path, path.relative_to(folder))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    command = sub.add_parser("build")
    for key in ("runs", "output", "host-source"):
        command.add_argument("--" + key, type=Path, required=True)
    sub.add_parser("archive").add_argument("--folder", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "build":
        build(args.runs, args.output, args.host_source)
    else:
        archive(args.folder.resolve())
