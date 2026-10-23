# Fresh Figure 8--9 Comparison Data

This is a new simulator-only diagnostic, not a replacement for the frozen
Figures 7--11 handoff. The paper and historical figure package are unchanged.
Read `data/summary.json` for the completed coverage and `data/missing.csv` for
unsupported or failed pairs. Missing values are not projected or copied from
the old evaluation. No new FPGA timing calibration is claimed.

The data and conclusions below describe the preceding frozen SSSP-only
collection. The separate [three-algorithm extension](multialgorithm/README.md)
now supplies nine fresh Figure 9 pairs, including the six previously missing
CC/ResPR pairs and a same-model SSSP rerun. It retains a negative ResPR result
and does not retroactively change this collection's Figure 8 measurements or
baseline-admission status. See its [completion plan](MULTIALGORITHM_PLAN.md)
and test report for the scope and retained failures.

**ResPR threshold correction:** that extension used `epsilon=1e-5/V`, not
the historical fixed per-vertex `epsilon=1e-6`. A separate
[fixed-threshold rerun](respr_fixed_epsilon/README.md) restores the historical
activation/stop setting on both arms. The strict-threshold collection remains
frozen evidence, not the result at the historical precision.

**Nonempty ResPR propagation:** the separate
[historical-input follow-up](respr_propagation/README.md) reruns Flickr u8 and
the AskUbuntu 540K/904K reciprocal u8 inputs with the current model and fixed
`epsilon=1e-6`. All three propagate real work; G+R is faster on all three.
These results must accompany the zero-active AU/SU/WK threshold-restoration
results when discussing whether sparse updates provide a latency advantage.

**Sparse Apply candidate:** a separate
[dense/sparse controlled follow-up](respr_sparse_apply/README.md) adds a
finite, timed tile-local bitmap to Spine ResPR. On the same nonempty inputs,
G+R/Spine changes to 0.630 / 11.572 / 15.069 for FL / AU540 / AU904. The dense
default exactly reproduces the preceding collection, and G+R is unchanged.
Final ranks and per-round active vertex sets match; tiny Flickr residual
differences and a post-hoc diagnostic comparison tolerance are explicitly
reported. This is a simulator architecture candidate, not routed HLS timing
or an admission of original-publication G/R performance.

## Completed Results

Seven Figure 8 pairs and three Figure 9 SSSP pairs pass correctness and
drained-memory-ledger checks. Six Figure 9 CC/ResPR pairs remain unsupported,
not numerically zero. This is a **completed supported-scope diagnostic**, not
a complete three-algorithm replacement evaluation or an admitted G+R baseline.

| Figure 8, one 512-update batch | Historical speedup | Fresh setup-inclusive speedup |
| --- | ---: | ---: |
| AU | 11.241 | 3.416 |
| SU | 10.367 | 2.707 |
| WK | 18.480 | 8.801 |
| SO | 18.939 | 4.494 |
| PK | 6.090 | 1.315 |

The AU 64/512/4096 sweep gives 3.099 / 3.416 / 3.270 times. The direction
survives this diagnostic, but it is **not an update-kernel speedup**. On all
five 512-update cases G has fewer device update cycles than Spine; initial
layout construction dominates the setup-inclusive comparison. Device time
is 0.010--0.454% of Spine total and under 0.023% of G total in those cases.
These results must not be generalized to resident multi-batch throughput.
Compared with the historical table, the advantage is smaller on every case.
The new CPU window includes the actual Spine graph/directory/metadata image
constructor and G's complete reservation/layout plus batch packing; it must
not be confused with the preceding demo's partial batch-only CPU audit.

| Figure 9, SSSP | Spine accepted bytes | G+R accepted bytes | Byte ratio G+R/Spine | HBM energy ratio G+R/Spine |
| --- | ---: | ---: | ---: | ---: |
| AU | 25,640 | 131,533,104 | 5,129.996 | 21.344 |
| SU | 23,780 | 164,468,504 | 6,916.253 | 28.145 |
| WK | 33,512 | 42,402,972 | 1,265.307 | 18.784 |

