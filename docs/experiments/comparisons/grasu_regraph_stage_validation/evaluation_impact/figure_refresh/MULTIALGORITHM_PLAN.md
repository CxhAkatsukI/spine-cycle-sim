# CC And Residual PageRank Completion

Status: in progress. This is an extension of the Figure 8--9 refresh, not an
admission of the complete baseline and not an edit to the paper.

Implementation checkpoint, 2026-10-23: the new Release core passes all 39
CTest targets, including warm CC and residual-PR independent oracles, finite
pressure and component-registration-order controls. Twelve preceding SSSP
trajectories retain identical full states, cycles and traffic. All four
direct-DRAMSim3 smoke arms and the three real-input CC pairs pass; the three
real-input residual-PR pairs are still running. These partial results are not
the final matrix or a complete Figure 9 delivery.

An initial multipart PR test exposed accumulation error in a sequential FP32
dangling sum. The correction follows the existing HLS's sixteen lanes and
eight FP32 accumulation banks, with 128 charged final-reduction cycles in
preparation and split-state Apply. Failed builds/tests and the interrupted
earlier matrix remain in the attempt archive. No timing multiplier was added.

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
   Existing SSSP cycles and ledgers must remain unchanged.
4. Check algorithm-specific R controls separately. The existing original-R
   implementation supports fixed-point PR and a local weighted-SSSP UDF;
   it does not already provide an original-author CC or residual-PR workload.
   Any additional UDF is a local control, not publication reproduction. Do not
   transfer the SSSP timing agreement to another algorithm without evidence.
5. Run AU/SU/WK CC and residual-PR pairs using pinned inputs, the same old
   converged state and update batch on both systems, and all-32-channel direct
   DRAMSim3 energy accounting. Keep the preceding SSSP results intact.
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
