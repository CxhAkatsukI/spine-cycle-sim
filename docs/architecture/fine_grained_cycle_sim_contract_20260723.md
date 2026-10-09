# Fine-grained cycle simulator contract

Date: 2026-07-23
Branch: `codex/fine-grained-cycle-sim`

Current Spine implementation status and evidence are frozen in
`fine_grained_spine_phase2_acceptance_20260723.md`. That milestone completes
the stable-profile hot/carry/full-tile/multi-round Spine slice; it does not mark
the competitor, hardware-calibration, or publication-evidence phases complete.

## Purpose

This branch replaces the coarse timing path with an execution-driven,
fine-grained simulator for a defensible Spine versus GraSU+ReGraph comparison.
The existing Python simulator and calibrated B/D/E2E models remain available as
the `legacy` regression baseline. They are not silently reinterpreted as the
new cycle model.

The primary claim targeted by this branch is narrower than RTL equivalence:
given an explicit architecture profile, real graph state, update batches, and
an algorithm policy, the simulator reproduces the architecturally visible
request, queue, storage, and compute behavior closely enough to predict
performance trends and expose bottlenecks. Every result must identify whether
it is measured, normalized, or projected.

## Frozen execution semantics

1. The cycle core is C++; Python loads graphs/configuration, constructs run
   matrices, invokes the core, checks oracles, and aggregates results.
2. Simulation is execution-driven. Components generate memory requests from
   their live state. A trace is allowed only for isolated memory validation.
3. Every clock edge uses `evaluate -> commit`. A producer cannot create a
   same-edge consumer result because of component registration order.
4. Time is a shared integer base. Core and HBM clock domains advance on their
   own edges. A cross-domain response becomes visible at the next destination
   clock edge plus an explicit bridge delay.
5. Finite FIFO/AXIS queues model capacity, ready/valid backpressure, width,
   transfer count, occupancy, and stall reason.
6. BRAM, URAM, and scratchpads are cycle components, not Python containers.
   They model capacity, banking, ports, latency, arbitration, conflicts,
   hazards, and overflow/fallback behavior.
7. AXI masters model burst splitting, IDs/outstanding limits, address-channel
   acceptance, response queues, ordering constraints, and backpressure.
8. The formal memory backend is online SST memHierarchy plus DRAMSim3/HBM.
   `MockMemory` is deterministic and exists only for unit tests and debugging.
9. Long idle intervals may be skipped only when the skip cannot alter queue
   occupancy, contention, arbitration, backpressure, or the order of visible
   events. Skips are counted and can be disabled.

## Architecture and comparison profiles

Machine-readable profiles live in `configs/architectures/`. A profile pins the
source revision, achieved clocks, memory geometry, architecture parameters,
feature set, evidence tier, artifacts, and limitations. Profile identity and
manifest SHA-256 must be copied into every run result.

- `spine_legacy_134_calibration`: historical hardware used by the existing
  B/D calibration layer.
- `spine_shared_engine_9c08763`: stable hardware performance reference. It is
  the default validation target until a newer accepted bundle exists.
- `spine_latest_afb8199`: source-following experimental profile. It is not a
  performance baseline without accepted hardware evidence.
- `spine_candidate10_one_pass_1e61fc0`: hardware-validated native Candidate10
  anchor with frozen source, routed xclbin, area, timing, and selected cycle
  evidence.
- `spine_candidate10_normalized_v1`: Candidate10-derived normalized profile.
  Its maintenance, AXI, family, level, partition, and tile parameters are
  fail-closed against the native parent; this is now the normalized comparison
  baseline, not a native measurement.

The comparison report has three separate views:

- `native`: faithfully reproduce each published/current architecture and its
  native numeric/algorithm semantics.
- `normalized`: equal algorithms, numeric rules, graph/update stream, HBM
  backend/geometry, and declared resource budget.
- `projected`: explicit architecture proposal. This cannot be presented as
  measured hardware and must carry resource, area, timing, and energy impact.

The U55C memory geometry is recorded as 32 HBM pseudo-channels. Spine uses 16
of them as graph-family channels and statically binds ancillary masters through
HBM[22]. The cycle core models those bindings as independent AXI initiators;
`graph_hbm_channels=16` must not be misread as the board's total channel count.

The primary competitor is a GraSU update engine with a PMA-native ReGraph
compute path. The existing host PMA-to-ReGraph conversion is secondary
evidence, because its conversion cost is an artifact of incompatible formats.
A zero-cost sum of standalone GraSU and ReGraph is only a lower bound.

## Algorithm contract