All three Spine byte totals equal their historical counterparts; R's new
layout and request path change its traffic. Model HBM energy is **not** a
per-byte rescaling: standby/refresh account for 99.2--99.6% of Spine energy
and 89.5--94.0% of G+R energy in this all-budget-channel accounting. The shorter
new G+R device windows and the changed energy scope explain why a surviving
traffic advantage does not preserve the old thousand-times energy ratios.
This collection does not isolate the relative contribution of each change.

## Data And Boundaries

| File | Meaning |
| --- | --- |
| `data/fig8_update_cross_dataset.csv` | One 512-update insertion batch on AU/SU/WK/SO/PK, where both arms complete |
| `data/fig8_update_batch_sensitivity.csv` | AU at 64/512/4096 updates per batch |
| `data/fig8_arms.csv` | Absolute device cycles, measured host preparation, logical transfer sizes, modeled setup and throughput |
| `data/fig9_memory_energy_rows.csv` | New SSSP pairs on AU/SU/WK: accepted bytes and modeled HBM energy |
| `data/fig9_arms.csv` | Absolute read/write bytes, cycles, rounds and DRAMSim3 energy components |
| `data/old_new_comparison.csv` | Historical and new ratios with explicit comparability limitations |
| `data/missing.csv` | Every unsupported algorithm or incomplete pair, with no fabricated numeric value |
| `evidence/index.json` | Hash-indexed portable reports, logs, source snapshots and external raw paths |
| `evidence/evidence.tar.gz` | Self-contained raw/configuration/state capsule, excluding external large inputs and tool binaries |
| `data/harness_equivalence.json` | Exact replay of twelve old input/result/full-state identities |

Figure 8 follows the old **setup-inclusive update-only** accounting convention:

```
T = median(host layout + batch preparation)
  + (logical initial upload bytes + batch upload bytes) / 12 GB/s
  + 10 us launch/synchronization
  + update-only device cycles / 150 MHz
speedup = T_G / T_Spine
```

The host median uses five Release CPU repetitions pinned to one CPU. Parsing,
input validation, independent oracles, runtime buffer allocation and readback
are outside that host window. Initial layout construction and logical initial
upload are included once for this **one-batch** comparison. This is not a
resident steady-state throughput result or a ten-batch amortized result.
Spine preparation runs the actual maintenance constructor to build graph
payloads, row/page indices, family directories and slice metadata, not just
edge sorting. A test-only linker wrapper counts those actual payloads while
suppressing simulator backend page-map storage; normal timed device runs use
the real backend. Its small scratch-port/constructor bookkeeping remains in
the measured CPU time. This is a simulator-side image-generation benchmark,
not a measurement of the native FPGA host application. G preparation includes
PMA reservation/layout generation and the shared shard/lane batch packer.
The arm CSV's graph/directory/metadata breakdown is Spine-specific; zero in
these columns on G does not mean G has no metadata. G's complete logical
initial upload is retained separately.

Logical uploads are not padded XRT BO transfers. Batch upload follows the
historical canonical 16-bytes/update convention on both arms, not each native
runtime's padded allocation or seed-buffer DMA. The transfer bandwidth and
launch term are explicit assumptions, not fresh measurements. Device propagation is outside
Figure 8 on both arms; only GraSU, not ReGraph compute, runs in its G+R arm.
The per-arm CSV keeps setup and device contributions separate so an overall
advantage cannot be mistaken for a faster update kernel.

Figure 9 starts both systems at the same independently converged old SSSP
state, applies the same eight insertions, and requires complete new-graph
convergence against independent Dijkstra. Initial graph/result preload is
outside both device windows. G physically edits the resident PMA subsequently
read by R; no host graph rebuilding is permitted between them. All accepted
memory bytes in update plus propagation are counted. Host CPU/DMA/launch and
orchestration are excluded from the energy window.

