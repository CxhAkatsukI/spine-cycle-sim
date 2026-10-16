# Full-Graph Host Readiness

## Scope

This is an offline prerequisite for the later FPGA matrix, not a hardware
measurement or a GraSU/ReGraph publication-performance comparison. It compiles
the unchanged current production host for SSSP, CC and residual PageRank and
uses its existing `--prepare-only` branch. That branch returns before device
selection, OpenCL context creation or FPGA programming. No bitstream is passed
to these commands. Neither a timing model nor production HLS is modified.

The frozen matrix is the complete 24-input insertion/u8 manifest at
`/data/tmp/chuxiao/fullgraph_fpga_workloads_20260806/manifest.json`:

- AU, SU, WK, SO, PK, LJ, LJ08 and R19, with no topology/ID compaction.
- SSSP and ResPR have eight physical edits; reciprocal CC has sixteen.
- Hosts retain their declared old-graph/reference convergence policies.
  Preparing a CPU reference is not proof of FPGA convergence or correctness.
- FullPR, deletions/fallback, larger batches, continuous multi-batch hardware
  and original-paper reproductions are outside this preparation check.

## Execution And Acceptance

The owner is
`spine_cycle_sim/experiments/evaluation_impact/fullgraph_readiness/`:
`preparation.py` owns identities, the fixed matrix and compilation commands;
`study.py` owns bounded execution; `diagnostics.py` reviews structured compiler
output; `analysis.py` accepts only the offline output contract. The CLI is
`python3 -m` on that package.

The host build preserves full `GRASU_MAX_CACHE_SEGMENT=131072` capacity and
enables `GRASU_REGRAPH_HOST_ROW_LINE_READ=1` for the optimized adapter layout.
It records the compiler version, flags, affinity, frozen sources, dependency
headers, binaries, Python interpreter and imported experiment runners. A clean
production worktree is required. Initial, post-admission and final SHA-256
checks cover all inputs. Small files are also hashed between steps; large-file
path/inode/size/mtime/ctime checks avoid repeatedly reading the full graph
matrix during memory polls. A final hash failure rejects the whole study.

Three six-partition correctness smokes precede the large matrix. Any smoke
failure stops full-graph execution. A large-case failure remains in the report
and the remaining predeclared rows are attempted. Each child has separate raw
stdout/stderr, command, timeout and resource records. Acceptance requires:

1. All 24 distinct graph/algorithm pairs attempted and passed, not 24 copies
   of one passing row; all three smokes passed first.
2. Exact input dimensions, physical-update conservation, converged CPU oracle,
   local-dst19 destination sharding, four frontends/shared downstream and a
   consistent PMA slot ledger.
3. The production runtime planner succeeds at full capacity. SSSP/CC also
   explicitly print and check 23 graph channels, at most 512 MiB per channel,
   and resident old-converged state. ResPR's prepare line does not print those
   channel maxima; its frozen planner checks capacity internally. No additional
   direct measurement is inferred from missing fields.
4. No unreviewed compiler diagnostics, runtime diagnostics, board-execution
   output, pin drift or safely stopped child.

Compilation retains `-Wall -Wextra -Werror` and requests GCC JSON diagnostics.
An empty array is accepted, as is one exact `note` from `CL/cl2.hpp` saying the
header has been renamed to `opencl.hpp`. That reviewed upstream header message
is retained in raw stderr and `compiler_diagnostics`, not suppressed. Any other
note, warning, error, nested diagnostic, duplicate, malformed JSON or stdout
fails before smokes or graph preparation. The unchanged production source and
its dependency headers remain hash-pinned; no source rewrite is used to remove
the message.

The only successful decision is
`FULLGRAPH_HOST_PREPARATION_PASS_NOT_BOARD_OR_PERFORMANCE`.
`board_programmed`, `hardware_timing_measured`, `publication_match` and
`production_baseline_admitted` remain false. Correct physical new-G metadata
binding, G-to-R handoff, routed timing and measured convergence still require
the actual hardware gates.

