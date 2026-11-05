# Current FPGA Source Controls

These eleven replayed controls supersede the older ResPR source-control series
in the parent directory. They are **not** a complete new Figure 7 matrix.
The [resident FPGA checkpoint](resident_checkpoint_v2/README.md) supplies the
15 completed pairs and all nine missing statuses separately.
The [CC resume record](cc_resume_v1/README.md) explains the guarded build
restart and exact queued follow-ups; it is not additional board evidence.
Its 104-GiB attempt subsequently hit its cgroup OOM limit; the separate
[memory follow-up](cc_resume_v2/README.md) records that failure and the
explicit larger build policy. Neither record supplies a measured CC bar.

- [Data](gr_controls.csv): actual per-arm milliseconds, ratios, image identities,
  clocks, sample counts, timing-closure status and claim scope.
- [Preview](figures/gr_current_source_controls.png) /
  [PDF](figures/gr_current_source_controls.pdf).
- [Provenance](gr_scope.json) and [raw receipts/logs](gr_receipts.tar.gz).
  Large graphs, final states and binaries are indexed by path and SHA-256 rather
  than duplicated. The archive preserves small hash-checked original evidence.

| Algorithm | G current / public, ms | R current / public time |
| --- | --- | --- |
| SSSP | 7.023 / 18.369 | AM 0.942x; AM+ 0.917x; AU 1.135x |
| CC | 7.364 / 18.369 | AM 0.966x; AM+ 0.922x; AU 1.124x |
| ResPR | 10.957 / 19.166 | skew 0.906x; AM 1.005x |

Every declared R point is within absolute +/-15%. Every G point is faster;
this is an **at-most-15%-slower** retention screen, not +/-15% absolute parity.
The dashed reference is 1 and the dotted upper threshold is 1.15. Lower is
better for the integrated baseline. One board sample per arm; no averaging.

## What Was Compared

G measures the resident first-to-last update-CU event span, including inter-shard
gaps but excluding initial residency and final readback. The public GraSU HLS
control updates PMA only. The integrated ResPR path also updates degree state;
its additional work is not removed from its timing.

R measures a resident superstep of the actual adapter plus modified ReGraph,
against the public-source four-Little ReGraph port (A4), with matched inputs
and state. It excludes G, initial upload and end-to-end host orchestration.
AM is Amazon; AM+ has higher activity; AU is the admitted AskUbuntu slice;
skew is the skewed-source fixture. This is not old-to-new convergence latency.

SSSP and CC use matched 150/500/450-MHz data/kernel/HBM clocks and nominally
timing-closed routes. ResPR uses matched **140/500/430-MHz** clocks on both arms.
Its nominal 150/450-MHz route missed timing; repackaging and board correctness
do not constitute a new static timing closure. That limitation is retained
in every CSV row and in the receipt archive. These controls establish retention
relative to the named public-code ports on these inputs, **not reproduction of
either paper's published throughput** or blanket equivalence for all workloads.

The exact SSSP image is the one used for the eight-row
[new SSSP result](../fig7_sssp_banked.csv). The CC image is the admitted
source-burst baseline; the replacement Spine CC route does not change that
baseline. The degree-prefix ResPR image is the baseline in the new running
resident matrix. No point is borrowed from the earlier packed-validity image.

The [qualified Spine correction host](https://github.com/jayfeather9/spine-dynamic-graph/commit/b576278)
and its tests are committed separately in the HLS repository. It changes host
preparation, not the Spine kernel or the G+R images in this control table.

## Reproduce

From a complete simulator checkout, with the pinned evidence still available:

```sh
pkg=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105
PYTHONPATH=. python3 "$pkg/export_controls.py" \
  --sssp-matrix "$checks/sssp-resident-matrix-banked-v4/matrix.json" \
  --cc-anchor "$checks/cc-warm-au-source-bursts-resident-v8/results.json" \
  --respr-g "$checks/respr-degree-prefix-g-dual-clock-v1/results.json" \
  --respr-r "$checks/respr-degree-prefix-dual-clock-v2/results.json" \
  --respr-route "$checks/respr-tail-degree-prefix-link-v1" --output /path/to/fresh-export
python3 "$pkg/render_current.py" --data /path/to/fresh-export/gr_controls.csv \
  --output /path/to/fresh-figures
```

`checks` was `/data/chuxiao/checks/source-retention-repair-20261104` on the
run host. Export replays original G/R admission and validates hashes, ratios,
images and clocks before writing. The renderer reuses the parent Python
GraphyFlow/TX Typewriter style and verifies the supplied ZIP's SHA-256.
The source-control preview is independent of all older frozen previews.
