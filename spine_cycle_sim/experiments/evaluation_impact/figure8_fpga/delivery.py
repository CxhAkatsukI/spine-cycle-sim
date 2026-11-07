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


def verify_file(path, receipt):
    path = Path(path)
    if checksum(path) != receipt["sha256"] or path.stat().st_size != receipt["bytes"]:
        raise ValueError("changed receipt: " + str(path))


def check_single_graph_upload(text):
    layouts = analysis.records(text, "SPINE_PERSISTENT_LAYOUT")
    if (len(layouts) != 1 or layouts[0].get("fixed") != "1"
            or layouts[0].get("graph_uploads") != "1"):
        raise ValueError("single-upload repair requires a fixed=1 graph_uploads=1 layout receipt")
    for key in ("arena_allocate_ns", "live_upload_ns"):
        try:
            value = int(layouts[0][key])
        except (KeyError, ValueError) as error:
            raise ValueError("single-upload repair requires a nonnegative " + key + " receipt") from error
        if value < 0:
            raise ValueError("single-upload repair requires a nonnegative " + key + " receipt")


def check_sparse_scratch_init(text, *, single_metadata_upload=False, compact_host_staging=False,
                             host_bound_scratch=0, uninitialized_host_backing=False):
    summaries = analysis.records(text, "SPINE_PERSISTENT_UPDATE")
    if len(summaries) != 1:
        raise ValueError("sparse-init repair requires exactly one raw update summary")
    try:
        vertices = int(summaries[0]["vertices"])
    except (KeyError, ValueError) as error:
        raise ValueError("invalid sparse-init update vertex count") from error
    expected = dict(vertices=str(vertices), bitmap_words=str((vertices + 127) // 128),
                    family_words=str((vertices + 3) // 4), owner_host_upload="0")
    if single_metadata_upload:
        expected.update(host_bound_scratch=str(host_bound_scratch), metadata_uploads="1")
    if compact_host_staging:
        expected["compact_host_staging"] = "1"
    if uninitialized_host_backing:
        expected["uninitialized_host_backing"] = "1"
    receipts = analysis.records(text, "SPINE_MAINT_SPARSE_INIT")
    if (vertices <= 0 or len(receipts) != 1
            or any(receipts[0].get(key) != value for key, value in expected.items())):
        raise ValueError("SPINE_MAINT_SPARSE_INIT must occur exactly once and match raw vertices, "
                         "ceil-divided live ranges and owner_host_upload=0" +
                         (f", host_bound_scratch={host_bound_scratch} and metadata_uploads=1"
                          if single_metadata_upload else "") +
                         (", compact_host_staging=1" if compact_host_staging else "") +
                         (", uninitialized_host_backing=1" if uninitialized_host_backing else ""))


def input_plan(run, report):
    local = run / "inputs.json"
    path = local if local.exists() else Path(report["inputs"]["path"])
    verify_file(path, report["inputs"])
    plan = json.loads(path.read_text())
    cases = plan["cases"]
    expected = {(dataset, 4096, 10, "a") for dataset in ("AU", "SU", "WK", "SO", "PK")}
    expected.update(("AU", 131072, count, "b") for count in (10, 100, 1000))
    names = [case["name"] for case in cases]
    if (plan["status"] != "READY" or len(cases) != 8 or len(set(names)) != 8
            or {(c["dataset"], c["updates"], c["batches"], c["panel"]) for c in cases} != expected
            or any(not name or Path(name).name != name or name in (".", "..") for name in names)):
        raise ValueError("the input manifest must declare the complete eight-case matrix")
    return plan


def checked_report(run, *, partial=False):
    run = Path(run)
    report = json.loads((run / "results.json").read_text())
    if report["status"] not in ("COMPLETED", "COMPLETED_WITH_FAILURES"):
        raise ValueError("cannot deliver an unfinished campaign")
    if (report["samples_per_arm"] != 1 or report["warmups"] != 0
            or report["timing_source"] != "FPGA_MEASURED"):
        raise ValueError("one sample per arm, without warmups, required")
    cases = report["cases"]
    declared = {case["name"]: case for case in input_plan(run, report)["cases"]}
    names = [case["name"] for case in cases]
    if (not names or len(set(names)) != len(names) or not set(names) <= declared.keys()
            or names != [name for name in declared if name in names]
            or (not partial and names != list(declared))):
        raise ValueError("the complete declared matrix is required, including failures")
    for case in cases:
        if any(case.get(key) != value for key, value in declared[case["name"]].items()):
            raise ValueError("case differs from the input manifest: " + case["name"])
        if case["status"] in ("RUNNING", "PREPARING"):
            raise ValueError("unfinished case")
        if set(case["arms"]) != {"spine", "gr"}:
            raise ValueError("a declared arm was never attempted")
        for arm, result in case["arms"].items():
            if result["status"] in ("RUNNING", "PREPARING"):
                raise ValueError("unfinished arm")
            for stream in ("stdout", "stderr"):
                receipt = result.get(stream)
                path = run / case["name"] / f"{arm}.{stream}.txt"
                if receipt is None:
                    if result["status"] == "PASS" or path.exists():
                        raise ValueError("missing raw log receipt")
                else:
                    if Path(receipt["path"]).name != path.name:
                        raise ValueError("unexpected raw log filename")
                    verify_file(path, receipt)
            if result["status"] != "PASS":
                if not result.get("error") or result.get("timing"):
                    raise ValueError("failed arm needs an error, not admitted timing")
                continue
            text = (run / case["name"] / f"{arm}.stdout.txt").read_text()
            observed = analysis.timing(text, arm, case)
            if observed != result["timing"]:
                raise ValueError("raw timers differ from the journal")
            if arm == "spine" and report.get("persistent_layout") in ("fixed-v5", "fixed-v6", "fixed-v7", "fixed-v8", "fixed-v9"):
                check_single_graph_upload(text)
            if arm == "spine" and report.get("persistent_layout") in ("fixed-v6", "fixed-v7", "fixed-v8", "fixed-v9"):
                check_sparse_scratch_init(
                    text, single_metadata_upload=report["persistent_layout"] in ("fixed-v7", "fixed-v8", "fixed-v9"),
                    compact_host_staging=report["persistent_layout"] in ("fixed-v8", "fixed-v9"),
                    host_bound_scratch=int(report["persistent_layout"] == "fixed-v9"),
                    uninitialized_host_backing=report["persistent_layout"] == "fixed-v9")
            if arm == "gr" and int(observed["raw_summary"]["metadata_replicas"]) != report["metadata_replicas"]:
                raise ValueError("G metadata configuration changed within the matrix")
        arms = case["arms"]
        passed = all(result["status"] == "PASS" for result in arms.values())
        measured = passed and arms["spine"]["clock"]["driver_reported_mhz"] == arms["gr"]["clock"]["driver_reported_mhz"]
        if (case["status"] == "MEASURED") != measured:
            raise ValueError("pair outcome disagrees with arm correctness or clocks")
        if measured:
            ratio = arms["gr"]["timing"]["setup_inclusive_ns"] / arms["spine"]["timing"]["setup_inclusive_ns"]
            if ratio != case["speedup"]:
                raise ValueError("speedup does not match the recorded timer sums")
        elif case.get("speedup") is not None:
            raise ValueError("failed pair cannot carry an admitted speedup")
    expected_status = "COMPLETED" if all(c["status"] == "MEASURED" for c in cases) else "COMPLETED_WITH_FAILURES"
    if report["status"] != expected_status:
        raise ValueError("campaign status omits a failed pair")
    for source in report.get("source_campaigns", []):
        path = Path(source["journal"]["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("source journal must be retained inside the merged run")
        verify_file(run / path, source["journal"])
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


def readme(report, *, setup_failure=False):
    passed = sum(case["status"] == "MEASURED" for case in report["cases"])
    failed = len(report["cases"]) - passed
    outcome = (f"{failed} failed pairs remain explicit in the CSV and preview. "
               "They have no admitted speedup; raw logs and recorded errors retain the failure evidence."
               if failed else "All eight pairs passed the recorded correctness and clock checks.")
    repaired = report.get("persistent_layout") in ("fixed-v3", "fixed-v4", "fixed-v5", "fixed-v6", "fixed-v7", "fixed-v8", "fixed-v9")
    layout = (f'Spine uses the declared {report["persistent_layout"]} persistent layout '
              f'(repair {report.get("repair", "unspecified")}). '
              "Raw fixed=1 layout receipts and physical launch accounting identify repaired execution. "
              "Chronological logical batches are retained; every physical sublaunch is charged."
              if repaired else "No fixed-layout persistent repair is declared by this journal. "
              "Use the archived host identities and raw logs to identify its bootstrap policy.")
    if report.get("persistent_layout") in ("fixed-v4", "fixed-v5", "fixed-v6", "fixed-v7", "fixed-v8", "fixed-v9"):
        version = report["persistent_layout"].removeprefix("fixed-")
        layout += (f" The declared {version} candidate statically bootstraps every family at L10, uses "
                   "at most 8,192 updates per physical launch, and allocates one active record "
                   "for the external MAINT-only host. Exact host artifacts pin this candidate; "
                   "the fixed=1 marker alone does not distinguish repair versions.")
    if report.get("persistent_layout") in ("fixed-v5", "fixed-v6", "fixed-v7", "fixed-v8", "fixed-v9"):
        layout += (f" {version.upper()} constructs the directory from the compact host image, "
                   "allocates the fixed device arenas directly, and performs a single fixed-arena graph upload, "
                   "not a compact-device upload followed by relocation. Every successful Spine "
                   "arm has a graph_uploads=1 receipt with arena_allocate_ns and live_upload_ns; "
                   "failed attempts remain failures rather than single-upload evidence.")
    if report.get("persistent_layout") in ("fixed-v6", "fixed-v7", "fixed-v8", "fixed-v9"):
        layout += (f" {version.upper()} retains full device allocation and reduces initialized ranges, not "
                   "initialization itself. Scratch and owner buffers use CONTENT_UNDEFINED; "
                   "the host explicitly uploads ceil(V/128) dirty-bitmap words and ceil(V/4) "
                   "family-directory words at their fixed offsets. Each successful Spine arm "
                   "has exactly one SPINE_MAINT_SPARSE_INIT receipt matching the raw update "
                   "vertex count, with owner_host_upload=0. The lifecycle initializes owner "
                   "before MAINT; per-launch input writes remain. Initialization remains "
                   "charged inside bootstrap_ns.")
    if report.get("persistent_layout") in ("fixed-v7", "fixed-v8"):
        layout += (f" {version.upper()} allocates scratch, owner and metadata without bound host initialization; "
                   "metadata also uses CONTENT_UNDEFINED. Only the wrapper uploads the final "
                   "patched metadata once; the lifecycle has no metadata argument. Every successful "
                   "Spine arm's SPINE_MAINT_SPARSE_INIT receipt additionally requires "
                   "host_bound_scratch=0 and metadata_uploads=1. Full allocations, sparse live-range "
                   "initialization and per-launch input writes remain; the metadata upload is "
                   "charged inside bootstrap_ns, not removed from initialization costs.")
    if report.get("persistent_layout") == "fixed-v8":
        layout += (" V8 uses compact CPU staging for input, dirty bitmap and family directory, "
                   "without a host owner vector; full device capacities remain unchanged. Each "
                   "successful Spine arm requires compact_host_staging=1 on that same sparse-init "
                   "receipt. Required initialization and per-launch writes remain charged, with "
                   "bootstrap initialization still inside bootstrap_ns.")
    if report.get("persistent_layout") == "fixed-v9":
        layout += (" V9 binds aligned, raw nonzeroed host backing for full scratch, owner and fixed "
                   "arenas, retaining full device capacities. CONTENT_UNDEFINED avoids uploading "
                   "the uninitialized backing; explicit live-range initialization and graph prefix "
                   "writes remain. Compact CPU staging holds input, dirty bitmap and family directory, "
                   "without a zeroed full-size owner vector. Already aligned, host-bound metadata "
                   "is migrated once after the wrapper patches it; the lifecycle has no metadata "
                   "argument. Every successful Spine arm requires host_bound_scratch=1, "
                   "metadata_uploads=1, compact_host_staging=1 and uninitialized_host_backing=1 "
                   "on the same sparse-init receipt. Required initialization and per-launch writes "
                   "remain charged; initialization and the single metadata migration stay inside "
                   "bootstrap_ns. Uninitialized host backing does not remove device initialization.")
    sources = report.get("source_campaigns", [])
    provenance = ("The matrix combines disjoint partial campaigns without rerunning or averaging cases.\n" +
                  "\n".join(f'- [Source {i + 1}](raw/{source["journal"]["path"]}): '
                            f'`{source["directory"]}`, `{source["status"]}`.'
                            for i, source in enumerate(sources)) if sources else
                  "The run journal is the original single-campaign provenance.")
    hard, high = report["memory_gib"], report.get("memory_high_gib")
    high_text = (f"The recorded high watermark is {high} GiB." if high is not None else
                 f"The {hard} GiB launch profile normally uses a {hard - 2} GiB high watermark; "
                 "memory.high was not recorded in this journal.")
    setup_text = ("- `setup_failure_card1/`: separately retained setup-failure evidence, not a measured sample.\n"
                  if setup_failure else "")
    return f"""# Figure 8: One-Pass FPGA Update Throughput

**Real FPGA measurements**, {passed}/8 complete pairs.
One measured execution per arm per case, no warmup, repeats or averaging.
The paper and frozen prior deliveries are unchanged.

## Results

The ratio is G update time / Spine update time; above 1 favors Spine.
This is the maintenance-only part of G+R; ReGraph propagation is not run.

{table(report["cases"])}

{outcome}
No failed point is replaced with a simulator prediction or a selected retry.

## Configuration And Provenance

{layout}

{provenance}

Source journals, per-case raw logs, timestamps, commands and arm ordering
are retained unchanged. The flat result follows the input manifest's case order.
This is one paired sample per case across the recorded campaigns, not a claim
that the complete matrix ran under one uninterrupted board lease.

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
  The one-time lifecycle initialization status check remains inside Spine's
  bootstrap timer, as in the original production host.
- No graph propagation or convergence is timed. The weighted update kernel
  is algorithm-independent for this insertion workload; these are not three
  different algorithm runs, nor a replacement for Fig. 7 latency.
- Both arms use identical original IDs, weights, order and batch boundaries.
  G explicitly reserves PMA from the future trace union and uses
  {report["metadata_replicas"]} metadata replica(s). Layout and capacity policy
  changes are disclosed above, not used to hide failures.

The older Fig. 8 is measured CPU preparation plus simulator predictions
with L4 Spine initialization. These FPGA runs include actual XRT
allocation/upload/wait costs and do not, by themselves, establish prediction
error for that model. Single samples establish observed outcomes, not confidence
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
{setup_text}- [File manifest](manifest.json): SHA-256 of every delivered file except
  this manifest itself.

The recorded hard memory budget is {hard} GiB under `{report["memory_profile"]}`.
{high_text} The board runner requires zero swap, an exclusive board lease
and a 32 GiB live reserve. The maximum recorded cgroup peak across source
campaigns was {report["memory_peak_bytes"] / 2**30:.2f} GiB, not a sum of peaks;
each campaign's own memory events remain in its journal.
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
python3 -m unittest discover -s tests -p 'test_figure8_fpga*.py'
```

For board reproduction, first rebuild the archived hosts, restore the
hash-indexed inputs/images, update `hardware.json`, then use `board.py`
inside a finite systemd cgroup with an available board. Exact commands of
the measured run, including environment and affinity, remain in the journal.
Do not rerun over this frozen output directory.
"""


def export(args):
    report = checked_report(args.run)
    verify_file(args.inputs, report["inputs"])
    verify_file(args.hardware, report["hardware"])
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.run, args.output / "raw")
    setup_failure = getattr(args, "setup_failure", None)
    if setup_failure is not None:
        shutil.copytree(setup_failure, args.output / "setup_failure_card1")
    for source, name in ((args.inputs, "inputs.json"), (args.hardware, "hardware.json"),
                         (args.host_sources, "host-sources.tar.gz")):
        shutil.copy2(source, args.output / name)
    analysis.write_table(report, args.output / "fig8_fpga.csv")
    if (args.output / "fig8_fpga.csv").read_bytes() != (args.run / "fig8_fpga.csv").read_bytes():
        raise ValueError("replayed CSV differs from the run's CSV")
    render.render(args.output / "fig8_fpga.csv", args.output / "figures")
    (args.output / "README.md").write_text(readme(report, setup_failure=setup_failure is not None))
    (args.output / ".gitattributes").write_text(
        "# Preserve byte-for-byte hardware receipts, including CRLF CSV and tool output.\n"
        "fig8_fpga.csv -text whitespace=cr-at-eol\n"
        "raw/** -text -whitespace\nsetup_failure_card1/** -text -whitespace\n")
    manifest = dict(status=report["status"], timing_source="FPGA_MEASURED",
                    measured_pairs=sum(c["status"] == "MEASURED" for c in report["cases"]),
                    attempted_pairs=len(report["cases"]),
                    persistent_layout=report.get("persistent_layout"),
                    source_campaigns=report.get("source_campaigns", []),
                    files={str(path.relative_to(args.output)): checksum(path)
                           for path in sorted(args.output.rglob("*")) if path.is_file()})
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "inputs", "hardware", "host-sources", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--setup-failure", type=Path)
    export(parser.parse_args())
