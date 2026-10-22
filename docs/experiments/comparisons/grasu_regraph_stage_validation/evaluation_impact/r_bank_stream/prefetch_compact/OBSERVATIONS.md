# Read-Only R Wait Observations

## Scope

This checkpoint observes the existing complete-convergence comparison in
[CONVERGENCE.md](CONVERGENCE.md); it does not optimize its timing. The original
A4 control, unchanged bank stream and experimental compact input retain their
memory latencies, finite resources, physical inputs and warm-state boundary.
No HLS, FPGA build, board test or paper is changed.

The purpose is to distinguish input/source waits and overlapping downstream
backpressure before selecting another explicit simulator architecture. A
small final tail does not prove that downstream pressure was absent earlier.
Neither correctness nor read-only observation admits performance retention.

**Completed decision:** all twelve numerical rows exactly replay the previous
checkpoint, and all four forward/reverse wait-record pairs agree. Fresh core
and default SST software regressions pass. The best complete R prediction is
still 28,250,210 / 34,809,212 cycles, or 2.591 / 2.197 times strong A4; the
10% retention gate is still failed. The portable
[observation analysis](observations.json) contains the four forward records
and hashes of both complete raw reports. This is a diagnostic checkpoint,
not a new admitted baseline or a replacement evaluation figure.

## Ownership

| Owner | Responsibility |
| --- | --- |
| `cpp/include/spine_sim/routed_regraph_observation.hpp` | Typed cumulative snapshots, independent of the timing configuration |
| `cpp/src/routed_regraph/system.cpp` | Reads component counters without advancing execution |
| `cpp/src/detail/routed_regraph_observer.hpp` | Clocked read-only Apply window predicate; samples committed pre-edge state independently of execution guards |
| `cpp/tests/evaluation_impact/wait_observations.hpp` | Serializes three CSV tables after the scheduler is drained |
| `cpp/tests/evaluation_impact/progress.hpp` | Existing optional progress export; state files and default stdout remain unchanged |
| `cpp/tests/routed_regraph/compact_input_tests.cpp` | Snapshot purity, aggregate conservation and registration-order tests |

The instrumentation adds no issue, response, cache, scheduler or pipeline
operation. Snapshots can be requested during execution; repeated reads must
not change component state or aggregate counters. Full-convergence export is
performed only after completion, outside the state-output directory.

## Counter Definitions

`frontend_waits.csv` contains four cumulative rows, one per frontend:

- `source_waits`: Scatter has a packet but its source-cache window is not ready.
- `edge_waits`: Scatter cannot obtain its next input packet.
- `output_stalls`: a ready Scatter pipeline item cannot enter Gather's queue.
- `pipeline_stalls`: Scatter cannot admit a packet because of capacity or issue interval.
- `request_stalls`: the source-request queue cannot accept a request.
- `packets`, `emitted`, `source_lines`: accepted/completed packets and loaded lines.
- `gather_reset`, `gather_merge`, `gather_drain`: existing Gather phase counters.
- `gather_output_stalls`: a ready Gather row cannot enter the downstream queue.
- `gather_conflicts`: existing Gather bank-conflict observations.
- `gather_rows`: completed Gather rows.

`source_waits.csv` contains one row per source service. It reports accepted
blocks, forwarded lines and terminal markers, parent requests/completions,
blocked response publication, blocked request issue and maximum pending
parents. A block's parent completion and streamed data both have to drain.

`backend_waits.csv` contains one row for shared merger, Apply and writeback.
It reports blocked output, exhausted read/write windows, pipeline-capacity
stalls and observed maximum window/pipeline occupancy. `apply_read_stalls`
counts clock edges with Apply running, a merged burst available, unfinished
input and a full read window, using committed pre-edge state. A dedicated
read-only observer ticks even when Apply's execution guard sleeps. It does
not issue requests, consume a FIFO or alter the guard. Other fields retain
their existing component definitions, not newly inferred exclusive stages.

The first attempt (`wait-observation-v1`) failed one of 36 CTests before the
convergence matrix ran. Its throttled empty graph had identical 323,711-cycle
completion and state under both registration orders, but the old Apply
`read_window_stalls()` returned 286,358 versus 286,373. Its suspended-cycle
bookkeeping depends on when guards refresh relative to FIFO commits. That
legacy diagnostic remains untouched for historical replay and is **not**
exported as the new sampled read-window count. The separate diagnostic in
`wait-diagnose-v1` identifies that field; neither attempt admits performance.

**Wait counters overlap.** A blocked downstream queue can coincide with an
upstream input wait or another frontend's activity. Four frontend counters
may exceed wall-clock cycles when summed. Even a large counter is not the
number of cycles recoverable by removing that condition. Do not stack these
tables into a normalized latency breakdown, call them measured FPGA counters
or substitute them for a controlled before/after optimization.

## Admission Checks

1. Build a fresh Release core and run the complete CTest suite, including live
   snapshot purity and forward/reverse observation equivalence.
2. Re-execute all twelve convergence rows and exactly compare every numerical
   observation, active trajectory and full-state output with the preceding
   compact-convergence checkpoint, not only the eight legacy rows.
3. Require identical completion and wait records under both component
   registration orders, and closed parent/packet/state ledgers.
4. Build a fresh SST software plugin and exactly replay all five historical
   default cases. The experimental input is not selected through SST; this
   is default compatibility, not candidate timing calibration.
5. Verify frozen source/compiler/input/binary identities and retain the finite
   cgroup, zero-swap and live-reserve records. Do not alter pinned source files
   while either campaign is running.