The resident PMA is reserved using the exact future insertion batch, including
empty source-0 rows needed by the R ABI. Figure 8 charges that reservation's
CPU work in setup; Figure 9 excludes it with the initial preload. Thus Figure 9
is a **conditional fixed-reservation replay**, not a test of arbitrary online
growth or rebalancing. Its old converged values and initial source-seed state
are prepared before the device window. These favorable baseline conditions
must remain visible when interpreting the result.

The historical SSSP sources are AU=11, SU=23, WK=0. Original physical vertex
IDs and complete materialized input files are retained. Earlier attempts using
manifest-default roots are indexed but superseded, not mixed into the final
Figure 9 table. Sources and complete input hashes are in each run report.

## Exact Model Identity

- Core libraries are reused only after source/compiler/library hash validation
  against the Gather-reuse run and its 37 passing numerical-core tests. The
  fresh SST harness and direct DRAMSim3 bridge are compiled with
  `-O3 -DNDEBUG -std=gnu++20 -fPIC`. This is not a rebuilt production plugin.
- G uses natural 64K-vertex destination shards, finite parallel search,
  64 search contexts, 32 metadata credits, shared metadata and direct physical
  segment read-modify-write. It **does not** use the separately tested
  full-cache/copied-metadata G prototype; that prototype is not integrated
  with this natural-geometry common-warm path. These results do not establish
  original-G timing parity or complete baseline admission.
- R selects the default-off `prefetch_gather_reuse` candidate, including its
  finite input and shared-backend schedule. This `RoutedReGraphSystem` simulator
  candidate currently supports **SSSP only**. The six CC/ResPR pairs from old Figure 9
  cannot be regenerated with this same model and are explicitly unsupported.
  Reusing their old rows would conceal a different baseline implementation.
- Spine uses Candidate10 one-pass maintenance, device-active propagation,
  owner scheduling, segmented fallback, and the existing 520-cycle reader
  control / 3,185,887-cycle fallback-setup assumptions. No new timing fit or
  multiplier is introduced by this data collection.
- Both arms use 150 MHz and direct timing-feedback DRAMSim3 with the same
  32-channel budget, 512 MiB per channel, and 32 outstanding backend requests
  per channel. Physical port/storage layouts still differ. In particular,
  candidate R has 16 masters/three state replicas versus original A4's
  13/four; this study does not assert strict resource equality.

The backend adapter and warm harness extraction are checked against all
twelve preceding common-warm executions: complete state hashes, cycles,
traffic counters and registration-order controls must remain identical when
the original mock backend is selected. See the retained equivalence report.
Every selected Figure 8 Spine row additionally checks the post-update physical
edge/index payloads and slice publication headers against the reconstructed
resident image, outside the timed device window. Export rejects rows lacking
this check or complete five-sample image/batch preparation.
This physical check covers live edge/index payloads and occupied-slice headers;
it does not independently validate every persistent family-directory entry,
page epoch/count or cleared empty-slice descriptor. It is not a claim of
complete physical-metadata verification. The follow-up read-only audit found
no remaining host-accounting/export blocker within this narrower scope.

## Energy And Historical Comparison

Energy is DRAMSim3 **total HBM subsystem energy across all 32 budget channels**,
including idle-channel standby and refresh during each arm's device window.
It is not FPGA board power or ASIC core energy. Each pair requires all 32
reports; absolute command and background energies are retained in the arm CSV.

Old Figure 9 reported bound-channel energy from different, calibrated plugin
identities. The new study has a different compute implementation and timed
request trace, uses the current direct memory bridge, and charges all budget
channels. Consequently, old/new energy ratios are **not a controlled ablation**
of R optimization. Likewise, fresh uncalibrated cycles cannot inherit the old
FPGA calibration. The old/new CSV flags this rather than attributing every
change to the adapter. Figure 8 also replaces the old fitted device-cycle
envelopes with current execution-driven predictions and fresh CPU timings.

## Safety And Reproduction

