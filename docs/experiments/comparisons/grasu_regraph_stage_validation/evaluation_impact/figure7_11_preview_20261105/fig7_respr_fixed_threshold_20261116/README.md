# Fig. 7 ResPR: two fixed activation thresholds

[High threshold (1e-7)](respr_high.csv) |
[Low threshold (3e-9)](respr_low.csv) |
[Run status](matrix_status.csv) |
[Raw logs and commands](evidence/)

Both sweeps use the eight original Fig. 7 datasets and the original
eight insertions on each graph. Each sweep uses one absolute per-vertex
threshold on all graphs, shared by Delta.hls and G+R. At the high
threshold a correct execution with no propagation is a valid result.
At the low threshold both implementations must propagate, so the
comparison also covers nonempty repair everywhere. The CPU preflight
put the largest old-graph residual across graphs at `6.40284e-10` (LJ08)
and the smallest post-insertion maximum at `6.86032e-9` (SO).
We selected `3e-9` from the earlier threshold ladder before board timing,
not by speedup. The original per-dataset-threshold results are separate.

Each row is one FPGA pair on U55C `0000:82:00.1`. `retained_exact` refers
to the four earlier pairs at the identical threshold, workload, old-rank
checkpoint and bitstreams: AU/SU/R19 high, SO low. Other rows are new.
Delta.hls reconstructs the deterministic FP32 old-rank checkpoint; G+R
loads its exported copy and checks that it has no active residual at the
requested threshold. Both outputs must pass their CPU reference checks.
The CSV records initial active counts, propagation rounds, and each
implementation's correctness result. G+R's correction pass is not a
propagation round. There are no repeat-based error bars.

Timings are the existing Fig. 7 resident host wall intervals, including
applying the batch, correction, propagation, dispatch and final readback.
Graph and old-rank loading, the Delta.hls old-graph correction cache,
and final CPU validation are outside the timer. Delta.hls pre-stages its
update descriptors. Its timed batch correction is host-assisted and its
path can relaunch/read state per round. These are not pure kernel times;
the CSV speedup is G+R wall time divided by Delta.hls wall time.

## Results

All 16 pairs passed correctness checks and matched initial active counts
and propagation rounds. At `1e-7`, three graphs propagate (AU, SU, R19)
and five do not. Delta.hls has lower measured wall time on all eight;
SU is effectively tied in this single pair (23.92 vs. 24.01 ms).
At `3e-9`, all eight graphs propagate on both systems (1 to 26 rounds).
Delta.hls is faster on five; G+R is faster on AU (1.14x), SU (1.71x),
and R19 (1.91x).

## Reproduction

Commands and logs are saved per dataset and sweep. The
[runner](run_fixed_threshold.sh) and [collector](collect.py) take the
prior replay directory and fixed-threshold scratch directory on trifoliate:

- Prior replay: `/data/chuxiao/fig7-respr-propagation-fig10b-20261116.cnPau7QX`
- Fixed-threshold scratch: `/data/chuxiao/fig7-respr-fixed-threshold-20261116.aljt53SZ`

See the [prior replay](../fig7_respr_nonzero_20261116/README.md) for host
patches and source commits. The selected Fig. 7 CSV, plots and paper are
unchanged.
