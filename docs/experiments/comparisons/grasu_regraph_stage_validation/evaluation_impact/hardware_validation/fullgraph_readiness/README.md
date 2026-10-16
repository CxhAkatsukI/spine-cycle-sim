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
`study.py` owns bounded execution; `analysis.py` accepts only the offline
output contract. The CLI is `python3 -m` on that package.

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
4. No diagnostics, board-execution output, pin drift or safely stopped child.

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

The readiness runner has sixteen focused unit tests, including immediate
admission with another FPGA tool running, memory-wait timeout, drift, smoke
failure, full-case failure retention and exact matrix coverage. Mocked runner
tests do not compile hosts, operate FPGA hardware or validate large graphs.
The first live run is separately indexed in the parent campaign guide after
launch; no full-graph preparation pass is claimed by this document.
