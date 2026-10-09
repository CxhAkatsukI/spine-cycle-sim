# GraSU And ReGraph Stage Validation

Status: SST/Spine refactor accepted in `51565fc`. Four independent upstream
source-functional controls pass; see [the checkpoint](SOURCE_CONTROLS.md).
Cycle models, admitted publication timing and A4/B integration overhead remain
unfinished. No measured publication match is claimed here.

Independent [HLS scheduling evidence](HLS_SCHEDULES.md) is now available for
the original kernel components, with source/tool/platform and compatibility
differences retained. It supplies implementation constraints for the missing
cycle models; it does not satisfy the publication timing or A4/B exit gates.

The [Little finite Gather/merge checkpoint](LITTLE_FINITE_MODEL.md) now covers
the first independent original-R cycle components. Complete word comparison,
finite-buffer conservation, repeated drain/clear and negative-reference gates
pass. Reader/source memory, Apply/writeback and whole-R timing are still missing;
the complete original-R and A4/B milestones below are not marked complete.

The subsequent [Little memory/frontend checkpoint](LITTLE_FRONTEND_MODEL.md)
now adds edge reads, source-memory service and Scatter. It passes exact original
request-protocol controls, finite pressure/resource sensitivity and old Gather
equivalence. Apply/writeback, Big/mixed scheduling, whole-R timing and the
publication/A4-B exit gates are still open.

The [Little PR state checkpoint](LITTLE_STATE_MODEL.md) adds degree/Apply,
indexed broadcast writeback and three resident A4 ping-pong iterations.
Original-source values and old Gather/frontend regression are checked
separately from model cycles. This does not complete partition/Big/mixed,
publication timing, original G or the matched A4/B/C milestones.

The [original-host input checkpoint](ORIGINAL_HOST_INPUTS.md) now passes full
Amazon and two neighboring inputs under A4 and the artifact's 11+3 example,
with complete edge/capture checks, repetitions and UBSan. Next connect the
admitted multi-partition A4 tasks after auditing per-port parent/burst credits.
Big/mixed device execution and original publication topology/window admission
remain open; successful host preparation is not a completed original-R model.

The [A4 whole-graph checkpoint](A4_GRAPH_EXECUTION.md) now connects those
multi-partition tasks through all acknowledged PR writes. Full Amazon and two
neighboring inputs pass pre-Apply/state/finite-ledger checks, fixed resource
sensitivity, reverse registration, repeated runs and UBSan. Old default
component/source outputs are exact. Next implement connected Big/mixed R and
admit the original publication topology/window and memory timing; this mock
memory result does not complete publication matching or the A4/B/C milestones.

The [Big routing/Gather checkpoint](BIG_ROUTING_GATHER.md) now independently
checks the omega network, eight banked destination arrays, packing and
three-way merge against complete author-source captures. Finite pressure,
repeats, reuse and UBSan pass; all eight whole-A4 rows remain exact. Next add
Big request-dependent source-memory service and connected mixed execution.
This is not whole-R timing admission or a completed A/G/B/C comparison.

The [Big memory/frontend checkpoint](BIG_MEMORY_FRONTEND.md) now separately
passes request, wrapper response and Scatter captures, including original
last-cacheline reuse and finite read/cache/queue ledgers. Source/model UBSan,
repeats and all old component/A4/Big-Gather outputs remain exact. Next connect
the complete mixed scheduler/state path. Publication timing and original
G/A4-B/C gates remain open; partial component cycles are not stage matching.

## Separate Questions

The [connected mixed checkpoint](MIXED_GRAPH_EXECUTION.md) now passes the
11+3 example on complete admitted graphs, including continuous Big groups,
independent indexed merge, all 14 state replicas and exact old regressions.
Original-host publication-tail overflow is rejected; successful execution
uses declared zero-extension. This closes the mixed functional connection,
not publication topology/memory/timing admission or G/B/C completion.

| Path | Question | Required control |
| --- | --- | --- |
| G | Does an isolated original GraSU update model reproduce an admitted published update rate? | Original temporal trace/batches, successful-update numerator, PMA geometry, URAM hot-store/writeback policy, DDR/clock and event boundary |
| A | Does original ReGraph reproduce an admitted original-paper PR result? | Original compact-edge/DBG layout, arithmetic, fixed iterations, graph-selected Little/Big topology, ports/merger/apply and publication clock |
| A4 | What does original ReGraph achieve with four Little and zero Big? | Independent original reader/compute control with a documented common resource budget; functional zero-Big support must be verified |
| B | What overhead does the PMA adapter introduce before/within resource-matched R? | Same logical graph/state/iterations/clock and downstream resources as A4; only the input representation/reader differs |
| C | How do G, B and host orchestration compose? | Distinct event windows and overlap accounting; no double-counting or omitted relaunch/setup work |

