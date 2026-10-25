# Implementation And Supporting Evidence

This is a portable copy of completed implementation checks and retained
attempt records. It is **not** the final FPGA comparison, stage timing
calibration, or reproduction of original-publication performance.

The original bytes are stored in `records.tar.gz`, with fixed archive metadata
and an archive hash in `manifest.json`. Expand it in this folder with
`tar -xzf records.tar.gz` to inspect the paths below. Generated tool whitespace
is preserved rather than cleaned to make a source diff pass.

## Reading Order

| Record under `records/` | Evidence boundary |
| --- | --- |
| `source-zfs-v3/results.json` and `raw/` | Independent source-functional checks: 21 bounded plain, 21 bounded token, and six legacy checks for each interface |
| `hls-zfs-v3/results.json`, `raw/`, and exported XML | Two bounded kernels synthesized/exported; interface and HLS estimate checks, not physical route timing |
| `route-zfs-v2/{sssp,cc,respr}/` | Actual route reports, link/resource contracts, metadata and raw compiler wrapper logs |
| `respr-artifact-audit-v1/results.json` | Independent G+R ResPR artifact, clock and pin audit |
| `spine-respr-zfs-audit-v1/` | Independent audit of the successful Spine ResPR compiler output after dependency postprocessing failed |
| `sim-sharded-v1/` | Fresh 31-test core regression, individual test output and the recorded source-review patch |
| `sst-bounded-verification-v2/stderr.log` | Five actual SST functional checks; not FPGA timing calibration |
| `terminal-tool-preflight-v2/` | 37 delivery, renderer and profile tests using synthetic fixtures, not measured board results |

The original statuses are unchanged. For example, `ROUTED_NOT_BOARD_TESTED`
describes a build-stage record when it was written; subsequent board evidence
belongs to the separate paired-matrix package. ResPR's automatically reduced
clocks are retained, not silently normalized to requested clocks.

## Integrity And Retained Failures

`manifest.json` lists all 127 copied records, their original paths, sizes,
SHA-256 hashes and roles. Its copied payload is 7,910,692 bytes. The reading
guide and manifest itself are not included in that payload count.

There are 32 stage/result records, including 16 `FAILED_RETAINED` outcomes.
Older `matrix-v1` through `matrix-v4` observers stopped with
`WAITING_FOR_REMAINING_HARDWARE` snapshots. These are explicitly labelled
superseded snapshots; their status text has not been rewritten into success
or mistaken for a currently running observer. No current matrix snapshot,
partial median, or finalizer state is included here.

Bitstreams, graph inputs and complete tool build trees are not copied into
Git. Original stage records retain their external paths and identity hashes.
Full failed-run raw directories remain at the original machine-local paths;
this portable supporting package does not claim to contain every failed
compiler intermediate or log. The final matrix package separately contains
the paired raw board logs and their validation records.

The copy recipe is `records/package-implementation-evidence.py`. It requires
a fresh output directory, rejects unexpected nonterminal stage records,
enforces 16-MiB per-file and 64-MiB total budgets, checks all 31 core tests,
and verifies each source and destination hash after copying. Its first
attempt rejected the historical waiting snapshots instead of silently
accepting them; that error log remains at the original evidence root.

The original evidence root is
`/data/chuxiao/builds/grasu-cache-extent-20261025` on trifoliate.
See the owning study's `REPORT.md` for measured conclusions and remaining
delivery gates.
