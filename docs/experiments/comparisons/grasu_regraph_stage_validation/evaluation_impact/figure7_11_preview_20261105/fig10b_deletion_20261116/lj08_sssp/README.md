# Figure 10(b): LJ08 SSSP on U55C

`results.csv` contains one accepted FPGA sample at each of 0%, 25%, 50%, 75%, and
100% deletion. Each batch has 512 signed edge updates. The
base graph is the original weighted LJ08 (5,363,260 vertices, 99,028,542 directed
edges, source 26); see `input_manifest.tsv` for the base, batch, and oracle hashes.
`raw/` holds the exact signed input after conversion to the board host's format
and the corresponding board log.

`comparison.csv` adds the published handoff's Ligra and Gunrock software
medians for the accepted FPGA rows. The join checks graph, batch, and old/new
distance hashes against the frozen input manifest. Mode I updates in place;
Mode R rebuilds CSR. The software samples were not rerun here.
Delta.hls wall time is 143.19 to 1,011.84 ms across the five shares and is
higher than both software Mode I medians at every point.

The CPU reference vectors differ from the old checkpoint at 156, 132, 111,
83, and 121 vertices for the 0%, 25%, 50%, 75%, and 100% batches, respectively.
These counts describe the input workload; they are not device work counters.

Before board testing, the HLS C model passed all five original batches against
the same full CPU distance vectors using the resident graph placement and local
repair. The model needed 4, 4, 6, 6, and 6 propagation rounds in deletion-share
order. These are functional checks, not FPGA timing or resource measurements.

The host preloads the original graph, its transpose, and a CPU-converged distance
vector before each sample. The FPGA handles the batch via local dependency repair
(`SPINE_REPAIR_MIXED_LOCAL`); no full-recompute mode is invoked. For every
accepted sample, the loaded checkpoint was read back and the final distances were
checked vertex by vertex against an independent CPU SSSP vector for the updated graph.
`wall_ms` includes batch packing and upload, execution, and final distance
readback; `publication_ms` ends before final readback. Neither includes loading the
old graph, generating the checkpoint, or verification after the measurement.

The image builds from `fabb5ad5fbcf9a2c9d490a95cbded8de482d62cb` of the
ordered-mixed implementation, with `kernel-host.patch` applied, increasing
the per-vertex row buffer from 4,096 to 65,536 and only the L10 storage allocation
to 5,242,880 edge slots per family. Original vertex IDs, weights and batch contents
are unchanged. Initial graph placement uses the existing cold/hot family routing.
See the weighted manifest for exact source and image hashes and
`xclbin-info.txt` for the linked image's clock and platform metadata
(146 MHz data path, 420 MHz HBM). The board host's SHA-256 was
`5c67b414739dbf46b15559c7e570a962a121cb8470e61fb24e021bf2e417c6a0`. On Seele,
`link-fast.sh` reused the three `l10/` kernel objects with ten synthesis jobs
instead of two, using the same platform, clock target and link settings. The
board uses one linked image for all five shares; `image.source` identifies the
selected file. Runs live in `/data/chuxiao/fig10b-lj08-sssp-repair-20261116` on
Trifoliate; see its `l10/` and `l10-fast/` subdirectories on Seele for build logs.
