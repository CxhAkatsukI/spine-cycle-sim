# Figure 8: One-Pass FPGA Update Throughput

**Real FPGA measurements**, 8/8 complete pairs.
One measured execution per arm per case, no warmup, repeats or averaging.
The paper and frozen prior deliveries are unchanged.

## Results

The ratio is G update time / Spine update time; above 1 favors Spine.
This is the maintenance-only part of G+R; ReGraph propagation is not run.

| Case | Spine, s | G update, s | G / Spine | Outcome |
| --- | ---: | ---: | ---: | --- |
| AU_4096_b10 | 0.599606 | 0.954642 | 1.592x | Spine |
| SU_4096_b10 | 0.562806 | 1.164655 | 2.069x | Spine |
| WK_4096_b10 | 0.574910 | 1.901516 | 3.308x | Spine |
| SO_4096_b10 | 8.389592 | 68.708168 | 8.190x | Spine |
| PK_4096_b10 | 13.324815 | 42.578711 | 3.195x | Spine |
| AU_131072_b10 | 0.978742 | 1.021854 | 1.044x | Spine |
| AU_131072_b100 | 1.141310 | 1.360007 | 1.192x | Spine |
| AU_131072_b1000 | 1.848652 | 3.065806 | 1.658x | Spine |

All eight pairs passed the recorded correctness and clock checks.
No failed point is replaced with a simulator prediction or a selected retry.

## Configuration And Provenance

Spine uses the declared fixed-v9 persistent layout (repair fixed-carry-v9). Raw fixed=1 layout receipts and physical launch accounting identify repaired execution. Chronological logical batches are retained; every physical sublaunch is charged. The declared v9 candidate statically bootstraps every family at L10, uses at most 8,192 updates per physical launch, and allocates one active record for the external MAINT-only host. Exact host artifacts pin this candidate; the fixed=1 marker alone does not distinguish repair versions. V9 constructs the directory from the compact host image, allocates the fixed device arenas directly, and performs a single fixed-arena graph upload, not a compact-device upload followed by relocation. Every successful Spine arm has a graph_uploads=1 receipt with arena_allocate_ns and live_upload_ns; failed attempts remain failures rather than single-upload evidence. V9 retains full device allocation and reduces initialized ranges, not initialization itself. Scratch and owner buffers use CONTENT_UNDEFINED; the host explicitly uploads ceil(V/128) dirty-bitmap words and ceil(V/4) family-directory words at their fixed offsets. Each successful Spine arm has exactly one SPINE_MAINT_SPARSE_INIT receipt matching the raw update vertex count, with owner_host_upload=0. The lifecycle initializes owner before MAINT; per-launch input writes remain. Initialization remains charged inside bootstrap_ns. V9 binds aligned, raw nonzeroed host backing for full scratch, owner and fixed arenas, retaining full device capacities. CONTENT_UNDEFINED avoids uploading the uninitialized backing; explicit live-range initialization and graph prefix writes remain. Compact CPU staging holds input, dirty bitmap and family directory, without a zeroed full-size owner vector. Already aligned, host-bound metadata is migrated once after the wrapper patches it; the lifecycle has no metadata argument. Every successful Spine arm requires host_bound_scratch=1, metadata_uploads=1, compact_host_staging=1 and uninitialized_host_backing=1 on the same sparse-init receipt. Required initialization and per-launch writes remain charged; initialization and the single metadata migration stay inside bootstrap_ns. Uninitialized host backing does not remove device initialization.

The matrix combines disjoint partial campaigns without rerunning or averaging cases.
- [Source 1](raw/source_campaigns/00/results.json): `/data/chuxiao/checks/fig8-fpga-persistent-20261107-v9/pilot-board`, `COMPLETED`.
- [Source 2](raw/source_campaigns/01/results.json): `/data/chuxiao/checks/fig8-fpga-persistent-20261107-v9/remaining-board`, `COMPLETED`.

Source journals, per-case raw logs, timestamps, commands and arm ordering
are retained unchanged. The flat result follows the input manifest's case order.
This is one paired sample per case across the recorded campaigns, not a claim
that the complete matrix ran under one uninterrupted board lease.

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
  The one-time lifecycle initialization status check remains inside Spine's
  bootstrap timer, as in the original production host.
- No graph propagation or convergence is timed. The weighted update kernel
  is algorithm-independent for this insertion workload; these are not three
  different algorithm runs, nor a replacement for Fig. 7 latency.
- Both arms use identical original IDs, weights, order and batch boundaries.
  G explicitly reserves PMA from the future trace union and uses
  1 metadata replica(s). Layout and capacity policy
  changes are disclosed above, not used to hide failures.

The older Fig. 8 is measured CPU preparation plus simulator predictions
with L4 Spine initialization. These FPGA runs include actual XRT
allocation/upload/wait costs and do not, by themselves, establish prediction
error for that model. Single samples establish observed outcomes, not confidence
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
- [File manifest](manifest.json): SHA-256 of every delivered file except
  this manifest itself.

The recorded hard memory budget is 32 GiB under `zfs-arc-clean-half-background5-v1`.
The 32 GiB launch profile normally uses a 30 GiB high watermark; memory.high was not recorded in this journal. The board runner requires zero swap, an exclusive board lease
and a 32 GiB live reserve. The maximum recorded cgroup peak across source
campaigns was 17.89 GiB, not a sum of peaks;
each campaign's own memory events remain in its journal.
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
python3 -m unittest discover -s tests -p 'test_figure8_fpga*.py'
```

For board reproduction, first rebuild the archived hosts, restore the
hash-indexed inputs/images, update `hardware.json`, then use `board.py`
inside a finite systemd cgroup with an available board. Exact commands of
the measured run, including environment and affinity, remain in the journal.
Do not rerun over this frozen output directory.
