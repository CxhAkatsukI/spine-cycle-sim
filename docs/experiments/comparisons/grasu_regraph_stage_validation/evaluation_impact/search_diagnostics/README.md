# G Search Progress And Port Diagnostics

## Decision

All 114 read-only diagnostic runs reproduce the preceding concurrency
checkpoint exactly: complete PMA state, cycles, work and physical traffic.
No scheduling, memory latency, port budget or queue capacity was changed.
The complete performance-retention gate remains failed; these observations
are not FPGA counters, timing calibration or baseline admission.

The remaining large-batch gap is in the interval before cache writeback,
with search supplying the last hot update. It is not explained by slower
cache loading or a longer final cache writeback tail. Port observations
motivate an explicit metadata-credit control, but do not prove causality.

## Reading And Scope

- [Complete matrix and diagnostic sidecars](evidence/index.json).
- [Fresh regressions and retained historical identity failures](verification/index.json).
- [Previous 266-row concurrency checkpoint](../search_concurrency/README.md).
- [Overall admission plan](../PLAN.md); G/R composition and Spine remain open.

The declaration retains all nineteen prepared inputs and both 64/128-cycle
memory assumptions. It replays `original_forwarded`, `cached_hot` (sixteen
search contexts) and `cached_hot64` (sixty-four), for 114 executions. The
forwarded original is the separate source-derived reference model, not the
current routed direct-HBM implementation. No case was selected by its ratio.

Every arm uses the same resident full-word PMA and ordered batch. The window
includes complete preload, update execution, writeback, acknowledgements and
memory drain. It excludes host preparation, DMA, launch and graph propagation
on all arms. Clock is 200 MHz; four physical banks have 32 backend credits
each. The original has eight metadata masters per CU; each candidate has one.
Each metadata master retains sixteen parent and burst slots.

## Results

The table reports committed-cycle event positions, **not additive stage
durations**, for the 65536-update mixed input. All other rows remain in the
indexed matrix. `Write start` is the first backend write beat issued for a hot
half, with the table taking the later half's start.

| Latency | Arm | Total cycles | Last search end | Last hot update retired | Last cache loaded | Write start |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 64 | Forwarded original | 1206069 | 939744 | 939380 | 319366 | 939766 |
| 64 | Cached, 64 contexts | 1870537 | 1604179 | 1604173 | 270533 | 1604234 |
| 128 | Forwarded original | 2384885 | 1856361 | 1856356 | 633798 | 1856438 |
| 128 | Cached, 64 contexts | 3635913 | 3107411 | 3107405 | 536837 | 3107466 |

At latency 64, both arms finish 266303 cycles after that write-start event;
at latency 128, both finish 528447 cycles after it. The candidate loads its
cache earlier, but searches finish much later. Its total-cycle ratio remains
1.551 / 1.525, consistent with the previous checkpoint.

Both arms issue 1244416 metadata reads and 9955328 metadata bytes for this
input. The 64-context candidate's single metadata port per CU is at its
parent limit for about 55% / 63% of **all execution cycles**, including cycles
after search completion in the denominator. Merely adding contexts has not
added memory concurrency: it still shares sixteen metadata parent slots.

Do not compare summed original/candidate stall counts as elapsed time.
Original observations aggregate eight ports per CU and can count simultaneous
stalls eight times. The diagnostic stores each port separately and uses
port-cycle denominators. Credit pressure is an observation, not an attribution
of every extra cycle to one queue.

## Event And Integrity Checks

Sampling occurs after every scheduler commit and changes no execution state.
The optional sidecar does not change the existing CLI or stdout result.

- `search_done`: first committed cycle at which each search finishes.
- `cache_loaded`: complete hot-cache preload, not the first returned line.
- `first_hot_update` / `last_hot_update`: retired cache edits, not accepted
  input tokens. Original and candidate use the same retirement boundary.
- `write_started`: first backend-issued write beat, not parent acceptance.
- Metadata pressure: pending parents sampled per port, including a staged
  parent where the AXI interface exposes it. One staged entry above the
  configured limit is allowed; it is not an extra backend credit.
- Final port records: physical bytes, accepted/completed requests and beats,
  credits, FIFO/backend/reorder stalls. All requests and beats must drain.

Cold retirement markers are deliberately absent: the existing original cold
acknowledgement counter mixes reads and writes. Full cold state, work and
traffic remain checked. Accepted cold updates must not be called completed.

Analysis rejects incomplete/duplicate declarations, changed old observations,
missing or inconsistent markers, changed traffic, undrained ports, unsupported
resource changes and promotion of hardware/publication admission. Packaging
checks sidecar hashes and parsed content against the recorded matrix; tests
reject both byte tampering and a changed sidecar with a recomputed hash.

## Ownership And Reproduction

Read-only core accessors live in `cpp/include/spine_sim/grasu.hpp` and
`cpp/src/grasu.cpp`. The optional sampler belongs to
`cpp/tests/evaluation_impact/common_g/diagnostics.hpp`. Declaration, analysis
and delivery have one owner at
`spine_cycle_sim/experiments/evaluation_impact/common_g/search_diagnostics/`.
They reuse the shared bounded runner and evidence packager.

```bash
cmake -S . -B /path/to/fresh-core -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build /path/to/fresh-core -j1
ctest --test-dir /path/to/fresh-core --output-on-failure -j1

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_diagnostics.study \
  --output /path/to/fresh-matrix --core-build /path/to/fresh-core/cpp \
  --previous /path/to/frozen-266-row-concurrency/results.json

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.search_diagnostics.delivery \
  --output /path/to/fresh-evidence --matrix /path/to/fresh-matrix/results.json \
  --previous /path/to/frozen-266-row-concurrency/results.json

python3 -m unittest tests.test_grasu_search_diagnostics tests.test_common_g_runner -v
```

Runtime artifacts are under
`/data/chuxiao/experiments/baseline_evaluation_impact_20261012/g-search-diagnostics-v1/`.
The pre-edit source archive and manifest retain the exact baseline. Core and
matrix runs are serial, limited to 1 GiB address space with an 8-GiB admission
reserve. Matrix steps peak at 341672 KiB process RSS and total about 407 seconds
of subprocess wall time. Source/input/binary pins are checked at completion.
Heavy HLS/routing queues keep their existing separate admission thresholds.

Fresh core regressions pass all 31 targets; the focused Python suite passes
97 tests. A fresh SST plugin passes both default smokes with exactly the prior
JSON outputs. These are compatibility checks, not candidate timing calibration.
The historical frozen-identity suites retain the same 30 mismatched
subassertions in sixteen tests, with no newly mismatched paths. Their failures,
earlier test attempts, logs and resource records remain in the verification
archive; frozen manifests were not rewritten.

## Next Control

Keep these arms frozen. Test explicit larger metadata-parent/burst/FIFO budgets
on the same single master, with unchanged contexts, physical banks, issue
bandwidth, memory timing and cache. Predeclare the complete input matrix and
verify all old observations exactly. Resource increases must appear in the
port ledger and later HLS evidence; they are not a fitting coefficient or a
claim that current routed hardware already contains those buffers.

Only after that control should a new hardware-feasible G path be selected.
The production G gate, original-publication timing, actual G-to-adapter/R
handoff and host window remain open. No paper or frozen figure is modified.
