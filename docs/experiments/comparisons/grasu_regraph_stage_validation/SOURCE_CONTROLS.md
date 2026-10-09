# Upstream Source Controls

## Accepted Checkpoint

Four original-source functional controls passed. This checkpoint establishes
small-fixture state and stream agreement, not device timing, finite-FIFO
correctness, whole-graph original ReGraph execution, or a published-rate match.
The full objective remains active; the [plan](PLAN.md) and
[status table](README.md) identify the remaining steps.

These controls compile the clean pinned author snapshots with Vitis HLS
2024.1 headers and GNU g++ 15.2.0, using `-std=c++17 -O1 -g0`. Original
ReGraph generation runs under Python 3.11. The production HLS repositories
and existing simulator numerical code are not changed.

| Control | Independent checks | Compile / run (s) | Run peak RSS (KiB) |
| --- | --- | --- | --- |
| Original G cache | All 16 banks, first/last cache rows; 224 valid updates over three batches; all 6,291,456 slot observations match sorted-set oracle | 1.957 / 0.704 | 19,608 |
| Original A4 Little | 4L/0B generated source; two source windows, three PR iterations each; 393,216 vertex states and stream conservation | 2.608 / 0.504 | 17,204 |
| Original default Little | Same functional checks with generated 11-way merger; Big paths not exercised by this row | 2.809 / 1.005 | 17,420 |
| Original default Big | Three original Big pipelines; independent cache-request oracle, omega routing, gather and generated merger; offsets 0/65,536, 1,048,576 destination values | 2.859 / 0.805 | 27,068 |

The final run is `results/upstream_stage_controls/source_functional_final_v1`.
The maximum measured compiler RSS was 343,364 KiB. Each process has a 2-GiB
address-space cap and a 128-MiB stack allowance; the runner checks 16 GiB of
additional available memory before launching. Runs are sequential. RSS uses
Linux `wait4`: maximum process RSS, not a simultaneous process-tree sum.
Compile timeouts are 300 s and functional-run timeouts 180 s.

Both Little controls process 257 logical edges per iteration with 264 padded
physical slots, six iterations total. Padding, repeated destinations, RAW
forwarding, upper-bound destinations, source lookahead, integer PR apply and
termination/conservation checks are included. The second source window
starts at vertex 4,096. These are synthetic functional fixtures, not timed
publication calibration or holdout workloads.

The Big control uses source-sorted edges, dummy padding and the original
top-level `bigKernelScatterGather` body. Requests are checked independently
for both cacheline address and destination lane, except unused fields of the
initial broadcast and end marker. All eight omega outputs and the full
524,288-vertex partition are observed, including the highest valid local ID.
Little tests call original stages separately; their memory responses are
prefilled to exercise the original ping-pong protocol. The original Little
top-level concurrent memory-wrapper composition is not yet tested.

## Observation Boundary

The author mergers are free-running `ap_ctrl_none` kernels with no function
return. The test harness observes exactly one complete partition through an
HLS stream delegate, then throws a test-only stop signal. Original merger
bodies are unmodified. This proves that prefix's values and input consumption;
it does not establish reset, indefinite liveness or next-partition behavior.

C-simulation streams are unbounded. `SW_EMU` enables the author's gather
initialization. Prefilled responses do not model DDR/HBM latency, outstanding
requests, bandwidth arbitration, FIFO backpressure or kernel/host overlap.
The recorded wall times are execution costs only. The report deliberately
leaves `device_cycles` and `publication_rate_error_pct` null.

## Resource Implications

The GraSU paper/source geometry difference is confirmed, not a word-size
conversion. In Section 6.1 the paper specifies length eight, four bytes per
entry, and a 32-byte PE buffer. Its inspected PDF SHA-256 is
`f0604446fe12b9aaad9249b7064ccea47bdc455db4d2f75e9808398317ceff5c`.
The pinned source defines `SEGMENT_SIZE=16`, and `process_1` compares sixteen
32-bit destination slots within a 512-bit value. Upstream `host.cpp` lines
140--158 allocate 32-bit device slots and convert the host's 64-bit records.
Therefore both sides refer to 32-bit device entries: paper 8/32 B versus
source 16/64 B. The source-pin file retains the earlier open question as a
historical snapshot; this finding supplies its resolution.

