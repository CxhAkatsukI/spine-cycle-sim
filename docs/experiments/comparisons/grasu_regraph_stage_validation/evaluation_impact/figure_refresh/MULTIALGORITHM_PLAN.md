# CC And Residual PageRank Completion

Status: numerical matrix complete. This is an extension of the Figure 8--9 refresh, not an
admission of the complete baseline and not an edit to the paper.

The final nine-pair matrix completed against `core-tests-v7`, whose fresh
Release build passes all 39 CTest targets. All six smoke and eighteen real
arms pass; the source pins remained unchanged. The complete
[delivery](multialgorithm/README.md) retains the six missing CC/PR pairs and
three same-model SSSP reruns. Partial or superseded matrices are historical
evidence, not the final delivery. Original CC/PR R timing controls and
original-G performance admission remain open, explicitly stated rather than
inherited from another algorithm.

## Retained Corrections

| Finding | Correction and required evidence |
| --- | --- |
| Sequential FP32 dangling accumulation loses accuracy on multipart PR | Follow the existing HLS's sixteen lanes and eight accumulation banks; charge 128 final-reduction cycles in preparation and split-state Apply; independent double-precision oracle and stored residual checks |
| Per-cycle scans of the complete Spine owner-state map make simulation unnecessarily slow | Maintain the in-flight count on existing transitions and clean only completed keys; public ledger checks still independently recount the map; ten saved arms have identical states, cycles, traffic and energy |
| Out-of-order DRAM responses can fill the finite read reorder storage and deadlock | Reserve storage before streamed beat issue and release it at ordered publication; test capacities 1/2/4/32, issue widths 1/4, held consumers and both scheduling/registration orders, without increasing storage or reducing latency |
| An original-A4 test depends on incidental same-cycle contention | Preserve the 38/39 failed run; add explicit shared-channel wiring and deliberately overlapping finite read/write pressure; the fresh complete 39-test gate passes |

The strict SSSP exact-cycle replay correctly rejected the AXI correction.
Its twelve inputs, full state hashes and traffic ledgers remain identical;
Spine cycles are unchanged. G+R adds 14 cycles for smoke and 1.35--1.70% for
the Amazon control because finite credits now constrain issue. The explicit
read-credit regression gate permits only that R-cycle delta and requires
registration-order invariance. This is a documented timing-model correction,
not behavior-preserving extraction. The final matrix reruns SSSP energy as
well as CC/PR; it must not select old energy under a new model identity.

All three final PR pairs show Spine accepting fewer bytes but taking
more modeled device cycles and more all-channel HBM energy. These negative
results are preserved rather than claiming a universal advantage. All failed,
interrupted and superseded attempts remain indexed in the delivered archive.

Deadline: 2026-10-24 05:30 CST for saved results and Git delivery, ahead of the
user-confirmed 06:00 machine restart. Start: 2026-10-23 19:06 CST.

## Gates

1. Freeze the current SSSP sources, compiler, executable identities and exact
   state/cycle/traffic outputs before modifying numerical code.
2. Extend the finite routed candidate for CC, then residual PageRank. Keep
   algorithm state encoding, degree/residual storage and initialization explicit.
   Charge device preparation and correction rather than hiding them in preload.
3. Require independent old/new graph oracles, complete convergence, source
   replica checks, padding checks and drained physical request/byte ledgers.
   SSSP states and byte ledgers must remain unchanged. A demonstrated model
   bug may change cycles only with an explicit retained before/after report,
   fresh affected figure data and registration-order invariance. It must not
   be labeled an exact-cycle replay.
4. Check algorithm-specific R controls separately. The existing original-R
   implementation supports fixed-point PR and a local weighted-SSSP UDF;
   it does not already provide an original-author CC or residual-PR workload.
   Any additional UDF is a local control, not publication reproduction. Do not
   transfer the SSSP timing agreement to another algorithm without evidence.
5. Run AU/SU/WK CC and residual-PR pairs using pinned inputs, the same old
   converged state and update batch on both systems, and all-32-channel direct
   DRAMSim3 energy accounting. Keep the preceding SSSP results intact as
   historical evidence and rerun their three pairs after the AXI correction.
6. Package raw/configuration/source identities, failed attempts, complete
   coverage, reproducible commands and unresolved limitations in this folder.
   Run numerical and repository-structure checks, commit, fetch and push.

## Execution Limits

Start with small correctness fixtures. Use finite per-process memory limits,
an explicit 24-GiB live reserve, bounded parallelism and wall-clock timeouts.
Save progress after every build and case. Do not begin work that cannot be
stopped and checkpointed before 05:30. No FPGA builds or paper edits.

## Claim Boundary

The G natural-geometry/shared-metadata path still needs its own original-G
performance admission. Passing these gates establishes the stated simulator
comparison scope only; it does not establish FPGA calibration or original
publication performance reproduction.
