"""Export the completed single-pass FPGA campaign without replacing old evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from . import analysis, render


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_report(run):
    report = json.loads((run / "results.json").read_text())
    if report["status"] not in ("COMPLETED", "COMPLETED_WITH_FAILURES"):
        raise ValueError("cannot deliver an unfinished campaign")
    if report["samples_per_arm"] != 1 or report["warmups"] != 0:
        raise ValueError("one sample per arm, without warmups, required")
    cases = report["cases"]
    expected = [(dataset, 4096, 10, "a") for dataset in ("AU", "SU", "WK", "SO", "PK")]
    expected += [("AU", 131072, count, "b") for count in (10, 100, 1000)]
    if [(c["dataset"], c["updates"], c["batches"], c["panel"]) for c in cases] != expected:
        raise ValueError("the complete declared matrix is required, including failures")
    for case in cases:
        if set(case["arms"]) != {"spine", "gr"}:
            raise ValueError("a declared arm was never attempted")
        for arm, result in case["arms"].items():
            for stream in ("stdout", "stderr"):
                receipt = result[stream]
                path = run / case["name"] / Path(receipt["path"]).name
                if checksum(path) != receipt["sha256"]:
                    raise ValueError("changed raw log: " + str(path))
            if result["status"] != "PASS":
                if case["status"] == "MEASURED":
                    raise ValueError("a failed arm cannot be a measured pair")
                continue
            observed = analysis.timing((run / case["name"] / f"{arm}.stdout.txt").read_text(), arm, case)
            if observed != result["timing"]:
                raise ValueError("raw timers differ from the journal")
            if arm == "gr" and int(observed["raw_summary"]["metadata_replicas"]) != report["metadata_replicas"]:
                raise ValueError("G metadata configuration changed within the matrix")
        if case["status"] == "MEASURED":
            arms = case["arms"]
            if arms["spine"]["clock"]["driver_reported_mhz"] != arms["gr"]["clock"]["driver_reported_mhz"]:
                raise ValueError("measured pair has different clocks")
            ratio = arms["gr"]["timing"]["setup_inclusive_ns"] / arms["spine"]["timing"]["setup_inclusive_ns"]
            if ratio != case["speedup"]:
                raise ValueError("speedup does not match the recorded timer sums")
    return report


def table(cases):
    rows = ["| Case | Spine, s | G update, s | G / Spine | Outcome |",
            "| --- | ---: | ---: | ---: | --- |"]
    for case in cases:
        def seconds(arm):
            timing = case["arms"][arm].get("timing")
            return f'{timing["setup_inclusive_ns"] / 1e9:.6f}' if timing else "FAIL"
        ratio = case.get("speedup")
        winner = ("Spine" if ratio >= 1 else "G") if ratio is not None else "Failed pair; retained"
        rows.append(f'| {case["name"]} | {seconds("spine")} | {seconds("gr")} | '
                    f'{f"{ratio:.3f}x" if ratio is not None else "--"} | {winner} |')
    return "\n".join(rows)


def readme(report):
    passed = sum(case["status"] == "MEASURED" for case in report["cases"])
    return f"""# Figure 8: One-Pass FPGA Update Throughput

November 7, 2026. **Real FPGA measurements**, {passed}/8 complete pairs.
One measured execution per arm per case, no warmup, repeats or averaging.
The paper and the frozen November 6 download are unchanged.

## Results

The ratio is G update time / Spine update time; above 1 favors Spine.
This is the maintenance-only part of G+R; ReGraph propagation is not run.

{table(report["cases"])}

Failed points are shown explicitly in the CSV and preview, not substituted
with simulator predictions. In particular, native Spine L2 reports graph
overflow during PK and AU 131K/10- and 100-batch maintenance. AU 131K/1,000
completes every batch but fails the final graph readback/oracle with an
out-of-range address. It is not an admitted timing point. These are not host
OOM events. No unresolved failure is claimed to be merely a layout issue;
the latter failure has a concrete compact-host/fixed-kernel layout mismatch:
17,829,908 is the kernel's fixed L10 bitmap base, beyond the allocated
3,694,361 words. This does not establish otherwise-correct device state.
Simply enlarging buffers can leave fixed carry destinations overlapping
live compact slices. The 10-batch trace also exceeds fixed L1 capacity
within one family, so changing bootstrap headroom alone is insufficient.
The native-wrapper README records the source locations and diagnosis.
See each arm's raw stdout/stderr for the last completed batch. Thus this
delivery does not yet contain a valid complete Fig. 8b curve.

## Measurement Window

- Panel a: original weighted AU/SU/WK/SO/PK traces, 4,096 total insertions
  divided chronologically into ten batches.
- Panel b: the same AU old graph and 131,072 insertions, divided into
  10/100/1,000 chronological batches. Labels show mean updates per batch.
- Initial native layout and graph upload are charged once. Each batch adds
  host packing, update DMA, kernel arguments/launch and completion wait.
  The graph stays device-resident throughout all batches.
