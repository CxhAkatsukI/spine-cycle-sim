"""Package the complete source controls, retained attempts and queued HLS status."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import analyze, parse
from .rtl_analysis import parse_bench
from .synthesis import unchanged


def package(output, matrix, hls, retained, freeze):
    report_path = matrix / "results.json"
    report = json.loads(report_path.read_text())
    if report["status"] != "FINITE_HLS_SOURCE_PASS_NOT_RTL_TIMING":
        raise ValueError("complete source-control matrix required")
    unchanged(report["source"] + report["dependencies"])
    previous = Path(report["previous"]["path"])
    if sha256_file(previous) != report["previous"]["sha256"]:
        raise ValueError("candidate model reference changed")
    summary = analyze(report, json.loads(previous.read_text()))
    if summary != report["analysis"]:
        raise ValueError("stored source-control summary differs")
    for row in report["rows"]:
        actual = parse(Path(row["execution"]["stdout"]).read_text(), row["updates"], row["mode"])
        if actual != row["control"]:
            raise ValueError("source-control stdout changed")
    for key in ("rtl_bench_compile", "rtl_bench_execution"):
        if report[key]["exit_code"] or report[key]["timed_out"]:
            raise ValueError("C++14 testbench source check did not complete")
    bench = parse_bench(Path(report["rtl_bench_execution"]["stdout"]).read_text())
    if bench != report["rtl_bench_source"]:
        raise ValueError("C++14 testbench source stdout changed")
    hls_path = hls / "results.json"
    queued = json.loads(hls_path.read_text())
    if queued["basis"]["sha256"] != sha256_file(report_path) or any(
            queued.get(key) is not False for key in (
                "hardware_timing_admitted", "production_baseline_admitted", "publication_match_admitted")):
        raise ValueError("HLS attempt does not retain this control identity and evidence boundary")
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for name, path in (("matrix.json", report_path), ("previous_metadata.json", previous),
                       ("hls_snapshot.json", hls_path)):
        shutil.copy2(path, output / name)
        files.append({"file": name, "source": str(path), "sha256": sha256_file(output / name)})
    raw = []
    for label, folder in [("controls", matrix), *[(path.name, path) for path in retained]]:
        if label != "controls":
            path = folder / "results.json"
            raw.append((label + "/results.json", path))
        for path in sorted(folder.glob("*")):
            if path.is_file() and path.name.endswith((".stdout.txt", ".stderr.txt", ".resources.json", ".d")):
                raw.append((label + "/" + path.name, path))
    for name in ("source", "inputs"):
        for path in sorted((matrix / name).rglob("*")):
            if path.is_file(): raw.append(("controls/" + str(path.relative_to(matrix)), path))
    if len({name for name, _ in raw}) != len(raw):
        raise ValueError("duplicate raw capsule member")
    archive = output / "raw_controls.tar.gz"
    members = []
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in raw:
            handle.add(path, arcname=name, recursive=False)
            members.append({"member": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    files.append({"file": archive.name, "sha256": sha256_file(archive)})
    index = {"status": "SEARCH_SOURCE_CONTROLS_PASS_HLS_UNADMITTED", **summary,
        "reports": files, "raw_members": members,
        "rtl_bench_source": bench,
        "delivery_implementation": {"path": str(Path(__file__).resolve()),
                                    "sha256": sha256_file(Path(__file__))},
        "pre_edit_freeze": {"path": str(freeze), "sha256": sha256_file(freeze)},
        "hls_status_at_packaging": queued["status"], "hls_live_report": str(hls_path),
        "hardware_timing_admitted": False, "production_baseline_admitted": False,
        "publication_match_admitted": False, "new_spine_comparison_executed": False,
        "core_or_sst_numerical_code_changed": False,
        "maximum_control_process_rss_kib": max(row["execution"]["peak_rss_kib"] for row in report["rows"]),
        "output_stall_rows_with_observed_backpressure": sum(
            row["mode"] == "stalled" and any(cu["blocked_output_writes"] for cu in row["control"]["cu_controls"])
            for row in report["rows"])}
    atomic_write_json(output / "index.json", index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "matrix", "hls", "freeze"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--retained", type=Path, action="append", default=[])
    args = parser.parse_args()
    result = package(args.output, args.matrix, args.hls, args.retained, args.freeze)
    print(json.dumps({key: result[key] for key in ("status", "executions", "hls_status_at_packaging")}))
