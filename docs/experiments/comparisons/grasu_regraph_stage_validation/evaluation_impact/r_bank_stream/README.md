# Current Bank-Stream R Against A4

## Scope

This is the complete-convergence counterpart of the
[resident bank-stream replay](../../actual_sharded_k4/model_sync/system/bank_stream/README.md).
It adds the current two-pair source topology to the existing
[credit sensitivity controls](../r_credits/README.md), without replacing them.
The earlier `candidate` arm has four source masters sharing two physical
banks; it is not the current seven-master topology.

Status: the fresh GCC-pinned remote attempt passed compilation, the control
test and seven focused C++ regressions and is executing the declared matrix.
No new timing result is accepted until the complete matrix and the exact
legacy replay finish.
This study changes neither production model timing nor HLS. It does not
calibrate the simulator to FPGA or reproduce a published ReGraph number.

## Fixed Comparison

Every arm uses the same Amazon real-ID slice (258,046 vertices, 1,450,899
edges), old converged weighted-SSSP state and three source-0 weight decreases.
The updated graph and seed are resident. All arms must finish the same
46-round synchronous propagation and final shortest-path closure. The window
excludes G, preparation, DMA and host orchestration from both systems.

The predeclared matrix is eight arms, two mock memory latencies (64 and 128
cycles), and two component registration orders: **32 executions**. The seven
historical arms retain their configuration. `bank_stream` alone selects the
production `grasu_regraph_bank_stream_sssp_compute_v1` configuration factory:
four adapter masters, two pairwise source services and one Apply master;
1024 directory rows, 256 bank FIFO lines, reader/drain intervals of two,
16 parent credits and a 16-request Apply window. The harness asserts the
actual backend registration count: seven versus nine for old K4 controls.

Compare the new arm with both legacy A4 and `a4_io16`; do not select only the
closest result. A4 has 13 masters on nine banks and four property replicas.
The new K4 has seven masters and two source replicas plus primary state.
Equal frontend count or parent credits is not strict resource equivalence.
These mock-memory assumptions are sensitivity controls, not measured AXI
latencies or a complete SST/DRAMSim3 evaluation.

## Acceptance

- All **28** preceding observations must replay exactly, including every
  round's cycles/active count, traffic, full-state output hashes and extents.
- New forward/reverse results must match exactly. Every final state word,
  replica and active trajectory must equal the old synchronous oracle.
- The C++ harness checks edge/packet conservation, request/completion and
  beat closure, drained memory, Apply/source/status writes and physical bytes.
- Retain all declared rows, failures and timeouts. Fresh Release compilation,
  the configuration test and seven focused C++ regressions precede execution.
- Source/input/build hashes must remain unchanged through the campaign.

Passing admits this single compute prediction, not FPGA timing, strict
resource matching, original 11-Little/3-Big publication performance, complete
G+R or a replacement Spine speedup. Those flags remain false in the output.

## Ownership And Reproduction

`spine_cycle_sim/experiments/evaluation_impact/r_bank_stream/` owns the study:
`study.py` builds and executes, `analysis.py` checks the complete matrix, and
`runtime.py` applies the existing high-memory admission policy. The C++
harness shares its configuration helper in `cpp/tests/evaluation_impact/`.
Production C++ and the SST plugin are unchanged; no plugin rebuild is needed
for this harness-only addition.

The build selects `/usr/bin/g++` explicitly, records its version and binary
hash, and verifies CMake actually selected that compiler. Both hosts report
GCC 15.2.0, although their Debian package revisions differ; exact replay is
still required rather than assumed from the version string.

The pre-edit freeze is
`/data/chuxiao/experiments/r_bank_stream_comparison_20261019/pre-edit/`.
It retains the pre-edit source archive, original 28-row report and independent
input/compiler/binary pins. The final source archive digest was checked before
editing. A relocated run must verify both frozen archives and every copied
input hash, not substitute a newly prepared graph.

```bash
python3 -m unittest tests.test_regraph_bank_stream_comparison tests.test_regraph_credit_controls -q
python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.study \
  --before /data/chuxiao/r_bank_stream_comparison_20261019/pre-edit \
  --inputs /data/chuxiao/r_bank_stream_comparison_20261019/inputs \
  --output /data/chuxiao/r_bank_stream_comparison_20261019/execution-NEW \
  --cpus 112 113 114 115
```

The execution command requires an exact 40/36-GiB user cgroup, zero swap and
the named `seele-reserve-128g-v1` policy. It reserves full finite peer budgets,
uses a serial build and at most four isolated 4-GiB cases, and checks the live
128-GiB reserve throughout. The output must not already exist. `results.json`
retains complete observations, commands, failures and source/build/input pins;
`admission.json` and `live_memory.json` retain containment evidence. A running
or queued report is not a completed performance result.

## Current Execution

Remote root: `/data/chuxiao/r_bank_stream_comparison_20261019/`.
The immutable `campaign-v2/` transfer contains 2,332 independently checked
files; its archive SHA-256 is
`6823ff0f86c930041efb3877dff258b30be4fcd53d276942a52418d1953e0548`.
It runs as `spine-r-bank-stream-convergence-20261019-v2.service`, invocation
`124f9d284db14be39fef1203a8c1a0ad`, with output `execution-v2/`.
Temporary files use the existing campaign-specific `campaign-v2/tmp/`.

The preceding immutable `execution-v1/` is retained as `FAILED_RETAINED`.
CMake selected an environment-provided Clang, which rejected existing
GraSU override warnings under `-Werror`; its requested temporary directory
was also absent. No matrix row ran and no timing result was obtained. The
replacement pins GCC and an existing temporary directory; it does not change
GraSU source, suppress warnings, or overwrite the failed attempt.
