# Original Little Finite-Resource Checkpoint

Status: **Gather/merge functional equivalence passes; timing is predicted.**
This advances the independent original-R component family. It does not finish
G, whole R/A, A4/B resource matching, or publication-speed reproduction.

## What Was Tested

The boundary starts with eight source-property/destination updates from
Scatter and ends with merged 512-bit property lines, before Apply. Each Little
has eight private 64K-vertex destination arrays; full-partition drain, clearing,
RAW forwarding, finite in-flight work, registered FIFOs, local merge, global
input holding and line packing are explicit. Review the
[implementation and assumptions](../../../implementation/grasu_regraph/original_regraph_little_gather.md).

An optional capture was added to the existing author-source probe without
changing the author algorithm. It exports **all** original global-merger words
in little-endian order, after the existing per-edge oracle check and before
Apply. The original pinned Scatter, Gather, generated merger and PR Apply
still execute in that probe. Previous functional result fields are unchanged.

| Control | Windows | Iterations/window | Words compared |
| --- | ---: | ---: | ---: |
| Original 4-Little / zero-Big downstream | 2 | 3 | 393,216 |
| Original 11-Little downstream component | 2 | 3 | 393,216 |

Every one of **786,432 words** matches both the original-source capture and a
separate direct per-edge sum. Windows start at source IDs 0 and 4096; each
iteration uses 257 logical edges, padded to 264 physical edges over all Little
pipelines. Three iterations reuse destination arrays after drain/clear. The
11-Little component is not the complete original 11L/3B system: Big does not
participate in this particular comparison.

Captures have fixed extent, SHA-256, source/compiler/dependency identities,
and the original merger boundary. Tests verify the PR iteration arithmetic
remains within signed-int limits. The model does not time Apply; its independent
scalar arithmetic only prepares the next comparison iteration's properties.

## Finite-Buffer Results

| Invariant case | Predicted cycles | Result |
| --- | ---: | --- |
| Four Little, depth-eight FIFOs, 1,000 bursts/Little | 33,788 | Oracle and all FIFO ledgers pass |
| Reverse all component registration order | 33,788 | Values, cycles and stall counters unchanged |
| Depth-one FIFOs, staggered sources, slow/delayed sink | 144,188 | Backpressure propagates; no lost or duplicated values |
| One in-flight Gather burst instead of seven | 39,782 | Added capacity stalls; same values |
| Eleven Little, staggered starts, 257 bursts/Little | 33,355 | Eleven-way merge and all ledgers pass |
| Reuse arrays for a zero-burst partition | 32,781 | Full drain emits only zeros; no leaked previous state |
| Reuse again with the initial nonzero partition | 33,788 | Values and cycles equal the first run |

Each invariant case checks 65,536 output words. Each lane drains 32,768 pairs,
and each global partition emits 4,096 lines, including zeros. Push/pop counts,
queue emptiness, maximum occupancy, valid/dummy tuple counts, update writes,
and full private-array drain are checked. Stalls are summed across components;
they may exceed elapsed cycles because multiple components stall concurrently.

The exact source fixture has different feed schedules from the invariant
fixture: synthetic 13-cycle stagger between Little starts. It predicts 32,835
cycles per four-Little comparison and 32,921 per eleven-Little comparison.
These numbers do not compare complete A4 versus complete A: they have neither
HBM nor Big nor whole-graph scheduling. Repetition preserves all stdout,
cycles and counters exactly.

The compiled comparison program also rejects three damaged reference cases:
one altered word, one removed word, and one appended word. An exit status
alone is insufficient: each negative control must produce its expected
specific diagnostic and must not time out.

## Interpretation

The new evidence establishes functional and resource-accounting behavior for
this finite Gather/merge network. It shows that sparse input still incurs
full destination-array drain, and that finite-buffer pressure changes predicted
time without changing answers. It is useful as an independently admitted
downstream for the next original-R reader and PMA-adapter controls.

It **does not establish** FPGA cycle agreement, original publication MTEPS,
or PMA adapter overhead. The detailed timing assumptions, idealized initial
state, and conservative/elastic backpressure choices are listed in the
implementation guide. HLS scheduling estimates constrain a model but do not
calibrate its end-to-end timing. The old total-system timings are not used as
an acceptance shortcut.

## Reproduce And Inspect

Run at the repository root with the pinned original sources already prepared
as described in [the study README](README.md). Use fresh output paths:

```bash
python3 scripts/run_upstream_stage_controls.py \
  --contract configs/experiments/grasu_regraph_upstream_captures_v1.json \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --out results/upstream_stage_controls/little_capture_reproduce
python3 scripts/run_original_regraph_gather_validation.py \
  --captures results/upstream_stage_controls/little_capture_reproduce \
  --out results/upstream_stage_controls/little_finite_reproduce
python3 -m unittest discover -s tests -p test_original_regraph_validation.py
```

The second command makes an isolated Release CMake build with one compiler
job and records compiler, flags, source and binary hashes. No frozen SST
binary is rebuilt. Add `--deliver-to NEW_FOLDER` to package a passing checkpoint;
packaging refuses to overwrite an existing delivery. The address-space limit
is 4 GiB per model/build process with 16 GiB reserve; original source capture
uses 2 GiB. All stages have saved output, timeout, and `wait4` peak RSS.

Delivered files are [finite_gather_results.json](finite_gather_results.json),
[finite_gather_verification.json](finite_gather_verification.json), and
[raw_little_finite_model.tar.gz](raw_little_finite_model.tar.gz). The archive
contains complete source captures, fixed contracts, compiler flags, all run
logs, negative-control diagnostics, and model/core regression results. It
excludes binaries, whole author-source trees, and regenerable damaged fixtures.
The verification index hashes each raw file and the archive. The existing
source pins and scheduling delivery remain unchanged alongside these files.

## Regression And Preservation

The delivered run passes seven C++ executables, including all six existing
core/GraSU/owner/lifecycle/address-map tests, and 71 focused Python tests.
The Python set covers the new admission/delivery owner, upstream functional
and HLS controls, repository organization, extraction-equivalence utilities,
and publication gates. Its logs are included in the raw archive.

All 2,437 protected evidence files retain their baseline hashes. The frozen
SST plugin remains SHA-256
`9a26e1fb51ecf7b99ccf0784c9e5bbc459cf857d293add557b9c52770b2c9d79`.
Existing numerical component bodies and the SST source list are unchanged.
The earlier 14-case SST extraction-equivalence matrix is retained, not rerun
for this separate-library checkpoint. No new FPGA run or full Python suite
is claimed.

The final sequential build's reported peak RSS is 690,572 KiB; the largest
new model test is 62,456 KiB. These `wait4` measurements are maximum process
RSS, not simultaneous whole-process-tree sums. Available memory exceeded
95 GiB before the model build, with the configured 16-GiB reserve retained.

## Remaining Work

1. Add the original edge reader, source-property memory service and ping-pong
   protocol to this component family; admit stream, memory and padding work.
2. Add Apply/degree/state-writeback and repeated iteration/partition scheduling;
   validate the complete four-Little path before timing its PMA-reader variant.
3. Add original Big/mixed scheduling and admit exact publication workload,
   topology, clock and event window before any published-rate comparison.
4. Complete original G search/DDR/host timing, with separately named source-16
   and paper-8 geometries, then compose validated stages with host overhead.

Neither additional channels nor a timing multiplier replaces these steps.
