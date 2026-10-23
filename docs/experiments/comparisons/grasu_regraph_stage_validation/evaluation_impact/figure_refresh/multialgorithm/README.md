# Three-Algorithm Figure 9 Data

The six missing AU/SU/WK CC and residual-PR pairs are now complete. SSSP was
also rerun, so **all nine pairs use the same frozen numerical sources, Release
core and direct DRAMSim3 backend**. This is simulator diagnostic evidence,
not an admitted original-publication baseline, FPGA calibration, or a paper
replacement. No FPGA build or paper edit was made.

## Results

All ratios below are **G+R divided by Spine**. A ratio above one favors Spine;
a ratio below one favors G+R. Cycles exclude host work. The energy column is
modeled HBM energy, not measured accelerator power.

| Algorithm | Dataset | Spine cycles | G+R cycles | Cycle ratio | Accepted-byte ratio | HBM energy ratio |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| SSSP | AU | 58,338 | 1,066,959 | 18.289 | 5,129.996 | 21.344 |
| SSSP | SU | 58,872 | 1,436,899 | 24.407 | 6,916.253 | 28.145 |
| SSSP | WK | 40,005 | 693,723 | 17.341 | 1,265.307 | 18.784 |
| CC | AU | 65,497 | 541,867 | 8.273 | 1,695.611 | 9.788 |
| CC | SU | 62,190 | 727,821 | 11.703 | 3,587.301 | 13.713 |
| CC | WK | 75,406 | 1,357,985 | 18.009 | 1,854.294 | 19.977 |
| ResPR | AU | 183,160,033 | 34,974,705 | 0.191 | 21.242 | 0.228 |
| ResPR | SU | 164,806,227 | 39,893,391 | 0.242 | 22.641 | 0.282 |
| ResPR | WK | 307,094,993 | 65,040,895 | 0.212 | 21.256 | 0.253 |

SSSP and CC retain a modeled device-cycle advantage in these cases. ResPR
does not: Spine is about **4.13--5.24 times slower**, despite accepting fewer
bytes. It also consumes more modeled total HBM energy. Preserve this negative
result; traffic reduction alone does not establish an energy or latency win.
This study has not isolated the individual causes of the PR timing gap.

AU/SU CC insertions do **not** change the final component labels; they test
maintenance and no-change completion, not merging two components. WK CC and
the CC smoke do change labels. The matrix is retained in full, not filtered
to the most favorable insertions.

## Files

| File | Purpose |
| --- | --- |
| [Pair table](data/fig9_memory_energy_rows.csv) | Nine fresh byte/energy ratios and absolute accepted bytes |
| [Arm table](data/fig9_arms.csv) | Eighteen arms: cycles, rounds, reads/writes and all DRAMSim3 energy components |
| [Summary](data/summary.json) | Model scope, full comparisons, source identities and SSSP before/after correction |
| [Evidence index](evidence/index.json) | Hashes, every retained attempt and explicitly external dependencies |
| `evidence/evidence.tar.gz.part*` | Lossless 64-MiB transport parts: portable logs, configurations, full output states, sources and failed attempts |
| [Test report](TEST_REPORT.md) | Passing numerical gates, full-suite failures and isolated environment rechecks |
| `validation/` | Post-seal packaging checks and resource records, separate from the numerical archive |

This delivers **data**, not new plotted PDFs. The preceding
[Figure 8 collection](../README.md) remains unchanged: its setup-inclusive
one-batch measurements are not ten-batch resident throughput. This extension
does not rerun Figure 8, Figure 7 hardware, or the Figure 10 stage breakdown.

## Inputs And Boundary

Each pair starts from the same independently converged old graph state,
applies the same eight user insertions, and runs to new-graph convergence.
CC uses reciprocal edges and therefore sixteen physical update records.
The original physical vertex IDs are retained; SSSP sources are AU=11,
SU=23 and WK=0. Sizes are the materialized old inputs, not original-dataset
headline sizes:

| Dataset | Vertices | SSSP edges | CC edges | ResPR edges |
| --- | ---: | ---: | ---: | ---: |
| AU | 515,281 | 390,847 | 679,246 | 826,848 |
| SU | 567,316 | 616,118 | 1,061,248 | 1,075,035 |
| WK | 1,140,149 | 1,142,352 | 2,032,558 | 2,190,639 |