Original publication matching and the A4/B resource-matched comparison are
different claims. Four Little is not a reconstruction of a published mixed
four-pipeline configuration or a 14-pipeline throughput result.

## Execution Gates

1. Pin upstream source versions and exact paper anchors using the preceding
   [source audit](../grasu_regraph_publication_match/README.md). Recover exact
   input identity, transformation, iteration count and throughput denominator.
   Keep unresolved conditions explicit instead of normalizing them away.
   The confirmed GraSU paper/source geometry mismatch requires separately
   named `G-paper8` and `G-source16` controls; the source-functional checkpoint
   only covers the latter. Do not silently alter the pinned author code.
2. Give original G and original R independent component/source ownership. Do
   not add timing multipliers or hidden baseline modes to the current G+R
   implementation. Keep preparation, execution, validation and analysis apart.
3. Check small functional fixtures against independent per-update/per-iteration
   oracles, stream contents, finite buffers, request conservation and stalls.
4. Predeclare publication calibration/holdout cases and neighboring checks
   before collecting timing or fitting parameters. Record compiler, frequency,
   memory configuration, source/plugin/input hashes and event boundaries.
5. Start with one bounded case per path; measure RSS and simulator wall time
   before scaling. Run processes in parallel only within measured memory limits.
6. Compare G and A independently with their admitted published rates. The
   requested approximately 10% rate-error target is an acceptance threshold,
   not permission to tune a holdout or choose the best result afterward.
7. Compare A4/B per sweep and end to end. Report logical/physical edges, padding,
   PMA occupancy, source/edge/state bytes, backpressure, overlap and cycles.
   Compute the matched-resource overhead from these two measured windows;
   preserve negative overhead if overlap actually improves the path.
8. Only then compose C and separately report host orchestration. Compensating
   G/R errors cannot establish stage validity even if the total time matches.

## Delivery

One documented study folder will contain contracts, code entry points,
source/input identities, raw/indexed results, resource logs, analysis and
reproduction commands. Every comparison must end with a clear status:
accepted match, measured mismatch, timeout, capacity failure, or unresolved
comparability. Missing original workload or microarchitecture evidence is
not a successful match. The paper and frozen figure packages stay untouched.

## Implementation Ownership And Milestones

| Checkpoint | Implementation boundary | Exit criterion |
| --- | --- | --- |
| Source and workload admission | Extend the existing `publication_match` owner; pin upstream revisions and input transformations in one study contract | No unresolved identity, denominator, topology, or timing-window field on a row used for publication matching |
| Original G control | Separate original-G component/configuration, not a direct-HBM flag inside the existing K4 reader | Per-update state oracle, URAM hot-store/read-write behavior, PMA/writeback traffic and bounded smoke pass |
| Original R control A | Separate compact-edge reader, Little/Big pipelines and original merger/apply ownership | Per-iteration state, finite-stream, memory and traversal ledgers pass before any timing comparison |
| Resource-matched A4 | Same original component family with explicit four-Little/zero-Big topology | Zero-Big generation and functional tests pass; ports, buffers, banks, mergers, apply throughput and outstanding limits are listed |
| Adapter integration B | Reuse the admitted downstream resource contract; replace only compact-edge input with PMA adapter input | A4 and B produce identical states on the same graph/iterations; physical work and overlap are reported separately |
| Bounded publication and overhead runs | Thin study CLI over preparation/execution/validation/analysis modules | Full predeclared rows reported, including mismatches and unresolved comparisons; memory logs and immutable run identities retained |

The phrase "four Little" alone does not establish resource equivalence. If
the existing K4 shared downstream differs from original A4, provide a separate
matched control or report that mismatch. Do not attribute all A4/B timing
differences to the adapter while changing gather/apply/merge resources too.

For B, report both end-to-end overhead `(T_B - T_A4) / T_A4` and conserved
extra input work. Adapter and R may overlap, so their isolated elapsed times
cannot simply be added. G completes before B in the selected sequential
integration window. Host preparation/rebin/relaunch is measured separately
and included only in the explicitly named setup-inclusive result.

Start with synthetic correctness fixtures and an admitted common FullPR
case; do not substitute weighted SSSP or Connected Components for ReGraph's
published BFS or Closeness Centrality. Small fixtures establish correctness,
not reproduction of a large-graph published rate. Use adjacent graph/size
checks to expose a coincidental match rather than selecting one best row.

Primary references: [ReGraph paper](https://soldierchen.github.io/assets/pdf/regraph.pdf),
[ReGraph author artifact](https://github.com/Xtra-Computing/ReGraph), and
[GraSU author artifact](https://github.com/qgwang-hust/GraSU).
Source facts and unresolved conditions are indexed in the preceding audit;
new experiments must pin their own inspected source/input hashes.