## Completed Findings

These counts span all 46 rounds of the same resident warm SSSP execution.
The old bank stream and compact-input candidate have **identical** backend
counts at each memory latency:

| Overlapping observation | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| Merger output blocked | 459,770 | 6,471,326 |
| Apply read window full with available input | 5,684,910 | 11,753,644 |
| Apply write-window stalls | 2,423,832 | 11,758,658 |
| Maximum Apply read / write parents | 16 / 16 | 16 / 16 |
| Maximum Apply pipeline occupancy | 29 | 29 |

For compact input, the sampled read-window count is about 20.12% / 33.77%
of elapsed cycles. The write count is about 8.58% / 33.78%. Do not add these
fractions: they are overlapping predicates, not an exclusive phase ledger.
Compaction improves the input path without reducing these backend counts.
This does not prove that the backend is the sole critical path.

Each of the two source services issues and completes 5,888 parent requests,
forwards 1,507,328 lines and 92 terminators, and observes at most one pending
parent. Both have zero request-issue stalls. Response publication is blocked
frequently:

| Source response publication blocked | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| Bank stream, service 0 | 1,821,232 | 3,743,618 |
| Bank stream, service 1 | 3,202,520 | 3,489,468 |
| Compact input, service 0 | 9,267,298 | 9,476,000 |
| Compact input, service 1 | 10,999,106 | 12,327,172 |

The source service is therefore often blocked publishing data to its
consumers, not failing to acquire another parent credit. More parent credits
alone are not supported as the next fix by these observations. A larger
publication-stall count does not imply a slower whole execution: compact
input finishes sooner while presenting a different consumer schedule.

The code in `cpp/src/routed_regraph/scatter.cpp` consumes source responses
in its response phase, then processes edges without independently draining
subsequent source lines. The source service also waits to forward a complete
block before selecting its next block. Separating finite cache loading from
edge progress is an explicit architecture candidate, **not implemented or
proven faster by this checkpoint**. It must retain cache-bank ownership,
window/terminator semantics, finite response storage and backpressure.

The registered transport's two-cycle single-client issue interval remains a
separate shared-model question, described in [the reader guide](README.md).
Any change must be applied to and retested on A4 as well. The unchanged
reader's scan floor and unequal destination-shard occupancy remain additional
limitations; a source-cache change alone is not promised to achieve 10%.

## Evidence And Reproduction

Raw root: `/data/chuxiao/experiments/r_bank_stream_comparison_20261022/`.

- `wait-observation-v2/`: fresh Release build, 36/36 core CTests, the
  configuration test and all twelve complete-convergence rows pass. Every
  numerical field and state-file extent/hash exactly replays
  `compact-convergence-v2/`. All eight K4 wait exports close their ledgers,
  and all four registration-order pairs agree. Source/input/compiler/binary
  pins remain unchanged. Runtime is 19 minutes 54.232 seconds.
- `wait-sst-v2/`: a separately built SST **software** plugin exactly replays
  all five default regression cases. No FPGA compiler or board is used, and
  no candidate SST timing claim is made. Runtime is 7 minutes 48.924 seconds.
  `results.json` SHA-256 is
  `725e82a1d6acd697bbb7872db380da9fb87c117df7149eb8f7039e269521b1a7`;
  `legacy/equivalence.json` SHA-256 is
  `ed858ab9be8919c33e9b1ab7dd51b667d1613f67b580e0d4a265854a90f9b21d`.
  The plugin SHA-256 is
  `3921c383f6408fa614b8514a43b317c889e24be4b5c270d9bc3e17f576a85502`.
- `observer-smoke-v2/`: fresh build and eight empty/throttled/multipart
  convergence executions plus framing/restart/rejection checks pass.
- `wait-observation-v1/` and `wait-diagnose-v1/` retain the counter failure
  explained above. `wait-sst-v1/` passed software compatibility but predates
  the independent sampler; it does not replace the v2 gate.

The convergence group has a 20-GiB hard/18-GiB high limit, four workers,
zero swap, OOM group kill and a 90-minute timeout. Its live watchdog observed
1,224,593,408 peak bytes; this is not a claim about the unsampled lifetime
peak. The completed service reports a rounded 1.1-GiB peak. Admission reserves
24 GiB for the system plus 8 GiB for background demand and all bounded peers'
full limits. The separate SST group has 6/5-GiB hard/high, zero swap and a
45-minute timeout; its watchdog observed 1,044,762,624 peak bytes. No foreign
process or memory limit was changed. CPU assignment may overlap between
workers, so simulator wall time is not an exclusive-core host benchmark.

From the repository root, use the complete campaign command in
[CONVERGENCE.md](CONVERGENCE.md), choosing a new unit and output path. Analyze
the completed result against the unchanged pre-observation checkpoint:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.wait_analysis \
  --run /data/chuxiao/experiments/r_bank_stream_comparison_20261022/wait-observation-v2/results.json \
  --reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/compact-convergence-v2/results.json \
  --output /path/to/fresh-observations.json

python3 -m unittest tests.test_regraph_wait_observations \
  tests.test_regraph_compact_convergence tests.test_regraph_bank_stream_runtime \
  tests.test_repository_structure -q
```

The analysis rejects incomplete matrices, changed cycles/traffic/state,
noncanonical or changed CSV tables, unclosed packets/parents and
registration-dependent observations. Wait predicates are observations, not
an invitation to subtract time from the model.