The measured simulator window includes resident device maintenance,
algorithm-specific preparation, propagation and result completion. Initial
loading, independent oracles, CPU preparation, DMA, kernel launch/relaunch
and readback are excluded on both arms. G physically updates the resident
PMA subsequently read by R; the host does not rebuild the post-update graph.
PMA capacity is reserved using the known future insertion batch. This is a
fixed-reservation replay, not arbitrary online capacity growth.

SSSP must exactly match independent Dijkstra; CC must exactly match independent
union-find. PR uses the common hardware-warm dangling/residual contract,
FP32 damping 0.85 and stored residual threshold `1e-5 / V`, checked against
independent double-precision Jacobi and its L1 error bound. Complete states,
source replicas, padding and physical request/byte closure are checked.

## Model And Open Gates

- Both arms use 150 MHz and the same direct DRAMSim3 model: 32 channels,
  512 MiB/channel and 32 outstanding backend requests/channel. Energy sums
  **all 32 channels**, including standby and refresh over each device window.
- G is the natural 64K-shard, shared-metadata implementation. Its separately
  tested copied-metadata prototype is not silently substituted. Original-G
  timing parity remains unadmitted.
- R uses finite `prefetch_gather_reuse` resources and now implements CC and
  warm FP32 residual PR. It has 16 masters/three state replicas, versus the
  original-A4 control's 13/four; this is not strict resource equality.
- The original source-derived R control has fixed-point FullPR and a local
  SSSP UDF, not these CC and warm FP32 residual-PR executions. No corresponding
  original-R timing match is established. Prior SSSP agreement cannot be
  transferred automatically, especially after the documented AXI correction.
- **Spine PR correction is an oracle-directed timed-work replay**: its memory
  requests are charged, but the functional correction seed is not derived
  from AXI responses. Correct final ranks do not establish a functional HLS
  implementation or FPGA timing equivalence for that preparation path.

These open gates prevent claiming a fully validated original G+R baseline or
a hardware/paper performance reversal from these predictions alone. They do
not justify concealing the PR counterexample.

## Corrections And Provenance

Finite out-of-order read storage could previously deadlock on PR. The repair
reserves a reorder credit before issuing a streamed beat and releases it at
ordered publication, without enlarging the 32-beat production storage.
The retained strict SSSP replay fails exact timing as expected: all twelve
input/state/byte trajectories, G cycles and Spine cycles remain exact, but
R adds 14 smoke cycles and 1.35--1.70% on the Amazon controls. An explicit
read-credit correction gate requires this limited change and invariance to
component registration order. All nine energy pairs were regenerated.

Spine owner bookkeeping was accelerated without changing its simulated
behavior; ten retained before/after arms have identical states, cycles,
traffic and energy. PR's banked FP32 dangling reduction follows the existing
HLS organization and charges its final reduction cycles. Failed sequential
reduction, deadlock, strict replay and earlier CTest attempts remain archived.

`matrix-v5` completed in 43 minutes with a roughly 2.6-GiB service peak,
inside a 6-GiB max/5-GiB high cgroup, zero swap, 4-GiB child limit and live
24-GiB system reserve. The final matrix and `core-tests-v7` retain unchanged
source pins. The recorded run head predates the subsequent checkpoint commit;
the archived dirty-source hashes, not the commit name alone, identify the run.

Only packaging changed after the numerical run: the redundant 1.1-GiB full
prechange repository archive remains external with its size/hash and reason
indexed. Its corresponding code-only Git snapshot is included and verified.
All failed/interrupted experiment records remain in the portable archive;
only build trees, external tool binaries and large input dependencies are
excluded as documented. Original full snapshots were not removed.

## Reproduce

From the repository root, inspect the
[runner guide](../../../../../../../spine_cycle_sim/experiments/evaluation_impact/figure_refresh/multialgorithm/README.md)
for bounded build/run commands and required external input/tool identities.
Run the fresh core gate before the study; use fresh output directories.
The archived `matrix-v5/results.json` records the exact compiler, input,
memory configuration and linked-library hashes. Offline verification needs
neither FPGA tools nor the original large graph inputs.
The verifier automatically reassembles the indexed parts in a temporary
directory, checks each part and the original complete archive hash, then
rechecks all sealed results. Allow about 180 MiB of temporary disk space:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.delivery \
  --output docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure_refresh/multialgorithm \
  --verify
```
