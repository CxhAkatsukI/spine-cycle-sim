# Fig. 10(b): FPGA latency across deletion shares

[AU CC FPGA and software reference CSV](results.csv) |
[AU CC raw board logs, batches and build hashes](raw/) |
[Data collector](collect.py)

[LJ08 SSSP FPGA results](lj08_sssp/results.csv) |
[LJ08 matched Ligra/Gunrock comparison](lj08_sssp/comparison.csv) |
[LJ08 protocol and replay](lj08_sssp/README.md)

This supplements the deletion-share panel in the current manuscript. It does
not replace the older simulator breakdown also numbered Fig. 10 in this handoff.
The reference CSV has separate LJ08 software rows. The LJ08 FPGA CSV and
matched comparison are separate from the AU results.

| AU CC deletion share | Delta.hls FPGA wall | Ligra I median | Gunrock I median | FPGA execution path |
| ---: | ---: | ---: | ---: | --- |
| 0% | 111.640 ms | 0.978 ms | 25.889 ms | warm insert |
| 25% | 44,709.400 ms | 32.869 ms | 26.717 ms | full fallback |
| 50% | 44,793.223 ms | 34.928 ms | 25.779 ms | full fallback |
| 75% | 44,879.841 ms | 35.401 ms | 24.870 ms | full fallback |
| 100% | 36,435.872 ms | 34.669 ms | 23.928 ms | affected components only |

All five FPGA runs passed the independent CPU graph and CC label checks.
Each mixed batch reset all 515,281 vertices and ran ten propagation rounds.
Pure deletion reset 131,351 vertices and still took ten rounds. The logs
separate propagation from discovery and reset. Delta.hls is slower than
both Mode I baselines at every point on this image. Do not clip these
FPGA values to the old panel's axis or extrapolate to other FPGA images.

**Input identity.** AU has 512 logical updates (1,024 reciprocal records)
per point. The 0% binary graph, batch and both oracle digests match
`C_AU_cc_[IR]_512` in the paper's `followup_latency_pair_index.csv`; the other
four points match the frozen AU signed-batch software evidence. The base
arcs are identical across all five points. The four deletion-bearing points
use the unit-weight graph export; the insertion-only point uses the existing
weighted board-graph export. These are per-point matched comparisons, not
one event stream with a varying deletion ratio. The CSV records which graph
encoding was hashed and preserves the identity hashes.

**Timing.** One U55C sample per point. The table uses host pack through final
board readback, excluding old-graph load, initialization and post-run CPU
oracle checks. The CSV also gives resident batch through final readback.
Ligra and Gunrock values are the existing software wall medians, not new
samples; Mode I is in-place and Mode R rebuilds CSR. The FPGA timings
include host/device work within the recorded window; they are not kernel
event times. The first 100% allocation failed at an 8 GiB host cgroup cap
and is retained separately; the five accepted runs used a 24 GiB cap.

**Replay.** The local run root is
`/data/chuxiao/fig7-respr-propagation-fig10b-20261116.cnPau7QX`. It retains the
prepared graphs and `run-fig10b-au-cc.sh`; use the shared card lock and memory
checks in that script. Image and host identities are in
[`raw/build.sha256`](raw/build.sha256); the `*.command` files retain each invocation.
To regenerate the CSV, pass the run root's `fig10b-au-cc-frozen` directory,
the original `cpu-gpu-deletion-sweep.json`, and the paper's
`meta/e15_trifoliate_cpu_gpu_20261115` directory to `collect.py`.

**LJ08 SSSP.** The CSV preserves the five deletion shares, source vertex 26,
and the graph, batch and oracle hashes from `lj_sssp_fraction_summary.csv`.
The exact 5,363,260-vertex / 99,028,542-edge graph and initial distance
vector were recovered. They are `base.bin` and `oracle.before` under
`fig10b-lj08-sssp-frozen` in the run root above. The recovered graph and
distance SHA-256 digests match the software data at all five shares. They
were regenerated from `lj08_weighted_sssp_insert_u8.graph` under
`/data/tmp/chuxiao/fullgraph_fpga_workloads_20260806`, using the software
delivery's `board_reference.cpp` with `convert` and an empty `sssp-overlay`.
The old eight-edge update tail was excluded and is not used in this sweep.

The five signed `batch.txt` files and reference outputs were recovered from
the original software campaign. The input identity columns in the CSV
give the batch and final-distance digests.

| Deletion share | Original attempt directory |
| ---: | --- |
| 0% | `20261114_lj08_sssp_insert512_0817` |
| 25% | `20261114_lj08_sssp_delete25_0652` |
| 50% | `20261114_lj08_sssp_mixed512_0507` |
| 75% | `20261114_lj08_sssp_delete75_0624` |
| 100% | `20261114_lj08_sssp_delete512_0355` |

The Nov. 13 candidate had a 4,096-entry repair-row buffer; the largest
forward and reverse rows in this graph each contain 19,432 edges. The
replacement raises that limit to 65,536 and fits the complete graph and
transpose using hot/cold family placement and a larger L10. The original
vertices, weights, updates and oracle are unchanged. See the
[LJ08 result directory](lj08_sssp/) for the exact image, host, and timing boundaries.
