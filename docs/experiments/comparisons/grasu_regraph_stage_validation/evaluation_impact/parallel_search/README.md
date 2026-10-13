# Parallel G Search: Prediction Checkpoint

## Conclusion

**The G performance-retention gate is not passed.** The opt-in parallel search
reduces predicted time by about 5x on larger mixed batches, but the current
direct-HBM hot-update path becomes the remaining bottleneck. Do not replace
the production baseline, claim a publication match, or rescale Figures 7--11.

The [final validation index](evidence/final_validation/index.json) contains all
84 runs, not only the
8192-update case that happens to be close to original G. Read the parent
[baseline admission plan](../PLAN.md) for the complete G/R/integration/Spine
goal. This checkpoint does not complete that goal.

## Scope And Controls

Three arms use identical initial PMA, weighted update words, logical operation
order, four HBM banks with 32 bank credits, declared latency 64 or 128 cycles,
and a 200-MHz model clock:

- Independent original-source16 G: finite search and original hot-cache model.
- Current G: unchanged compact direct search and direct-HBM hot updates.
- Search candidate: sixteen finite search contexts per CU, shared row/binary
  metadata master, ordered publication; the current hot/cold processors remain.

The candidate is explicitly default-off. It supports one full-word destination
window, not the production 23-channel sharded system. The original hot cache
has a fixed 16-MiB load/store footprint; the candidate does not receive a free
URAM cache. Port, storage and scheduling differences are architectural facts,
not coefficients fitted to the target result.

All inputs are resident and prepared. Timing starts at update execution and
ends with memory drain. Host preparation, DMA and orchestration are excluded
on every arm; these are **predictions, not FPGA measurements**. Original
source16 and publication paper8 are distinct, and neither prediction is a
reproduction of a published throughput number.

## Matrix And Results

Fourteen cases include empty/tiny inputs, a sixteen-lane boundary, hot-only
and cold-only inputs, repeated same-segment hazards, mixed batches of 4096,
8192, 16384 and 65536 updates. Each runs at both latencies on all three arms:
14 x 2 x 3 = 84 observations. Complete PMA hashes, cache/cold counts, row reads
and binary probes agree. The twelve old original/current observations replay
exactly, including cycles and traffic. Fourteen independent HLS-helper source
checks pass; those checks do not execute bounded whole-kernel RTL feedback.

| Latency | Updates | Original cycles | Current cycles | Search candidate | Candidate / original |
| --- | --- | --- | --- | --- | --- |
| 64 | 4096 | 577403 | 1441620 | 289742 | 0.502 |
| 128 | 4096 | 1142267 | 2740180 | 549070 | 0.481 |
| 64 | 8192 | 616852 | 2896724 | 582606 | 0.944 |
| 128 | 8192 | 1222885 | 5506004 | 1104078 | 0.903 |
| 64 | 16384 | 700900 | 5806932 | 1168334 | 1.667 |
| 128 | 16384 | 1389287 | 11037652 | 2214094 | 1.594 |
| 64 | 65536 | 1206069 | 23268180 | 4682702 | 3.883 |
| 128 | 65536 | 2384885 | 44227540 | 8874190 | 3.721 |

A ratio below one means the candidate is faster. Both the no-more-than-10%
slower gate and the two-sided 10% matching gate fail over the complete nonempty
matrix. Empty input remains a fixed-overhead control, not a speed gate.
At small batches, the original fixed cache load/store dominates; at large
batches it amortizes, exposing the candidate's direct-HBM update cost. The
8192-update near-match is not evidence of a general performance match.

## Hardware Feasibility

Two isolated U55C HLS compile attempts succeeded, but **neither meets the
requested 200-MHz estimated clock**. Successful XO generation is not timing
closure, routing, integration or FPGA calibration.

| Attempt | Estimated period | Target | LUT | FF | BRAM18 | URAM |
| --- | --- | --- | --- | --- | --- | --- |
| Initial request selector | 12.193 ns | 5 ns | 24986 | 22430 | 4 | 0 |
| Balanced ready-mask selector | 8.036 ns | 5 ns | 21195 | 21455 | 4 | 0 |

Generated interface reports show 96-bit data and 12-bit keep/strb. The host
source helper reports a vendor-header keep-width quirk separately rather than
changing the synthesized ABI. Source checks cover request/response values,
all selector masks/rotations, credit counts and ordered packets. HLS reports
still warn about backward dataflow channels: bounded RTL co-simulation is
required before asserting deadlock freedom or achieved initiation rates.