The small-input attempt uses a 6/5-GiB cgroup max/high, 4-GiB child address
limit, zero swap, and 24-GiB live reserve. SO/PK exceeded that child cap, so a
separate serial retry uses 40/36-GiB max/high and a 32-GiB child cap, with the
same reserve. Both require atomic full-budget admission, live watchdogs,
finite per-process timeouts and unique attempt directories. No foreign task
or memory limit is changed. The first compile/library-loading failures and
all resource-limited rows remain indexed.

The accepted rows select Figure 8 AU/SU/WK from `attempt-v9`, SO/PK from
`attempt-v10`, and Figure 9 from `attempt-v7` only. The first four attempts
retain compile/library-loading failures. Attempt v5 retains the original
SO/PK address-space failures and superseded default-root Figure 9 runs;
neither is silently removed. Earlier Figure 8 rows from v5/v6 lack complete
Spine constructor accounting and are superseded. Attempt v8 adds that
accounting and physical-image checks but omits G batch packing, so it is also
excluded. Final v9/v10 include both. They complete with approximately
0.98/27.3-GiB cgroup peaks; v7 completes historical-source SSSP with a 1.5-GiB
peak. All three selected attempts have unchanged source/input/dependency pins,
no failed rows and zero swap. The large-input attempt takes 12 minutes
42 seconds of wall time, distinct from the predicted device time.
The final twelve-execution harness
replay is also included, with exact input/result/state-hash equality to the
pre-extraction run. This is extraction equivalence, not FPGA calibration.

Validation includes six fresh SST smokes in each selected attempt, 37 focused
Python tests, and the exact twelve-execution extraction replay. The 37 numerical
core tests belong to the hash-validated reused core build, not a new test run
or a fresh production-plugin build. Portable verification additionally checks
the archived raw results against the exported CSV and JSON tables.
CSV export uses LF line endings; this packaging-only format change does not
alter the frozen numerical execution sources or values.

The cohesive code owners are:

- `spine_cycle_sim/experiments/evaluation_impact/figure_refresh/`: declared
  scope, bounded runner, validation, comparison and portable delivery.
- `cpp/tests/evaluation_impact/figure_refresh/`: materialized inputs/oracles,
  host measurement, update-only path and direct-memory SST harness.
- `cpp/tests/evaluation_impact/warm_comparison/`: shared complete-convergence
  execution, with the old wrapper preserved for exact replay.

Run from a simulator worktree, using fresh paths and unit names. The retained
reports contain the actual commands and dependency locations. For example:

```bash
systemd-run --user --wait --pipe --collect --unit=figure89-small-rerun \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=7200 --working-directory="$PWD" \
  /usr/bin/python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.study \
  --reference /data/chuxiao/experiments/r_gather_reuse_20261022/convergence-v2/results.json \
  --output /path/to/fresh-output --cpu 4 --timeout 600 --datasets AU SU WK
```

Use the named `cpu-large-input-40g-reserve24-v1` profile and matching 40/36-GiB
cgroup for SO/PK. Do not just remove address-space limits. Packaging and
verification commands are recorded with the final evidence summary.

For the historical-source Figure 9 rerun, append `--figures 9` and select
AU/SU/WK. For only Figure 8 use `--figures 8`. Reproduce the extraction gate
with the `warm_comparison.study` CLI and the same reference library report.
The collected package can be independently checked without those `/data`
raw paths:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.delivery \
  --output docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure_refresh \
  --verify
```

The packager's `--small`, `--large` and `--propagation` arguments take the
selected attempt `results.json` files. `--attempts` takes their common parent,
`--before`/`--after` take the original/final twelve-execution replay reports,
and `--historical` takes the frozen handoff's `data` directory. Package into a
fresh directory; never overwrite a frozen handoff. The verifier checks archive
membership/hashes, exported files, raw numerical markers, selected sources,
closed request ledgers, host repetitions and all 32 energy aggregates.

**Acceptance boundary:** completed correctness/ledger-admitted pairs are new
simulator predictions. This folder does not claim all algorithms are supported,
all original-G/R parity gates passed, or Figures 8--9 are publication-ready.
