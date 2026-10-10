"""Package raw diagnostics and conservative summaries without touching figures."""

from __future__ import annotations

import json
from pathlib import Path
import statistics
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .analysis import analyze_log
from .execution import identity
from .synthesis import read_report


CASES = {"SSSP": "au_sssp", "CC": "au_cc", "ResPR": "au_respr"}


def package(data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "results.json"
    if report_path.exists() or (output / "raw_diagnostic.tar.gz").exists():
        raise FileExistsError("delivery exists; refuse to rewrite frozen evidence")
    files = {}
    studies = {}
    for algorithm, folder in CASES.items():
        directory = data / folder
        frozen = json.loads((directory / "summary.json").read_text())
        if frozen["status"] != "PASS" or not all(frozen["checks"].values()):
            raise ValueError("paired hardware study did not pass")
        manifest = json.loads((directory / "manifest.json").read_text())
        medians = {}
        traces = []
        for attempt in frozen["attempts"]:
            name = f'r{attempt["repeat"]}_{attempt["arm"]}'
            run = directory / name
            raw = analyze_log((run / "run.log").read_text(),
                              require_trace=attempt["arm"] == "trace_enabled")
            if identity(run / "result.txt") != attempt["result"]:
                raise ValueError("raw result file no longer matches frozen identity")
            medians.setdefault(attempt["arm"], []).append(raw["timing_ms"]["setup_inclusive_ms"])
            if attempt["arm"] == "trace_enabled":
                traces.append(raw)
        studies[algorithm] = {
            "case": manifest["case"], "input_identities": manifest["inputs"],
            "checks": frozen["checks"], "runs": len(frozen["attempts"]),
            "host_affinity": manifest["host_affinity"],
            "peak_rss_mib": max(a["resources"]["peak_rss_kib"] for a in frozen["attempts"]) / 1024,
            "median_setup_inclusive_ms": {arm: statistics.median(values) for arm, values in medians.items()},
            "median_compute_span_ms": statistics.median(t["compute_span_ms"] for t in traces),
            "median_adapter_after_gather_union_ms": statistics.median(t["adapter_after_gather_union_ms"] for t in traces),
            "median_stage_metrics": {stage: {key: statistics.median(t["stages"][stage][key] for t in traces)
                                             for key in ("union_ms", "sum_ms", "max_concurrency")}
                                     for stage in traces[0]["stages"]},
            "trace_events": traces,
        }
        for path in directory.rglob("*"):
            if path.is_file() and (path.name != "result.txt" or path.parent.name == "r0_baseline"):
                files[str(path.relative_to(data))] = path
    synthesis = json.loads((data / "ablations/summary.json").read_text())
    if synthesis["status"] != "HLS_PASS_NOT_ROUTED":
        raise ValueError("synthesis ablations incomplete")
    synthesis["raw_summary_identity"] = identity(data / "ablations/summary.json")
    for name, run in synthesis["runs"].items():
        run["delivery_report_analysis"] = read_report(data / "ablations" / name)
    for path in (data / "ablations").rglob("*"):
        if path.is_file() and (path.suffix in (".json", ".txt") or path.name.endswith("csynth.xml") or path.name == "burst.xml"):
            if "build" not in path.parts or path.name.endswith("csynth.xml") or path.name == "burst.xml":
                files[str(path.relative_to(data))] = path
    for name in ("all_host_check.stdout.txt", "all_host_check.stderr.txt", "all_host_check.resources.json",
                 "final_adapter_check.stdout.txt", "final_adapter_check.stderr.txt", "final_adapter_check.resources.json"):
        path = data / name
        files[name] = path
    for name in ("baseline_source.tar", "candidate_source.tar.gz"):
        files[name] = data / name
    result = {"status": "CURRENT_HARDWARE_DIAGNOSTIC_AND_CANDIDATE_HLS_PASS",
              "not_complete": ["optimized_routing_and_board_validation", "optimized_simulator_synchronization",
                               "matched_original_A4_vs_actual_K4", "original_publication_speed_match"],
              "studies": studies, "synthesis": synthesis,
              "raw_archive_scope": "all_27_logs_and_one_byte_identical_result_per_algorithm_plus_HLS_reports"}
    with tarfile.open(output / "raw_diagnostic.tar.gz", "w:gz") as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
    raw = {"archive": identity(output / "raw_diagnostic.tar.gz"),
           "files": [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]}
    atomic_write_json(output / "raw_index.json", raw)
    atomic_write_json(report_path, result)
    lines = ["# Current K4 Diagnostic Results", "",
             "This is a checkpoint, not completion of the revised comparison goal.", "",
             "## Unchanged Hardware", "",
             "All 27 runs pass the CPU oracle, result-byte equality, identical round/state",
             "semantics and before/after input/bitstream hash checks. Each algorithm uses",
             "three repetitions of baseline, trace-disabled and trace-enabled hosts.", "",
             "| Algorithm | Baseline ms | Trace disabled ms | Trace enabled ms | Compute span ms | Adapter-after-gather union ms | Peak RSS MiB |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for algorithm, study in studies.items():
        values = study["median_setup_inclusive_ms"]
        lines.append(f'| {algorithm} | {values["baseline"]:.3f} | {values["trace_disabled"]:.3f} | '
                     f'{values["trace_enabled"]:.3f} | {study["median_compute_span_ms"]:.3f} | '
                     f'{study["median_adapter_after_gather_union_ms"]:.3f} | {study["peak_rss_mib"]:.1f} |')
    lines += ["", "These are current G+R measurements, not speedups against original A4.",
              "Times are medians; result bytes and convergence counts, not noisy elapsed",
              "time, are required to match exactly. CPU affinity is fixed to 120,121.", "",
              "## What Was Found", "",
              "The original source loop traverses all source rows even after sending the",
              "stream's last packet. In the first traced SSSP round, shard 0 gather ends",
              "about 81 ms after round enqueue, while its adapter ends around 512 ms.",
              "This is consistent with the visible trailing-row walk. Next-shard adapter",
              "launches wait for the previous adapter on the same frontend, so such tails",
              "can delay subsequent shards. Four adapter and gather events overlap, while",
              "mux/apply/HBM each have peak concurrency one, matching the intended topology.", "",
              "An adapter-after-gather interval is not an exclusive AXI-stall measurement",
              "and cannot simply be subtracted from total time to promise a speedup.",
              "Existing counters still cannot partition all internal memory/backpressure",
              "causes. The source code plus schedule motivate two separate candidates:",
              "stop when the known final packet is sent, and prefetch eight contiguous rows.", "",
              "## Candidate Gates", "",
              "The original path remains the default. Both candidate flags are off unless",
              "explicitly enabled. The candidate uses the existing aligned, monotonic row",
              "ABI; no sparse-source index or update maintenance is assumed free.",
              "Weighted, destination-only and unit-weight source tests each check 243",
              "cases and 1,464 packets against the baseline, including first/last-source",
              "placement, empty rows, 8-row tails, capacity clipping and cold/stale banks.", "",
              "| HLS variant | LUT | FF | BRAM_18K | Estimated clock ns |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for name, run in synthesis["runs"].items():
        r = run["analysis"]["resources"]
        lines.append(f'| {name} | {r["LUT"]} | {r["FF"]} | {r["BRAM_18K"]} | {run["analysis"]["estimated_clock_ns"]:.3f} |')
    lines += ["", "These are 150-MHz U55C Vitis 2024.1 adapter compile results, not routed",
              "frequency or board performance. Continuous row reads are inferred for",
              "both the original and prefetch paths. Prefetch changes the local scheduling;",
              "automatic widening is refused due to the 8-byte alignment",
              "type information. Do not claim a single 512-bit directory transaction or",
              "an eightfold traffic reduction from this candidate.", "",
              "## Remaining Work", "",
              "Route and validate the selected candidate against the frozen bitstream;",
              "only then synchronize/admit the simulator model and collect matched A4/K4",
              "results. FullPR arithmetic/state/round matching is still a prerequisite",
              "for the original-ReGraph comparison. The production FullPR host has three",
              "rounds, whereas the existing original-A4 control has one PR iteration.", "",
              "The old finite PMA+A4 74--791x prediction remains a different control.",
              "No optimized FPGA speedup or publication ~10% match has been established.", "",
              "## Evidence", "",
              "[Machine-readable results](results.json), [raw file/hash index](raw_index.json),",
              "[raw logs, canonical results and HLS reports](raw_diagnostic.tar.gz).",
              "The full local run tree and XOs are under", f"`{data}`.",
              "Bitstream binaries are indexed by immutable SHA-256, not copied into Git.", ""]
    (output / "RESULTS.md").write_text("\n".join(lines))
    return result
