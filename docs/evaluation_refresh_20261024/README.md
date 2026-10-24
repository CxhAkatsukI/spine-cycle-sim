# Latest FPGA Figure 7

This is a new, initially partial hardware handoff. It does not change the paper
or overwrite the August figure package. See `data/provenance.json` for the
current number of completed measured pairs out of 24.

## Files

- `figures/fig7_latest.png` and `.pdf`: grouped SSSP/CC/ResPR preview.
- `data/fig7_latest.csv`: successful measured pairs only.
- `data/*_execution.json`: current raw sample records and per-workload failures.
- `data/provenance.json`: coverage, timing boundary and source-report hashes.
- `render_fig7.py`: Python collector and renderer, using the prior GraphyFlow
  handoff's TX Typewriter (`txtt`), colors, hatch density and thin black outlines.

Missing bars mean pending or failed measurements, not zero latency. The source
reports distinguish the two. No timeout estimates or old hardware values fill
gaps. FullPR is not part of this three-algorithm matrix.

## Measurement

Each pair begins with the old graph's converged state and measures the update
batch through convergence and final readback. Host relaunch/orchestration is
included; initial graph allocation/loading and initial convergence are outside
the measured window. Both sides validate against their CPU oracle; the paired
log checker also checks graph/update counts, initial-state and convergence
markers. Each completed workload has one excluded warmup pair and three measured
pairs, alternating architecture order. The plotted ratio is the G+R median wall
time divided by the Spine median wall time. A value below one favors G+R.

The compute clock is 150 MHz on both designs. G+R SSSP uses Vitis's automatically
scaled HBM clock (440.1 MHz in build metadata, 440 MHz in the packaged topology);
the unchanged integer Spine artifact records 450 MHz HBM. These are measured
wall times at each packaged configuration, not equal-HBM-clock or normalized
predictions. The 450-MHz timing-signoff failure is retained separately and does
not prevent these functional/performance tests. Clock topology records are in
each report. Successful CPU checks are not formal physical timing signoff.

Spine SSSP/CC reuse the explicitly recorded integer-core bitstreams whose source
equivalence was inspected. SSSP's historical build commit remains a collector
fallback, not a direct clean-build record. ResPR waits for the newly compiled
sparse-Apply Spine kernel, rather than substituting the older dense PR kernel.
The fresh G+R design uses the prefetch/compact PMA streaming adapter.

## Reproduce

From this directory, with Python/Matplotlib and the installed TeX `txfonts`:

```bash
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python render_fig7.py --campaign /data/chuxiao/builds/gr-prefetch-blocking-axis-trif-20261024/actual-frequency-matrix-v2
python3 -m unittest discover -s . -p test_render_fig7.py
```

Use `--watch` to refresh while the three measurement workers run. Raw host logs,
binary/source pins and resource-watchdog records live under that campaign, with
one algorithm/dataset/sample directory per attempt. This collector does not run
hardware or infer simulator accuracy from FPGA wall times.

The earlier `actual-frequency-matrix-v1` attempt passed AU/SU/WK but its global
`ps` monitor timed out on larger graphs. Its failures and raw logs are preserved
there. Version 2 reruns all eight graphs using dedicated service-cgroup memory
accounting and pidfd cleanup; it does not reuse version 1's successful values.
The 16-GiB service limit and 40-GiB live system reserve are watchdogs, not an
idle-memory reservation that prevents concurrent FPGA compilation.
