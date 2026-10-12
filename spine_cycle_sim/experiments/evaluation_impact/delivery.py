"""Package immutable diagnostic reports without promoting a baseline."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import summarize


def load_completed(g_path, r_path):
    g = json.loads(g_path.read_text())
    r = json.loads(r_path.read_text())
    if g["status"] != "MATCHED_G_DIAGNOSTIC_COMPLETE_NOT_TIMING_ADMISSION":
        raise ValueError("complete matched-G report required")
    if r["status"] != "DIAGNOSTIC_COMPLETE_BASELINE_PERFORMANCE_GATES_OPEN":
        raise ValueError("complete R convergence report required")
    expected = {(latency, count, arm) for latency in (64, 128)
                for count in (0, 64, 4096) for arm in ("original", "current")}
    identities = [(row["latency"], row["updates"], row["observation"]["arm"]) for row in g["rows"]]
    if len(identities) != len(expected) or set(identities) != expected:
        raise ValueError("complete matched-G matrix required")
    for latency in (64, 128):
        for count in (0, 64, 4096):
            pair = [row for row in g["rows"] if (row["latency"], row["updates"]) == (latency, count)]
            if any(row["observation"]["state_pass"] is not True for row in pair):
                raise ValueError("G state gate failed")
            if pair[0]["state_sha256"] != pair[1]["state_sha256"]:
                raise ValueError("G states differ")
    if summarize(r["r_rows"]) != r["r"] or r.get("pins_unchanged") is not True:
        raise ValueError("R acceptance report differs from observations")
    return g, r


def source_reference(path, required):
    lines = path.read_text().splitlines()
    if any(not any(token in line for line in lines) for token in required):
        raise ValueError("missing inspected source/compile condition: " + str(path))
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size,
            "excerpts": [{"line": index + 1, "text": line.strip()}
                         for index, line in enumerate(lines) if any(token in line for token in required)]}


def package(output, g_path, r_path, failed_path, integration, hls_build):
    g, r = load_completed(g_path, r_path)
    failed = json.loads(failed_path.read_text())
    if failed["status"] != "FAILED_RETAINED":
        raise ValueError("retained failed attempt required")
    for report in (g, r):
        if any(sha256_file(Path(pin["path"])) != pin["sha256"] for pin in report["pins"]):
            raise ValueError("frozen source/input/binary identity changed before packaging")
    source = integration / "repos/GraSU/GraSU/GraSU_kernels/src"
    references = [
        source_reference(source / "kernel_bin_search.cpp", ("bin_search_direct", "GRASU_COMPACT_HBM_PORTS")),
        source_reference(source / "kernel_process_cache.cpp", ("process_cache_direct", "GRASU_PURE_PIPELINE_DIRECT_CACHE")),
        source_reference(hls_build / "logs/bin_search/bin_search/bin_search_vitis_hls.log", ("GRASU_COMPACT_HBM_PORTS",)),
        source_reference(hls_build / "logs/process_cache/process_cache/process_cache_vitis_hls.log", ("GRASU_PURE_PIPELINE_DIRECT_CACHE",)),
    ]
    output.mkdir(parents=True, exist_ok=False)
    capsules = []
    for name, path in (("matched_g.json", g_path), ("r_convergence.json", r_path), ("failed_attempt_v1.json", failed_path)):
        target = output / name
        shutil.copyfile(path, target)
        capsules.append({"file": name, "source": str(path), "sha256": sha256_file(target), "bytes": target.stat().st_size})
    # Empty-batch startup is retained, but is not an update-throughput sample.
    comparisons = []
    for latency in (64, 128):
        for count in (64, 4096):
            values = {row["observation"]["arm"]: row["observation"] for row in g["rows"]
                      if row["latency"] == latency and row["updates"] == count}
            comparisons.append({"latency": latency, "updates": count,
                                "current_over_original": values["current"]["cycles"] / values["original"]["cycles"],
                                "cycles": {arm: value["cycles"] for arm, value in values.items()}})
    index = {"status": "DIAGNOSTIC_CHECKPOINT_NOT_BASELINE_ADMISSION", "reports": capsules,
             "g_source_references": references, "g_nonempty_comparisons": comparisons,
             "g_ten_percent_prediction_target_met": all(0.9 <= row["current_over_original"] <= 1.1 for row in comparisons),
             "r": r["r"], "baseline_admitted": False, "publication_match_admitted": False,
             "new_spine_comparison_executed": False,
             "limitations": ["G original-source16 and paper8 are distinct; neither timing model is publication-calibrated",
                             "G diagnostic uses one destination window, not the complete 23-channel production layout",
                             "R endpoint, source-state bank, replica and parent-credit budgets are not strictly equal",
                             "R is warm compute-only SSSP; G, host and seed preparation are excluded on every arm",
                             "Candidate is not a routed FPGA measurement or a promoted production plugin"]}
    atomic_write_json(output / "index.json", index)
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "g", "r", "failed", "integration", "hls-build"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    index = package(args.output.resolve(), args.g.resolve(), args.r.resolve(), args.failed.resolve(),
                    args.integration.resolve(), args.hls_build.resolve())
    print(json.dumps({"status": index["status"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