This checkpoint validates `G-source16`, not `G-paper8`. Keep both
configurations explicit in the next timing study. The paper-8 control must
account for search, placement, cache capacity and transfer granularity; merely
changing a macro is insufficient because the upstream kernel hardcodes
sixteen comparison slots and 512-bit segments. No performance penalty or
benefit is inferred from geometry alone.

The generated 4L/0B connectivity contains four edge ports on HBM 0/2/4/6,
four source-property read/write bundles on HBM 1/3/5/7, and PR outdegree on
HBM 30. It contains no active Big connection. This is nine bank assignments,
not the current integration's complete channel contract.

Each original Little has eight gather lanes, each with a 65,536-value buffer:
2 MiB of logical destination storage per Little, 8 MiB for four. Its replicated
source ping-pong buffers contain 256 KiB per Little, 1 MiB for four. These are
source array sizes, not synthesized area or RAM-utilization results.

The original Little merger consumes one 64-bit partial from each pipeline
per loop iteration, merges two vertices, and packs eight iterations into one
512-bit output. This is a source-level scheduling target, not a demonstrated
effective II. Big has a different output/routing path. The relevant memory
interfaces do not explicitly specify an outstanding-request budget; tool
defaults must be recovered rather than assumed to be the current port's 16.

Consequently, four current PMA frontends and four original Little pipelines
are not interchangeable resource descriptions. B must reuse the admitted
A4 downstream or explicitly report a resource mismatch. A4/B timing cannot
be attributed only to the adapter if gather/merge/apply also change.

For G, the tested original cache kernel preloads and writes back all 131,072
512-bit segments per half: 8 MiB in and 8 MiB out per invocation. This follows
from the original loops; the harness does not measure bus transfers. Both
halves would imply 32 MiB for this cache path alone, before the separate DDR
path. Original per-PE update II is still unresolved; its loop has no explicit
`PIPELINE` pragma, so an assumed one-update-per-cycle model is not admitted.

## Reproduction And Review

Use the commands in [README](README.md). The
[functional contract](../../../../configs/experiments/grasu_regraph_upstream_controls_v2.json)
predeclares both topology and every expected result field. The runner rejects
missing/duplicate records, extra fields, changed values/types and HLS stream
warnings. Compiler dependencies, binaries, generated topology files, input
contracts and orchestration code are hash-recorded. Author snapshots are
checked clean before and after execution. Earlier failed probes are retained
in the raw package, not silently replaced by passing reruns.

[Raw reports and logs](raw_source_controls.tar.gz) include the final passing
matrix and preceding failed/exploratory runs, excluding reproduced upstream
trees and executable files. Archive SHA-256:
`f086261803fd623fbda546ea69fd2e33affb341b9b2ef41730997f64dc97ca42`.
The first Python-3.13 import failure is retained as a separately labeled
reproducer; that initial attempt did not yet have a report writer.

The first generator attempt failed under Python 3.13 because upstream imports
`re.T`. Python 3.11 runs it without editing the source. A subsequent harness
attempt found no `/usr/bin/time`; resource collection now uses `wait4`
directly. A later formatted harness failed compilation due to include order;
the Big invocation now follows its upstream definition. None of these
failures was a model/performance mismatch, and none is an accepted result.

Twelve focused Python tests cover admission, source identity, dependency
hashes, timeout/reaping, memory reserve and output preservation. Six existing
C++ test executables also pass. The earlier 14-case, three-phase exact SST
refactor evidence remains unchanged; this checkpoint adds no numerical-model
edit and does not rerun that matrix or the FPGA matrix. The complete Python
suite is not claimed.

The combined upstream/publication/refactor/organization subset passed
45 Python tests. Both documentation-layout and catalog checks pass. A
[verification record](verification.json) also checks archive contents,
protected evidence hashes and unchanged numerical source identities.

Primary references: [ReGraph author artifact](https://github.com/Xtra-Computing/ReGraph),
[ReGraph paper](https://soldierchen.github.io/assets/pdf/regraph.pdf), and
[GraSU author artifact](https://github.com/qgwang-hust/GraSU). ReGraph's
graph-selected publication topology is separate from the author's default
11L/3B source configuration. Its published CC is Closeness Centrality, not
the connected-components algorithm of our dynamic comparison.
