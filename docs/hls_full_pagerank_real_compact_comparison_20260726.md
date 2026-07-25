# HLS-profile Full PageRank Real-Compact Comparison

## Question

This experiment compares Spine with the proposed HLS-equivalent
GraSU/ReGraph Full PageRank path under one common dynamic-graph contract:

- preload the same initial graph outside the timed window;
- time one 8-mutation insertion, deletion, or weight-change batch;
- wait for structure and degree state to become visible;
- execute three all-vertex PageRank iterations at damping 0.85;
- validate each result against independent float32 and float64 oracles;
- compare external-order rank vectors across systems.

The corpus contains nine cases: three compact real-edge slices (Amazon-2008,
web-Google, and soc-Flickr-und) times three update scenarios. Weight changes
are encoded as eight exact deletes followed by eight inserts.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
make -C cpp/sst -j2
python3 scripts/run_hls_pagerank_real_comparison.py \
  --out-dir results/hls_full_pagerank_real_comparison_release_20260726 \
  --jobs 3 \
  --timeout-seconds 300 \
  --max-cycles 100000000 \
  --no-build
```

The runner supports `--run-id`, `--limit`, and `--resume`. Its cache key binds
the runner, both child runners, profiles, capability catalog, input manifest,
SST binary, and simulator plugin.

## Correctness

All 18 system rows pass their architecture and mathematical oracles. All nine
paired external rank vectors match; the maximum cross-system absolute rank
difference is 0 in this matrix. The runner fails before writing a passing
manifest if any vector, phase ledger, graph size, update count, profile, clock,
or DRAM request count differs.

## Performance

`Spine speedup` is defined as `GraSU time / Spine time`; values below 1 mean
GraSU is faster. Times use each profile clock: routed-reference Spine at
141 MHz and proposed GraSU/ReGraph at 200 MHz.

| Group | Spine E2E speedup | Plain-language result | Compute-only result |
|---|---:|---|---|
| All 9 pairs, geometric mean | 0.780 | GraSU is 1.282x faster | GraSU is 1.020x faster |
| Amazon-2008 | 0.995 | Effectively tied; GraSU is 1.005x faster | Spine is 1.244x faster |
| web-Google | 0.693 | GraSU is 1.443x faster | GraSU is 1.162x faster |
| soc-Flickr-und | 0.689 | GraSU is 1.451x faster | GraSU is 1.136x faster |

GraSU wins all nine E2E rows, but the small Amazon case shows why a component
breakdown matters: Spine's compute is faster there, while its maintenance cost
removes that advantage. Across all rows, GraSU's structure update is about
340x faster by geometric mean. Insert/delete/weight-change do not materially
change the E2E ordering because three PageRank sweeps still dominate total
time; weight changes increase both systems' update work through 16 physical
records.

## Memory observations

The phase boundary now freezes backend requests when Spine maintenance drains,
before Reader/compute can issue in the next cycle. Both systems therefore
report closed update and compute request ledgers.

| Request metric, GraSU / Spine | Geometric mean |
|---|---:|
| Total update + compute | 1.307x |
| Update only | 0.0104x |
| Compute only | 1.523x |

GraSU does far less update traffic, but more PageRank compute traffic. Its E2E
lead therefore comes from cheap PMA updates, its 200 MHz profile clock, and its
pipeline schedule, not from universally lower memory volume. This matrix does
not yet classify requests as sequential or random. DRAMSim3 energy covers only
instantiated active channels and excludes on-chip and idle-channel energy, so
it is retained as raw evidence rather than promoted to total-energy results.

## Claim boundary

- These are compact real-edge slices, not full datasets.
- Spine uses a valid one-batch L0 checkpoint; arbitrary multi-level checkpoint
  loading remains open for publication-scale graphs.
- GraSU/ReGraph PageRank is executable and HLS-equivalent by construction, but
  no PageRank xclbin has been synthesized or hardware-validated.
- Simulator cycles are not calibrated cycle-for-cycle against hardware.
- Full PageRank here means all vertices are processed for three fixed
  iterations; it is not a convergence-to-tolerance experiment.

The result closes the real-compact Full PageRank gate. It does not close
thresholded residual PageRank, locality classification, total energy/PPA,
dense-batch, or publication-scale runtime gates.
