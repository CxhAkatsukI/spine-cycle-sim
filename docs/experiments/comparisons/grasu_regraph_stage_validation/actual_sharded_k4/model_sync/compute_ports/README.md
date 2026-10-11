# Compute Extraction And Shared Ports

This checkpoint prepares the **actual K4 compute topology**. It is not the
completed candidate simulator, a new FPGA run, timing calibration, or an
original-A4 performance comparison. The existing v8 topology is unchanged.

## What Changed

The existing Gather, merger, Apply and source-state writer now have separate
implementation files and a small private interface. Their arithmetic and
legacy stage sequencing are retained. The original large file still owns
legacy source service, iteration control and system composition.

`AxiEndpoint` is a non-owning view of request/response queues. It does not
create an AXI master or grant extra bandwidth. Existing callers use views of
their original ports; new composition can instead connect logical clients
through `SharedAxiPort` to **one** physical master.

The shared-port component provides:

- Registered, round-robin request arbitration with a bounded routing table.
- Transaction-ID translation, so independent clients can use the same IDs.
- Bounded response and streamed-read queues with backpressure.
- Separate parent-response and streamed-data completion. A route is retained
  until both are forwarded, even when the parent arrives first.
- Explicit accepted/completed, response, beat, pressure and occupancy counters.
- Rejection of aliased queues, incompatible stream ports and clock domains.

Apply and the source-state writer can now use those clients without copying
their numerical implementation. This removes a structural obstacle to sharing
the actual HLS read/write masters; it does not itself connect the whole K4.

## Evidence

The extraction-only plugin passes the five fixed SST cases against the
previous `fb8c9f0` checkpoint, with **no ignored result fields**. A second
regression checks the endpoint-capable implementation separately.
After correcting the packaging script's case count from 144 to 72 (the latter
already includes both registration orders), the same plugin passes a third
five-case regression under the final source snapshot. Numerical sources and
test executables did not change; `report_count_fix.json` records the distinction.

| Gate | Scope |
| --- | --- |
| Pure extraction | Five cases: exact correctness, cycles, counters and result bytes |
| Endpoint-capable legacy path | Same five-case full-result comparison, separately recorded |
| Shared AXI component | 72 pressure/capacity/registration-order cases, plus invalid-wiring and parent-before-last-beat checks |
| Connected compute | 25 cases across SSSP, CC, FullPR and ResPR; ResPR includes both state layouts |
| Complete core | 18 CTest executables |

Connected tests execute two successive rounds and compare complete primary,
auxiliary and both published source arrays, activation counts, error totals,
request counts and bus bytes against direct ports. SSSP also has a separate
scalar expected-state check. Queue depths of one and four and reversed
component registration are exercised. Timing is deliberately **not** required
to equal the independent-port fixture: shared arbitration changes contention.

The connected fixture stresses all Apply clients on one physical master. That
is a functional stress test, not an assertion that every PageRank HLS bundle
has that layout. Shared source ports in this fixture carry writeback only;
the separate AXI test checks simultaneous read/write clients. The actual
source-read block service is still an integration task.

The machine-readable delivery consists of `compute_ports.json`,
`compute_raw_index.json` and `raw_compute_ports.tar.gz` in this directory.
It retains all three SST regressions, the previous baseline results, source/input
snapshots, build identities, full test reports and failed attempts. The first
extraction build caught a misplaced `override`; a later fixture initially
counted registered-but-unused masters as active. Both failures are preserved.

## Timing Boundary

The new mux admits at most one parent request, one parent response and one
streamed beat per cycle. Routing credit is not released for same-cycle reuse.
It introduces registered queue boundaries when selected. These are explicit
model assumptions, **not** measured Vitis arbitration latency or a calibrated
FPGA cycle prediction. Direct endpoint views introduce no additional queue.

Physical AXI limits remain with the one `FixedAxiPort`; creating more clients
does not create more physical ports or outstanding-burst budgets. A stalled
client can block the head of the physical response queue. That restriction
is visible in the model, not replaced by unbounded per-client buffering.

This request mux is **not** the HLS pairwise source-block scheduler. The
actual wrapper serves frontends (0, 2) and (1, 3), switching only after a
whole source block or terminator. That scheduler still needs its own model.

## Code And Reproduction

Start with the [C++ ownership map](../../../../../../../cpp/README.md).
The owners are:

- `cpp/src/detail/grasu_regraph_compute.hpp`: private stage interfaces and port bindings.
- `cpp/src/grasu_regraph_{gather,merger,apply,writeback}.cpp`: existing compute behavior.
- `cpp/include/spine_sim/axi_endpoint.hpp`: queue view, no timing model.
- `cpp/include/spine_sim/shared_axi_port.hpp` and `cpp/src/shared_axi_port.cpp`: finite arbitration and response routing.
- `cpp/tests/routed_regraph/{shared_axi_tests,compute_ports_tests}.cpp`: pressure and connected-state gates.
- `spine_cycle_sim/experiments/sharded_k4_stages/compute_delivery.py`: evidence revalidation and packaging.

Run from the simulator root, using fresh output directories:

```bash
cmake -S . -B build/k4-compute-review -DCMAKE_BUILD_TYPE=Release
cmake --build build/k4-compute-review -j2
ctest --test-dir build/k4-compute-review --output-on-failure --timeout 120

make -C cpp/sst BUILD_DIR="$PWD/build/k4-compute-plugin-review" \
  DRAMSIM3_ROOT=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729 -j1
taskset -c 112-115 python3 scripts/run_grasu_refactor_regression.py \
  --lib-dir build/k4-compute-plugin-review \
  --out-dir results/k4-compute-review/shared \
  --baseline-dir results/k4-compute-review/before \
  --jobs 2 --case-timeout-seconds 600
```

Extract the archive's `before/` into the fresh result root, or build the pinned
baseline with the same compiler/backend and run the same contract. A changed
compiler or backend requires a new paired baseline. The local campaign is
`/data/chuxiao/experiments/sharded_k4_system_sync_20261011/`.
Builds/tests use finite timeouts and memory limits, SST uses at most two jobs,
and launch admission retains a 16-GiB memory reserve. Neither the paper nor
the figure package nor the frozen `build/sst` plugin is overwritten.

The evidence packager rechecks these gates before creating a new delivery:

```bash
python3 scripts/package_sharded_k4_adapter_gates.py --model-compute \
  --data /data/chuxiao/experiments/sharded_k4_system_sync_20261011 \
  --integration /home/chuxiao/grasu-regraph-integration \
  --output results/k4-compute-review/delivery
python3 -m unittest discover -s tests -p 'test_sharded_k4_compute_delivery.py'
```

## Remaining Work

1. Connect raw adapter packets to independent Scatter and the pairwise source
   service, including known packet counts and end-response drain.
2. Dispatch adapter and gather chains independently; preserve fixed shard
   assignment and the globally ordered mux.
3. Run one shared Apply/HBM lifetime per round, reset Gather every shard and
   account for the round-status write and source/writeback shared masters.
4. Admit a distinct candidate profile with complete-state, traffic and
   convergence checks, then run matched bounded FPGA timing cases.
5. Compare original A4 and actual optimized adapter + modified K4 with matched
   algorithms, initial state, iterations, resources and measurement windows.

The accepted [paired hardware improvements](../../adapter_optimization/BOARD_RESULTS.md)
remain unchanged. None of these component checks proves that the simulator
already predicts those improvements or that optimized K4 matches original A4.
