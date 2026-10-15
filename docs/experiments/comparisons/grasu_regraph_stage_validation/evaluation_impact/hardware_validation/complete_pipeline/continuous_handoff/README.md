# Continuous G To SSSP Handoff

## Decision

**Host functional preflight passes; FPGA execution has not run.** This study
adds a bounded single-partition SSSP host to the resident-G test. Nine compact
AU/SU/WK inputs produce 27 checked batch rows. Every final distance and
synchronous active-count trajectory agrees with an independent Dijkstra
oracle. None of these rows is a measured FPGA cycle, publication match,
integrated RTL pass or complete-baseline admission.

The [host evidence index](host_evidence/index.json) contains frozen source,
inputs, contracts, raw output, compiler/header identities and resource logs.
It preserves v1 (18 passing rows), v2 (parser rejection), and v3 (27 passing
rows). No attempt was overwritten. The separate
[G regression index](g_regression_evidence/index.json) records a fresh run of
the original G-only host: all eighteen non-timing state results equal the
earlier guarded-host capsule.

## Matrix And Limits

| Inputs | Batches per input | Policy and useful coverage |
| --- | --- | --- |
| AU/SU/WK mixed-512 | Empty, 256 physical records, remaining 256 | Nonempty batches require deletion fallback |
| AU/SU/WK weight-change-4096 | Empty, 4096 physical records, remaining 4096 | Net weight increases trigger fallback |
| AU/SU/WK warm-decrease-64 | Empty, 64 physical records, remaining 64 | 64 distinct logical decreases overall; AU/SU actually propagate without resetting old distances |

Warm controls select the first 64 distinct decreases whose deletion weight
matches the initial graph, in the frozen weight-change input's pair order.
They are explicitly derived functional controls, not additional original
traces or cherry-picked timing measurements. Each nonempty batch changes 32
logical edges. WK's fixed source 0 has little reachability: its warm batches
terminate with zero newly active vertices, so it does not establish meaningful
propagation performance. AU/SU warm batches take 3--8 synchronous rounds.

Each graph has 8192 initial edges, fewer than 65536 vertices and one native
65536-vertex destination partition. Inputs reserve future positive variants;
all physical edits are hot-cache updates. Cold G, native multi-partition
convergence, capacity growth, CC, ResPR and FullPR are outside this preflight.
These compact cases do not replace the requested eight-large-graph matrix.

## Data Path And Timing

The host starts with the old graph's converged source-0 distances, then keeps
PMA and state BOs resident over three consecutive batches. G receives only
that batch's physical updates. The adapter binds the **same** four PMA BOs
and row BO written by G; no CPU compact-edge reconstruction or graph restore
is allowed between G and R. R loops until its device active count reaches
zero, including the final no-change round, with a declared 2048-round limit.
Both source-state replicas and apply state are checked after publication.

For insertion/decrease-only net changes, the host detects changed sources
and writes active bits into the resident distance replicas. A net removal or
weight increase instead resets distances and recomputes on the updated PMA.
This host-side policy is explicit; it is not claimed as device-generated
seeding or the final optimized host implementation.

The intended board E2E window includes net-policy detection, update packing,
G DMA/launch/wait/publication, seed or fallback DMA, all R rounds, convergence
readbacks and final result readback. One-time parsing/reservation/programming
and old-state upload are separate. Independent correctness oracles and full
PMA/metadata/state-replica diagnostic readbacks are outside this window.
The current net-policy implementation copies/scans a host edge map; its cost
is included, not assumed free. Kernel event intervals are unioned rather
than summed across overlapping CUs.

`--model-check` invokes no FPGA API and reports G/R busy time and hardware
E2E time as zero. Its host preparation/oracle costs are not device latency.
The `--board` path only compiles in this preflight; it still needs strict
route admission, the shared board lease, runtime checks, bounded execution
and event analysis before any hardware claim.

## Retained Failure And Compatibility

v2 failed before graph construction because the inherited test parser allowed
only 512 or 8192 update records, not the new warm control's 128. No G/R
execution or hardware failure occurred. The fix adds an explicit opt-in
128-record native-partition input scope to the handoff caller. Existing
callers retain their original defaults. UBSan unit checks cover this boundary
and the SSSP seed, fallback, invalid-input and convergence rules.
The v3 rerun preserves all eighteen original handoff non-timing results and
adds nine warm-control rows. The unchanged original G-only scope is rerun
separately, rather than inferred from successful compilation.

v3 host compilation and execution take about eleven seconds overall, with
roughly 395 MiB maximum compiler-process RSS recorded by `wait4`, not a
simultaneous process-tree sum. Each step is bounded by a
4-GiB cgroup, 3-GiB high watermark, no swap, 900-second timeout, CPUs 124--125
and a 104-GiB available-memory reserve. These are verification resource
measurements, not FPGA performance. Other FPGA tools need not exit when the
full concurrent budgets fit.

## Code And Reproduction

Code owners are under
`cpp/tests/evaluation_impact/common_g/continuous_handoff/` and
`spine_cycle_sim/experiments/evaluation_impact/common_g/continuous_handoff/`.

| File | Responsibility |
| --- | --- |
| `resident.hpp`, `resident_test.cpp` | Net-edge seed/fallback semantics, synchronous reference and independent shortest-path oracle |
| `compute.hpp` | Native single-partition R ABI, resident state, direct PMA handoff and convergence loop |
| `control.cpp` | Three-batch orchestration, explicit timing boundaries and raw events/results |
| `preparation.py` | Freeze production preparation, ABI sources, native inputs and declared warm controls |
| `study.py` | Bounded unit/host compilation and complete host-model matrix |
| `analysis.py`, `delivery.py` | Reject incomplete scope or promoted claims; reanalyze and seal raw evidence |

From the simulator repository root:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_handoff.study --help
python3 -m unittest tests.test_grasu_continuous_handoff tests.test_grasu_continuous_handoff_delivery
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_handoff.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/continuous_handoff/host_evidence"))'
```

Supply a fresh `--output`, the original GraSU kernel `--upstream`, production
HLS `--integration`, and installed `--xrt`. Use an enclosing user systemd
service with 6-GiB hard/5-GiB high/no-swap limits and a bounded lifetime. Raw
attempts are under
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.

Do not invoke `probe --board` manually to bypass admission. The full-new-G
route remains a separate running experiment. The adapter-only link generated
an xclbin but failed final HBM setup timing at -0.032 ns; it is neither an
admitted board image nor a substitute for the new-G route.
