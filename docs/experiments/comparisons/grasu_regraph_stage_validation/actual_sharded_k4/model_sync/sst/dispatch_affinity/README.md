# WK Dispatch Affinity Control

## Decision

**All nine complete FPGA results pass; more host CPUs do not close the WK
timing discrepancy.** This is a negative control, not timing calibration,
an exclusive-stage measurement, or an original-ReGraph performance match.

The [complete v4 matrix](../empty_exit_matrix/README.md) predicts optimized
WK resident compute at 60.164 ms versus its original FPGA span of 92.622 ms.
Its invocation trace shows substantial same-adapter relaunch gaps. This
follow-up changes only CPU affinity, retaining the admitted host, candidate
bitstream, graph, warm state, update batch and convergence semantics.

| Allowed logical CPUs | Repetitions | Median FPGA compute span (ms) |
| --- | ---: | ---: |
| 122--123 (2 CPUs) | 3 | 94.319 |
| 116--123 (8 CPUs) | 3 | 92.467 |
| 96--127 (32 CPUs) | 3 | 95.479 |

Each arm uses a nested set of distinct cores on the same socket. The arms
rotate each repetition; only one board job runs at a time, on device 1.
All nine spans lie between 90.560 and 98.914 ms. All successor adapter and
whole-lksg events were already queued before their predecessors ended.
Worker 0's median adapter-gap sums remain 30.165, 27.326 and 30.088 ms.
Those overlapping per-worker gaps must not be added together or subtracted
from the total to manufacture a calibrated device time.

The result rules out the simple explanation that allowing only two host
CPUs caused the discrepancy in this control. It does **not** prove the
runtime's root cause, remove host overhead, or exclude physical memory and
downstream backpressure effects. Three repetitions are descriptive evidence,
not a statistical or causal certificate. No model coefficient, HLS source,
memory setting or input layout changed.

## Evidence And Reproduction

[dispatch.json](dispatch.json) contains the revalidated report and complete
output hashes. [dispatch_raw_index.json](dispatch_raw_index.json) seals
[raw_dispatch.tar.gz](raw_dispatch.tar.gz), which contains all nine event
logs, run environments, process records, attempts, manifests and runner
source. The nine identical full result files remain externally hash-indexed
instead of being duplicated; their equality was checked during execution
and again during packaging. The earlier complete-matrix package is a pinned
dependency. The graph, host and xclbin must be restored at their recorded
hashes to rerun the board control.

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.dispatch_sweep \
  --integration /home/chuxiao/grasu-regraph-integration \
  --reference /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/paired_wk_sssp_candidate \
  --output /absolute/fresh/dispatch_control \
  --cpus 122,123 --cpus 116,117,118,119,120,121,122,123 \
  --cpus 96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127
```

Use available, strictly nested CPU sets when relocating; that is a new
control, not a replay of these affinities. Each child is capped at 8 GiB
and 600 seconds with a 16 GiB reserve. Peak recorded process RSS is
1,404,728 KiB; total child wall time is 45.424 seconds. RSS is the maximum
individual process value, not the simultaneous process-tree sum.

Execution/analysis is owned by `dispatch_sweep.py`; immutable validation
and packaging by `dispatch_delivery.py`, in the study's existing Python
package. The next diagnostic must examine runtime dependencies without
treating a profiler-perturbed run as a new performance result.