- Parsing, image programming, validation/status readback, oracle work and
  logging are excluded from the summed timer. Mandatory Spine status checks
  still run between batches. This is not uninterrupted process wall time.
- No graph propagation or convergence is timed. The weighted update kernel
  is algorithm-independent for this insertion workload; these are not three
  different algorithm runs, nor a replacement for Fig. 7 latency.
- Both arms use identical original IDs, weights, order and batch boundaries.
  G explicitly reserves PMA from the future trace union and uses one shared
  metadata copy. Native Spine bootstraps at L2. No capacity policy is changed
  to conceal a failure.

The older Fig. 8 is measured CPU preparation plus simulator predictions
with L4 Spine initialization. This FPGA run uses L2 and actual XRT
allocation/upload/wait costs. It therefore does not, by itself, measure
prediction error for that L4 model. Neither results nor configurations are
silently merged. Single samples establish observed outcomes, not confidence
intervals or steady-state averages.

## Files

- [CSV](fig8_fpga.csv): all eight attempted pairs and absolute timing terms.
- [PNG](figures/fig8_fpga_update_throughput.png) /
  [PDF](figures/fig8_fpga_update_throughput.pdf): Python/GraphyFlow-style,
  TX Typewriter; both panels have their own legend and a 1x reference.
- [Run journal](raw/results.json): commands, CPU affinity, exact host/image
  and input identities, correctness, clocks and live memory observations.
- [Inputs](inputs.json): original trace identities and conversion paths;
  graph data and xclbins remain outside Git and are indexed by SHA-256.
- [Bindings](hardware.json): exact local host and image paths.
- [Frozen native host sources](host-sources.tar.gz): both thin wrappers,
  included production dependencies, compiler commands and a portable build
  script. Verify with the embedded SHA256SUMS before rebuilding.
- `setup_failure_card1/`: earlier image-programming timeout before any
  successful update sample. The runner was interrupted when it attempted
  the next arm; its original RUNNING journal is retained, not treated as
  completed evidence. All selected measurements use card 0.
- [File manifest](manifest.json): SHA-256 of every delivered file except
  this manifest itself.

The board runner used a 24 GiB hard limit, 22 GiB high watermark, zero swap,
an exclusive board lease and a 32 GiB live reserve. Peak cgroup memory was
{report["memory_peak_bytes"] / 2**30:.2f} GiB; memory events are in the journal.
Clock sets are recorded after each arm under the same lease, not inferred
from the filename. This is a timing measurement, not a new routing claim.

## Code And Reproduction

The owning package is
`spine_cycle_sim/experiments/evaluation_impact/figure8_fpga/`; native wrappers
are in `cpp/tests/evaluation_impact/figure8_fpga/`. From a full repository
checkout, use Python 3.11+, Matplotlib, LaTeX txfonts and dvipng:

```sh
module=spine_cycle_sim.experiments.evaluation_impact.figure8_fpga
python3 -m "$module.render" --data /path/to/fig8_fpga.csv --output /tmp/fig8-redrawn
python3 -m unittest tests.test_figure8_fpga tests.test_figure8_fpga_sources
```

For board reproduction, first rebuild the archived hosts, restore the
hash-indexed inputs/images, update `hardware.json`, then use `board.py`
inside a finite systemd cgroup with an available board. Exact commands of
the measured run, including environment and affinity, remain in the journal.
Do not rerun over this frozen output directory.
"""


def export(args):
    report = checked_report(args.run)
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.run, args.output / "raw")
    shutil.copytree(args.setup_failure, args.output / "setup_failure_card1")
    for source, name in ((args.inputs, "inputs.json"), (args.hardware, "hardware.json"),
                         (args.host_sources, "host-sources.tar.gz")):
        shutil.copy2(source, args.output / name)
    analysis.write_table(report, args.output / "fig8_fpga.csv")
    if (args.output / "fig8_fpga.csv").read_bytes() != (args.run / "fig8_fpga.csv").read_bytes():
        raise ValueError("replayed CSV differs from the run's CSV")
    render.render(args.output / "fig8_fpga.csv", args.output / "figures")
    (args.output / "README.md").write_text(readme(report))
    (args.output / ".gitattributes").write_text(
        "# Preserve byte-for-byte hardware receipts, including CRLF CSV and tool output.\n"
        "fig8_fpga.csv -text whitespace=cr-at-eol\n"
        "raw/** -text -whitespace\nsetup_failure_card1/** -text -whitespace\n")
    manifest = dict(status=report["status"], timing_source="FPGA_MEASURED",
                    measured_pairs=sum(c["status"] == "MEASURED" for c in report["cases"]),
                    attempted_pairs=len(report["cases"]),
                    files={str(path.relative_to(args.output)): checksum(path)
                           for path in sorted(args.output.rglob("*")) if path.is_file()})
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "inputs", "hardware", "host-sources", "setup-failure", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    export(parser.parse_args())
