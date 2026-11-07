# Figure 8: One-Pass FPGA Update Throughput

November 7, 2026. **Real FPGA measurements**, 4/8 complete pairs.
One measured execution per arm per case, no warmup, repeats or averaging.
The paper and the frozen November 6 download are unchanged.

## Results

The ratio is G update time / Spine update time; above 1 favors Spine.
This is the maintenance-only part of G+R; ReGraph propagation is not run.

| Case | Spine, s | G update, s | G / Spine | Outcome |
| --- | ---: | ---: | ---: | --- |
| AU_4096_b10 | 0.949022 | 0.845721 | 0.891x | G |
| SU_4096_b10 | 0.886369 | 1.060230 | 1.196x | Spine |
| WK_4096_b10 | 0.997291 | 1.869868 | 1.875x | Spine |
| SO_4096_b10 | 5.204369 | 67.652156 | 12.999x | Spine |
| PK_4096_b10 | FAIL | 39.717544 | -- | Failed pair; retained |
| AU_131072_b10 | FAIL | 1.122844 | -- | Failed pair; retained |
| AU_131072_b100 | FAIL | 1.295712 | -- | Failed pair; retained |
| AU_131072_b1000 | FAIL | 2.971797 | -- | Failed pair; retained |

Failed points are shown explicitly in the CSV and preview, not substituted
with simulator predictions. In particular, native Spine L2 reports graph
overflow during PK and AU 131K/10- and 100-batch maintenance. AU 131K/1,000
completes every batch but fails the final graph readback/oracle with an
out-of-range address. It is not an admitted timing point. These are not host
OOM events. No unresolved failure is claimed to be merely a layout issue;
the latter failure has a concrete compact-host/fixed-kernel layout mismatch:
17,829,908 is the kernel's fixed L10 bitmap base, beyond the allocated
3,694,361 words. This does not establish otherwise-correct device state.
Simply enlarging buffers can leave fixed carry destinations overlapping
live compact slices. The 10-batch trace also exceeds fixed L1 capacity
within one family, so changing bootstrap headroom alone is insufficient.
The native-wrapper README records the source locations and diagnosis.
See each arm's raw stdout/stderr for the last completed batch. Thus this
delivery does not yet contain a valid complete Fig. 8b curve.

## Measurement Window

- Panel a: original weighted AU/SU/WK/SO/PK traces, 4,096 total insertions
  divided chronologically into ten batches.
- Panel b: the same AU old graph and 131,072 insertions, divided into
  10/100/1,000 chronological batches. Labels show mean updates per batch.
- Initial native layout and graph upload are charged once. Each batch adds
  host packing, update DMA, kernel arguments/launch and completion wait.
  The graph stays device-resident throughout all batches.
- Parsing, image programming, validation/status readback, oracle work and
  logging are excluded from the summed timer. Mandatory Spine status checks
  still run between batches. This is not uninterrupted process wall time.
- No graph propagation or convergence is timed. The weighted update kernel
  is algorithm-independent for this insertion workload; these are not three
  different algorithm runs, nor a replacement for Fig. 7 latency.
- Both arms use identical original IDs, weights, order and batch boundaries.
  G explicitly reserves PMA from the future trace union and uses one shared
  metadata copy. Native Spine bootstraps at L2. No capacity policy is changed
  to conceal a failure.

The older Fig. 8 is measured CPU preparation plus simulator predictions
with L4 Spine initialization. This FPGA run uses L2 and actual XRT
allocation/upload/wait costs. It therefore does not, by itself, measure
prediction error for that L4 model. Neither results nor configurations are
silently merged. Single samples establish observed outcomes, not confidence
intervals or steady-state averages.

## Files

- [CSV](fig8_fpga.csv): all eight attempted pairs and absolute timing terms.
- [PNG](figures/fig8_fpga_update_throughput.png) /
  [PDF](figures/fig8_fpga_update_throughput.pdf): Python/GraphyFlow-style,
  TX Typewriter; both panels have their own legend and a 1x reference.
- [Run journal](raw/results.json): commands, CPU affinity, exact host/image
  and input identities, correctness, clocks and live memory observations.
- [Inputs](inputs.json): original trace identities and conversion paths;
  graph data and xclbins remain outside Git and are indexed by SHA-256.
- [Bindings](hardware.json): exact local host and image paths.
- [Frozen native host sources](host-sources.tar.gz): both thin wrappers,
  included production dependencies, compiler commands and a portable build
  script. Verify with the embedded SHA256SUMS before rebuilding.
- `setup_failure_card1/`: earlier image-programming timeout before any
  successful update sample. The runner was interrupted when it attempted
  the next arm; its original RUNNING journal is retained, not treated as
  completed evidence. All selected measurements use card 0.
- [File manifest](manifest.json): SHA-256 of every delivered file except
  this manifest itself.

The board runner used a 24 GiB hard limit, 22 GiB high watermark, zero swap,
an exclusive board lease and a 32 GiB live reserve. Peak cgroup memory was
17.89 GiB; memory events are in the journal.
Clock sets are recorded after each arm under the same lease, not inferred
from the filename. This is a timing measurement, not a new routing claim.

## Code And Reproduction

The owning package is
`spine_cycle_sim/experiments/evaluation_impact/figure8_fpga/`; native wrappers
are in `cpp/tests/evaluation_impact/figure8_fpga/`. From a full repository
checkout, use Python 3.11+, Matplotlib, LaTeX txfonts and dvipng:

```sh
module=spine_cycle_sim.experiments.evaluation_impact.figure8_fpga
python3 -m "$module.render" --data /path/to/fig8_fpga.csv --output /tmp/fig8-redrawn
python3 -m unittest tests.test_figure8_fpga tests.test_figure8_fpga_sources
```

For board reproduction, first rebuild the archived hosts, restore the
hash-indexed inputs/images, update `hardware.json`, then use `board.py`
inside a finite systemd cgroup with an available board. Exact commands of
the measured run, including environment and affinity, remain in the journal.
Do not rerun over this frozen output directory.
