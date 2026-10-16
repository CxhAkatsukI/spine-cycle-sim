# Production-Source Board Qualification

## Scope And Decision

This is the board entry point for the fresh production search/cache exports in
the [production route](../production_routing/README.md), not the older diagnostic
route. The candidate gate replays all 2485 frozen inputs, checks the thirteen
owned source/configuration members and requires the exact two reviewed XO
digests. It does not add a diagnostic-only identity flag to the production
manifest to make the older gate accept it.

At the 2026-10-16 09:48 UTC checkpoint, the entry point has passed fourteen
focused Python tests, 64 existing continuous-path tests, thirteen metadata
tests, eighteen native-board tests and fifteen organization tests. Document,
catalog and whitespace checks also pass. These are mocked/unit checks,
**not FPGA execution**. The production
route and metadata C++ preflight are still queued; no production board result,
baseline-performance match or replacement figure is claimed.

At 09:52 UTC the bounded board queue started successfully, replayed 2960
source/input pins and reported `WAITING_FOR_EXACT_ROUTE_AND_METADATA_HOST`,
`board_started=false`, with no errors or OOM events. It does not wait for
unrelated tools to exit. The older diagnostic G route was in post-placement
optimization and A4 was in routing; intermediate timing is not final signoff.

| Live owner | Frozen identity |
| --- | --- |
| Simulator board runner | Commit `e392b5e90d0ed0ad82270138d7977ba05f834851`, `/home/chuxiao/spine-cycle-sim/spine-cycle-sim-production-board` |
| Board queue service | `spine-g-production-board-20261016-v1.service`, invocation `d77c1d1100274f14b0c3b5ebe2eb5eae` |
| Production route prerequisite | `spine-g-production-route-20261016-v1.service`, invocation `194a3f0af5c74d408ac4aa494a435970` |
| Metadata-host prerequisite | `spine-g-metadata-refresh-host-20261016-v1.service`, invocation `0810335b222341daacedce97c4be33c2` |
| Raw board attempt | `/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-production-board-supervisor-v1` |

The three preflights under the same raw campaign root are
`g-native-board-host-v1`, `g-metadata-refresh-host-v1` and
`gr-continuous-host-v4`. The selected board is device 0. The service has a
48-hour lifetime and CPU quota 200%, with CPUs 124--125, 256 tasks maximum
and a 30-second group shutdown deadline. Its logs and source worktree are
retained; later documentation commits do not change the live runner.

## Declared Matrices

| Matrix | Inputs and repetitions | Required checks | Boundary and limits |
| --- | --- | --- | --- |
| `native_g` | One five-shard input, three repetitions | Full 131072-segment cache halves; hot/cold updates; every physical PMA word and padding; independent logical-edge oracle | Isolated G correctness, not original-G performance reproduction |
| `metadata_refresh` | One two-generation input, three repetitions | Same OpenCL BOs retained; directory contents refreshed in place; complete PMA/padding after each batch; DMA/kernel event accounting | Single-segment row consumption only; multi-segment binary-search refresh remains untested |
| `resident_gr` | Nine inputs, three repetitions: 27 processes, 81 resident batches | G-produced PMA consumed directly; full state and packet conservation; old converged SSSP state to new batch convergence, including explicit fallback cases | Existing convergence policy and 2048-round bound; not a one-hop comparison or the eight-large-graph matrix |

Each process may contain several resident batches. The total is 33 process
attempts, not 33 independent graphs. All three matrices must pass; missing rows,
changed inputs, timeouts and runtime failures remain failures with raw records.
The existing numerical/event validators are reused without changing timing or
correctness calculations. None of these qualification results alone proves a
match to published GraSU/ReGraph performance.

The metadata host's deliberately stale-directory negative control runs on CPU.
It does not establish a stale-metadata negative control on FPGA. Likewise,
successful board transactions would not be a separate integrated RTL simulation
or a measured ten-stage latency breakdown.

## Version And Artifact Admission

`production_board/route.py` owns the candidate-specific source gate. The shared
`continuous_board/execution/route.py` owns completed-artifact, 22-CU topology
and strict final routed timing checks. Diagnostic callers retain their original
candidate gate; production callers select the new gate explicitly.

The supervisor waits for both exact service invocation IDs: the production
route and the metadata host preflight. A restarted, missing or failed service
cannot authorize programming. A successful service exit is necessary but not
sufficient: final host evidence, artifact identity and routed timing must replay.
The original comparison xclbin, host executables and imported Python owners are
pinned before execution. An independent board lock, idle-device checks,
runtime-library checks and a pre-programming PCIe BDF guard are retained.

The live route manifest has one documented transition: it appends the final
`preflight/results.json` identity immediately before tools start. The queue
freezes every other field and the complete original pin prefix in `request.json`;
only that one verified trailing identity is allowed. Final admission requires
it and then pins the complete terminal manifest. Do not rewrite a frozen packet
or silently substitute an older bitstream.

## Memory Policy

The board supervisor is contained at 8 GiB hard / 7 GiB high, zero swap and
group OOM kill. It atomically reserves its full budget against every bounded
peer FPGA build plus a 24-GiB reserve. Unknown or unbounded peers reject
admission. Other FPGA tools do **not** have to exit if those budgets fit.

The shared per-case watchdog additionally retains its existing 104-GiB reserve;
therefore the supervisor requires at least 112 GiB available before entering
the board matrices. This is a conservative safety floor, not a tool-idleness
condition. Each case has a 600-second deadline, a live memory guard and CPUs
124--125. The supervisor's prerequisite/memory wait is bounded; its systemd
lifetime must also cover the possible 33 case deadlines. Failed runs do not
automatically reset a board or reprogram a replacement candidate.

## Ownership And Reproduction

The cohesive package is
`spine_cycle_sim/experiments/evaluation_impact/common_g/production_board/`:

- `route.py`: exact production identity and completed-artifact admission.
- `experiments.py`: matrix declarations and adapters to unchanged validators.
- `supervisor.py`: exact prerequisite invocations, memory lease and sequencing.

Run only from a new frozen simulator worktree, in the required bounded service,
with `XILINX_XRT=/opt/xilinx/xrt`. Supply fresh output and actual invocation IDs:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.production_board.supervisor \
  --native-preflight /path/to/native-host-preflight \
  --metadata-preflight /path/to/metadata-host-preflight \
  --gr-preflight /path/to/resident-gr-host-preflight \
  --route /path/to/production-route \
  --original /path/to/original-sharded-k4.xclbin \
  --route-unit exact-route.service --route-invocation EXACT_32_HEX_ID \
  --metadata-unit exact-metadata-host.service --metadata-invocation EXACT_32_HEX_ID \
  --output /path/to/fresh-production-board-attempt \
  --device 0 --repeats 3 --maximum-wait 133200 --poll-seconds 30 --execute
```

`request.json` freezes the prerequisites and candidate input packet.
`results.json` retains prerequisite states, admission decisions, source pins,
matrix results, programming attempts and terminal memory events. Each child
folder contains raw stdout/stderr, watchdog records, runtime identity, timing
admission and parsed checks. The only overall passing status is
`PRODUCTION_G_GR_BOARD_QUALIFICATION_PASS_NOT_BASELINE_ADMISSION`; it is not a
publication-performance or full-graph admission.

## Remaining Work

After qualification, separately measure original G versus the actual new G,
original ReGraph versus A4, and A4 versus the actual adapter/modified-R path.
Keep preparation, G, adapter/R and host costs explicit. Only qualified fixed
versions may enter the declared Spine comparison and new Figures 7--11 package.
The paper and historical figure packages remain untouched.