## Memory And Reproduction

Use a fresh output directory and an exact 24-GiB hard cgroup, finite high limit,
zero swap and group OOM kill. The atomic shared lease reserves this entire
budget, every other bounded build's complete budget, and a 32-GiB system
reserve. Unknown/unbounded peers prevent admission. Other FPGA tools need not
exit: two 40-GiB peers give a 136-GiB admission threshold, while one gives
96 GiB. Waiting is bounded to 18 hours by default and holds no reservation.
After admission a live-memory/process-tree watchdog guards every child.

Three host compilations run sequentially (300 seconds each), followed by
sequential smokes and full-graph preparations (1,800 seconds each). No graph
parallelism is assumed safe. OOM, timeout and watchdog stops are failures,
not projections or capacity passes. The whole service also has a bounded
lifetime. A unit termination must be read alongside the last saved report;
`RUNNING` is never a completed result.

Example, from the simulator worktree:

```bash
systemd-run --user --unit=spine-fullgraph-readiness-20261016-v1 \
  -p MemoryMax=24G -p MemoryHigh=22G -p MemorySwapMax=0 \
  -p OOMPolicy=kill -p CPUQuota=200% -p RuntimeMaxSec=151200 \
  -p TasksMax=256 -p KillMode=control-group -p TimeoutStopSec=30 \
  --working-directory="$PWD" \
  /usr/bin/taskset -c 116,117 /usr/bin/python3 -m \
  spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness \
  --integration /home/chuxiao/grasu-regraph-integration \
  --manifest /data/tmp/chuxiao/fullgraph_fpga_workloads_20260806/manifest.json \
  --xrt /opt/xilinx/xrt --hls /data/yxx/tools/xilinx/Vitis_HLS/2024.1 \
  --output /data/chuxiao/experiments/baseline_hardware_validation_20261015/fullgraph-host-readiness-v1
```

Read `results.json`, `raw/*.stdout.txt`, `raw/*.stderr.txt` and
`raw/*.resources.json` under the
attempt directory, plus the systemd terminal result. Keep an unsuccessful
attempt intact and choose a fresh output path for a retry.

## Checkpoint

The readiness runner has twenty-two focused unit tests, including immediate
admission with another FPGA tool running, memory-wait timeout, drift, smoke
failure, full-case failure retention, exact matrix coverage and strict compiler
diagnostic classification. Mocked runner
tests do not compile hosts, operate FPGA hardware or validate large graphs.
The first live attempt is `fullgraph-host-readiness-v1` under the campaign
root in the reproduction command above. It freezes simulator revision
`7a2165b` and production revision
`6f5ebf2b0679f04f4f6e035e850fce7b6043a660`. Its service is
`spine-fullgraph-readiness-20261016-v1.service`, invocation
`f75292d58f964a2689a6d0941567f22a`.

At the 2026-10-16 02:03 UTC checkpoint, the queue reports
`WAITING_FOR_MEMORY_NOT_FOR_OTHER_TOOLS_TO_EXIT`, with no child compilation,
smoke or full-graph preparation launched. Available memory is approximately
90--95 GiB, below the two-peer 136-GiB threshold. Separate container FPGA
processes also fail the finite-budget/zero-swap admission check; their
processes and limits are not changed by this study. The already admitted G
and original-R builds continue concurrently. This is a launch checkpoint,
not a full-graph preparation pass. Read the live report for subsequent state.

The v1 attempt was subsequently admitted and stopped at its compiler-output
gate at 2026-10-16 02:39 UTC. Compilation exited successfully; the only stderr
was the upstream `CL/cl2.hpp` rename note. No smokes or full-graph cases ran.
The failed attempt is preserved. The fresh v2 attempt uses structured diagnostic
review and otherwise keeps the same production revision, matrix, memory policy,
compiler optimization and offline-only boundary. A queued v2 is not a pass.