The current model does not claim to model the synthesized arbitration delay.
Consequently the 200-MHz candidate timings are conditional architectural
predictions, not proof that this particular HLS implementation attains them.

## Next Experiments

1. Pipeline the metadata arbiter and validate finite request/response/credit
   feedback in RTL, including blocked output and same-key updates.
2. Investigate segment-ordered hot-update concurrency or a bounded cache in
   the owning HLS path. Preserve same-segment ordering and count all extra
   state, ports, traffic and preload/writeback costs. Mirror only implementable
   changes in an explicit simulator candidate.
3. Repeat the full matrix, including large batches and hot/cold/conflict
   neighbors. Promote nothing based on a favorable crossing point.
4. Then finish the R resource control and CC/ResPR neighbors, actual G-to-R
   handoff and host windows. Only an admitted baseline proceeds to the matched
   warm Spine demo and a new figure-impact assessment.

Earlier R evidence remains unchanged: one Amazon warm SSSP compute case is
within about 5% of original A4, but resource equality, other algorithms,
publication timing and actual G integration remain open. It is not a complete
G+R or Spine result.

## Ownership And Reproduction

- Core interface: `cpp/include/spine_sim/grasu_update/search.hpp`.
- Finite candidate: `cpp/src/grasu_update/parallel_search.cpp`.
- Opt-in composition only: `cpp/src/grasu.cpp`, `GraSuNativeConfig`.
- Three-arm fixture: `cpp/tests/evaluation_impact/common_g/`.
- Experimental HLS, not production HLS: its `hls/` subdirectory.
- Preparation, execution, validation, analysis, synthesis and packaging:
  `spine_cycle_sim/experiments/evaluation_impact/common_g/parallel/`.
- Focused tests: `cpp/tests/grasu_parallel_search_tests.cpp` and
  `tests/test_grasu_parallel_search.py`.

Use a fresh Release core build and fresh output directories. Source, input,
binary and report identities are pinned. Raw artifacts are indexed in
`evidence/`; machine-local absolute paths are provenance, not portable inputs.
The first two failed source-helper attempts and the earlier 72-row intermediate
matrix are retained alongside the complete 84-row matrix and both HLS attempts.
The final runner replay includes compiler/CMake version capture, a mandatory
complete-matrix validation call and explicit exclusion of empty input from
performance gates. It reproduces all 84 observation records and state hashes
exactly. Earlier capsules are preserved, not rehashed to the new runner. See
the [evidence guide](evidence/README.md) for the reading order.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.parallel.study \
  --output /path/to/fresh-matrix --core-build /path/to/release-build/cpp \
  --previous /path/to/original-common-g/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.parallel.synthesis \
  --output /path/to/fresh-isolated-hls

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.parallel.delivery \
  --output /path/to/fresh-evidence --matrix /path/to/fresh-matrix/results.json \
  --previous /path/to/original-common-g/results.json \
  --hls /path/to/first-hls/results.json /path/to/second-hls/results.json \
  --retained /path/to/failed-first/results.json /path/to/failed-second/results.json
```

Matrix execution is sequential, pinned to one CPU, limited to 4 GiB address
space per process, with a 24-GiB system reserve and 600-second step timeout.
Isolated HLS uses an 8-GiB process/cgroup ceiling, no swap, two CPUs and a
900-second compile timeout. Do not run another Vitis build alongside an active
route. Keep queued-route inputs and frozen paper/figure packages unchanged.

## Regression Checks And Remaining Limits

- Fresh Release C++ build: all 28 CTest tests pass. Focused search tests also
  reject unsupported ABI, partition count and metadata-channel composition.
- Fresh default SST plugin: builds and loads; three four-channel online-memory
  smoke cases pass with closed 64-request ledgers. The existing G+R native SSSP
  smoke also passes its state oracle and closed backend arbitration ledger.
  These check default-path integration, not candidate SST exposure or timing.
- Focused Python checks cover full-matrix admission, identical-work gates,
  immutable report identities, packaging and exact replay. Repository layout,
  catalogs, SST loading/memory checks and plugin transition are checked too.
- The old `tests.test_stage_validation_delivery` live-source identity test is
  still failing: 23 hash subassertions already differed from HEAD before this
  work; the two intentionally changed G source files add four occurrences.
  Its other five tests pass. Frozen historical source identities are not
  rewritten, and this suite is not reported as green.

The [verification report](verification.json) indexes the bounded runs and
their raw logs. No production HLS source, paper text or frozen figure package
is changed by this checkpoint. No actual G-to-R handoff or new Spine demo is
claimed.