Algorithms plug into one hardware-shaped interface:

`Update -> Map -> Reduce -> Apply -> Activate/Converge`

The first complete release supports:

- Weighted SSSP: directed simple graph, non-negative integer weights,
  last-write-wins duplicates, missing delete is a no-op. Insert/decrease is
  incremental; delete/increase initially uses an exact full-recompute fallback.
- Full PageRank: damping `0.85`, float64 mathematical oracle, float32 default
  architecture profile, cold rank `1/N`, dangling redistribution, L1 residual
  threshold `1e-6`, at most 100 iterations. Warm start is the primary dynamic
  mode; cold and fixed-iteration runs are separate modes.
- Thresholded residual PageRank: signed residual push, active when
  `abs(residual) > epsilon/N`, default `epsilon=1e-6`, with explicit dangling
  redistribution and all frontier/push/edge work counted.

Every batch is checked against both a high-precision mathematical oracle and a
bit-accurate architecture oracle. Numeric mismatch and timing mismatch are
reported independently.

## Measurement window

The primary experiment is resident-graph continuous batching:

`update + automatic differential detection + native on-device handoff + compute`

Initial graph loading, preprocessing, and host/PCIe transfer are reported
separately. Primary latency is never allowed to omit a conversion that the
declared architecture genuinely requires.

Required structural counters include accepted and stalled FIFO/AXIS transfers,
BRAM/URAM bank conflicts, AXI requests/bursts/beats/bytes, outstanding depth,
HBM row behavior when exposed by the backend, edges per tile/family/level,
frontier work, algorithm operations, and idle-skip intervals.

## Validation and claims gate

Calibration and holdout workloads are disjoint. The minimum validation set is
20 synthetic microbenchmarks plus three real datasets. For non-tiny holdout
runs, the initial target is:

- stage and E2E median absolute percentage error at most 20%;
- p90 absolute percentage error at most 35%;
- Spearman rank correlation at least 0.90.

Tiny cases use absolute cycle error. Structural counters that are observable in
HLS/hardware must match exactly. If the timing gate fails, results are labeled
`structural-only`; hidden fitted latency constants cannot substitute for a
missing mechanism.

The runtime target is RMAT-23 Full PageRank for 10 iterations in at most 10
minutes (hard limit 30 minutes), difficult SSSP/residual cases in at most 60
minutes, small CI in at most 60 seconds, and peak memory below 64 GiB.

## Area, timing, and energy

Cycle simulation supplies performance and activity. FPGA HLS/Vivado supplies
the first area/timing feasibility evidence. CACTI supplies memory-array energy
and area. Dynamic energy is activity multiplied by characterized event energy;
leakage is power multiplied by simulated time. The final publication-quality
comparison requires the same standard-cell/ASIC flow for both architectures.

Each simulator change is labeled as exactly one of:

- fidelity fix;
- profile parameter change;
- architecture proposal;
- simulator runtime optimization.

Architecture proposals require an explicit HLS/RTL realization and resource,
timing, and energy delta before being promoted from `projected`.

## Delivery phases

### Phase 1: trustworthy vertical slice

- C++ multi-clock `evaluate -> commit` scheduler.
- Finite FIFO/AXIS and banked on-chip memory primitives.
- AXI transaction layer, deterministic mock backend, and online SST backend.
- One end-to-end Spine maintenance/read/compute microbenchmark over a real edge
  list with dual-oracle correctness and structural counters.

Acceptance: C++ and Python tests pass; SST is used online in an integration
test; changing FIFO depth/outstanding limits creates the expected stalls; no
legacy regression fails.

### Phase 2: complete algorithms and competitor

- Stable Spine profile with all three algorithm policies.
- GraSU PMA update model and PMA-native ReGraph compute model using the same
  primitive semantics and HBM backend.
- Native, normalized, and projected experiment manifests.

Acceptance: every batch passes both oracles; normalized runs use identical
memory/numeric profiles; no host conversion is hidden; at least 20 synthetic
and three real workloads complete within the runtime envelope.

### Phase 3: evidence and hardware handoff

- Hardware holdout validation and calibrated claim gate.
- Activity, CACTI, FPGA area/timing, and later common ASIC flow.
- HLS implementation of the shared algorithm policy interface and proposed
  native handoff. All three algorithms pass C simulation and synthesis; a
  representative algorithm passes hw_emu/hw.

Acceptance: reproducible bundles contain source/profile hashes, exact commands,
raw counters, correctness outputs, prediction errors, synthesis reports, and
an explicit evidence tier for every chart row.
