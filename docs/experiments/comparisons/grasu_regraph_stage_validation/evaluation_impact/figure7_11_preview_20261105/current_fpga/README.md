# Current FPGA Source Controls

These eleven replayed controls supersede the older ResPR source-control series
in the parent directory. They are **not** a complete new Figure 7 matrix.
The [resident FPGA checkpoint](resident_checkpoint_v3/README.md) supplies the
16 completed pairs and all eight missing statuses separately. It adds the
completed LJ08 ResPR pair without rewriting the frozen fifteen-pair review.
The [CC resume record](cc_resume_v1/README.md) explains the guarded build
restart and exact queued follow-ups; it is not additional board evidence.
Its 104-GiB attempt subsequently hit its cgroup OOM limit; the separate
[memory follow-up](cc_resume_v2/README.md) records that failure and the
explicit larger build policy. Neither record supplies a measured CC bar.
The local ARC diagnostics below describe earlier failed attempts, not the
latest accepted LJ08 result. They do not change the remote CC build.

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

## Earlier ARC Attempts: No Accepted LJ08 Pair

This historical failure record is superseded only for current pair coverage
by the [validated LJ08 result](resident_checkpoint_v3/README.md). The failed
receipts and the frozen fifteen-pair review remain unchanged.

ZFS ARC is normally reclaimed automatically; no cache purge or global ZFS
change was requested or performed. `MemAvailable` alone was too conservative
as an admission test, so the explicit board policies also observe discounted
clean evictable ARC, enforce cgroup limits and supervise memory pressure.

The separate `zfs-arc-clean-half-settle10-v1` LJ08 attempt also stopped:
full PSI remained above our 1% guard for ten seconds. At the final observation,
`MemAvailable` was 19,433,537,536 bytes, the policy's discounted effective
headroom was 59,164,557,824 bytes and full PSI was 1.23%. The child peak was
20,295,331,840 bytes. All cgroup high/max/OOM counters were zero. This was
our pressure-protection decision, not evidence of OOM or a measured speedup.
The guard thresholds are our operational policy, not an OpenZFS guarantee.
This result does not justify repeatedly relaxing them until a run passes.

Preserved receipts on the run host:

- `/data/chuxiao/checks/source-retention-repair-20261104/respr-dual-arc-lj08-settle-v5/lj08/results.json`:
  `FAILED_RETAINED`, SHA-256 `ef1c4ac1437d453f36b867898373fbd57fdc89825b3ddf14f4b7c822cc6f4c1a`.
- Sibling `../matrix.json`: `RETAINED_INCOMPLETE_MATRIX`, SHA-256
  `dccbcf1ce74bdd597c8a4d544b56f6ec39597e381de160e731644007dac63135`.
- The dependent correction retime produced no accepted pair; its
  `/data/chuxiao/checks/source-retention-repair-20261104/respr-host-correction-arc-lj08-settle-v5/matrix.json`
  records `FAILED_RETAINED` (`FileNotFoundError`), SHA-256
  `a07032798f2cad6f32faa71c4a0bfcd05a908efc4ac136664d388414a93be829`.

The frozen fifteen-pair checkpoint is unchanged. LJ08 ResPR is still missing;
partial per-arm output is not a completed comparison. The independent CC
[192-GiB build replacement](cc_resume_v2/README.md#launched-replacement) runs
on the high-memory host without changing this local board policy.

### Subsequent Attempt And Queue Repair

The separate `respr-dual-arc-lj08-settle-v6` attempt was admitted with
68,822,335,488 bytes effective headroom against a 68,719,476,736-byte
reservation requirement, with low admission PSI (0.22%). It then stopped
after ten seconds of sustained high PSI. At the final observation, effective
headroom was 62,210,951,936 bytes and full PSI was 1.65%. Its cgroup peak
was 3,166,302,208 bytes; all high/max/OOM counters were zero. Only the
original Spine arm started, and no accepted timing pair was produced.
This does not show that ARC was unreclaimable, or identify which concurrent
workload caused pressure. No cache purge or global setting was changed.

[Retained v6 receipts](arc_lj08_v6_receipts.tar.gz) contain the original
terminal matrix, child result, logs and the dependent retime's last report.
Archive SHA-256:
`01ec515f482fe2fd9683fa56fe5c42dcaa2cd236f97691ed8bee803a6842ae74`.
The downstream invocation `ad16f5504b8944b29a5ed969201aedf5` was stopped
at 2026-11-05 21:45:32 CST after its producer was confirmed terminal. Its
last report still says `WAITING_FOR_FROZEN_PAIRS`; neither that stale report
nor systemd's successful stop is a successful measurement.

The correction-matrix runner now tolerates a producer file that has not yet
been created, within the existing finite wait deadline. Once a producer is
terminal, measured rows remain eligible for retiming, while failed or missing
rows become `UPSTREAM_UNAVAILABLE_RETAINED` with the exact terminal source
identity. Malformed input still fails. This avoids both the v5 startup race
and v6's futile wait without changing any hardware, numerical model, memory
guard, existing receipt, or accepted timing. Focused tests verify that a
terminal failed producer cannot launch a board child or become a sample.

The [fresh terminal classification](arc_lj08_v7_terminal.json), run from
commit `23f004f0` under a 2-GiB/zero-swap, 120-second service limit,
replayed the v6 terminal source and returned `RETAINED_INCOMPLETE_MATRIX` /
`UPSTREAM_UNAVAILABLE_RETAINED`. It launched no board child. This receipt
verifies the queue repair, not FPGA performance.

The subsequent v7 pair was admitted at 79,580,377,088 bytes effective
headroom and zero admission PSI, with the same 32/30-GiB max/high and zero
swap. It stopped during the original Spine arm after ten seconds of high
PSI; the final full PSI was 1.01%, effective headroom 58,659,192,576 bytes,
and cgroup peak 10,264,940,544 bytes. All high/max/OOM counters were zero.
The G+R arm did not start. The fixed v8 follower correctly returned
`UPSTREAM_UNAVAILABLE_RETAINED` without launching a board child. Neither
result adds a measured pair. These observations distinguish our conservative
pressure cutoff from allocation failure; they do not establish a need to
purge ARC or identify the cause of system-wide pressure. No additional retry
was queued immediately after this failure.

[Retained v7 pair and v8 follower receipts](arc_lj08_v7_receipts.tar.gz)
have archive SHA-256
`1d5c7dfda1f90c05203ed784230ab2c04095f23de003c130221969cd1f83541b`.
The fifteen-pair frozen review archive remains unchanged.

### Direct Qualified-Host Pair

The resident runner can now explicitly consume the existing CPU qualification
and measure the qualified Spine correction host and G+R once each. This removes
the redundant old-host measurement previously required before a host-only
retime. It does not provide a new performance result, guarantee that the ARC
pressure guard will pass, or change its thresholds. The existing seven accepted
ResPR retimes still reuse their exact frozen G+R samples and remain labelled so.

The new optional `--qualification` argument is forwarded by `dual_clock_matrix`.
It requires the exact CPU-qualified host and unchanged Spine kernel and
comparator; G/R source-control admission, matched clocks, numerical policy,
final-result oracles, one-sample count, cgroup limits and live memory monitoring
remain enforced. Both fresh-arm attempts and correction preparation scope are
recorded. This host-side cache is not device-resident PageRank correction.

For a **completed, checked** direct pair on a previously missing dataset,
`export_resident_checkpoint.py --qualified-pair /path/to/new/results.json`
adds the separately pinned receipt to a fresh output directory. Export rechecks
qualification, host/kernel identity, G/R controls, clocks, log hashes, analysis
and cache timing scope. It refuses to replace an already measured retime, choose
between duplicate datasets, substitute a different baseline image or accept a
failed pair. The CSV distinguishes two fresh arms from a reused G+R sample.
Original failed matrices remain in the receipt archive; the frozen review
package and its fifteen accepted pairs are not rewritten.

The first direct LJ08 pair was queued from frozen simulator commit
`380884bd` on 2026-11-05, under
`gr-respr-qualified-lj08-20261105-v1.service` (invocation
`086e83d7d76b4f8fb81f80eb8c3d587a`). Its child is
`gr-respr-qualified-lj08-child-20261105-v1-lj08.service` (invocation
`aa829d46ff0b4e39aeb4e762c378a634`). The run host's live receipts are
`/data/chuxiao/checks/source-retention-repair-20261104/respr-qualified-lj08-v1/matrix.json`
and `lj08/results.json` below that directory. At the recorded admission the
discounted effective memory was 74,237,573,632 bytes against a 68,719,476,736-byte
requirement, and both PSI averages were 0.02%. The child retains 32/30-GiB
max/high, zero swap and the unchanged `zfs-arc-clean-half-settle10-v1` policy;
the coordinator has a separate 2-GiB maximum. It started the Spine arm. This
launch record is **not a completed pair**; inspect the terminal receipt and
replay all gates before exporting a new checkpoint. No automatic repeat or
dependent old-host retime was queued.

That direct pair subsequently stopped at 22:17 CST with `FAILED_RETAINED`:
full PSI reached 1.66% continuously for ten seconds. Effective discounted
headroom was still 71,529,877,504 bytes; the task peak was 3,091,701,760 bytes
(2.88 GiB), and all cgroup high/max/OOM counters were zero. Only the Spine arm
was attempted; neither a completed pair nor a new speedup is available. This
is a stop by our global-pressure policy, not proof of OOM or of non-reclaimable
ARC. At that checkpoint, no further retry had been queued.

The [direct-pair receipts](qualified_lj08_v1_receipts.tar.gz) preserve the
terminal matrix, child receipt, service log, clocks and repackaging records;
binaries remain indexed, not duplicated. Archive SHA-256:
`5099480fad32559871bbd68109aa9433384b0d957249ecd62ac4154a06cf725c`.
Child receipt SHA-256:
`004024a6e3a565c69f85087ef7837cfa5f7b2298ef1eee154c0d2ecaf26f665f`.
The frozen review still has fifteen of twenty-four accepted pairs. The CC
build and its previously documented followers are independent of this stop.

### Memory Diagnostic, Not A New Board Result

The [read-only observation series](memory_baseline_no_pair.json) sampled the
existing ARC policy thirty times at two-second intervals from 14:31:27 to
14:32:25 UTC on November 5. The observer launched no FPGA or graph task and
used a 128-MiB maximum, 96-MiB high limit and zero swap. Its service peak was
12.4 MiB. The policy source is pinned in the receipt. This is a subsequent
background observation, not a reconstruction of the failed pair's pressure.

Full PSI ranged from 0.19% to 0.78%, and no observation failed the PSI guard.
Nevertheless, discounted effective headroom reached a minimum of 48.25 GiB
(raw `MemAvailable` minimum 15.89 GiB), below the 64-GiB board admission
requirement. These observations do not identify the cause of earlier pressure
or justify changing global ARC settings. No extra pair was launched.

The runner now preserves failed-execution memory diagnostics as described in
the [board admission guide](../../../../../../implementation/runtime/board_arc_admission.md).
This adds the previously missing last/peak observations and before/after
cgroup pressure to a hashed failure sidecar. Safety thresholds, workloads,
oracles, image identities and timing boundaries are unchanged. The former
attempts remain frozen failures without retroactively invented diagnostics.

### Guarded Direct-Pair Continuation

After adding the failure diagnostics, one direct LJ08 pair was queued from
frozen simulator commit `c0e26ce988b60f0d6c997a10fd9147a232bb580d` at
14:39 UTC on November 5. The service is
`gr-respr-qualified-lj08-diagnostics-20261105-v1.service`, invocation
`ea37d855386a418cbfa18149e026f1e0`. Its live receipt is
`/data/chuxiao/checks/source-retention-repair-20261104/respr-qualified-lj08-diagnostics-v1/results.json`.
It has a 32-GiB maximum, 30-GiB high limit, zero swap and an eight-hour runtime
limit. Board admission waits at most six hours, then measures each arm once;
there is no automatic retry after a failed execution.

This attempt ended at 14:45 UTC with `FAILED_RETAINED`, before starting the
measured host: clock programming completed, but the second strict prelaunch
check saw full PSI 1.08%. Raw available memory was 51.41 GiB and discounted
effective headroom 82.88 GiB. Both host logs are empty, cgroup pressure was
zero, peak cgroup usage was 135.4 MiB, and high/max/OOM events were all zero.
The top-level `attempts=[spine]` records the intended call, not proof that a
host process started. This is not the earlier ten-second live-child stop,
not OOM, and not a measured slowdown. The
[prelaunch failure receipts](qualified_lj08_prelaunch_failure_receipts.tar.gz)
retain all records except the indexed xclbin; archive SHA-256:
`9a24cdb0e1cd452713c506d199247861f880c4eadb4a0ce3376db2e97e139275`.

The settling profile now permits a strict, bounded prelaunch wait as
described in the [memory guide](../../../../../../implementation/runtime/board_arc_admission.md).
This does not relax PSI or memory thresholds, retry an executed arm, change
the qualified Spine host or screened G+R image, or supply a sixteenth pair.
The frozen fifteen-pair review archive remains unchanged. New execution
requires a new frozen runner and output directory; the failed receipt is
never rewritten.

The fresh prelaunch continuation uses frozen simulator commit `f684a1c7`,
service `gr-respr-qualified-lj08-prelaunch-20261105-v2.service`, invocation
`0c514a3df92a4f8a9351a87a952a84f3`, with the same 32/30-GiB limits,
zero swap, eight-hour runtime and qualified host/image. At 15:03 UTC it
had completed the Spine arm and started G+R. This is a live execution record,
not an accepted pair; both arms, clocks, final oracles and export gates must
pass before adding a row. There is no automatic repeat of either arm.

An earlier startup-only `gr-respr-qualified-lj08-prelaunch-20261105-v1.service`
(invocation `61c8796c78c04d58b977d52fdb726b1e`) failed with
`ModuleNotFoundError` because its new worktree was not yet ready. No output
directory, experiment host or board test was started. After worktree creation
finished, import and clean-source checks passed before the separate v2 launch.
This startup failure supplies no performance evidence.

On the run host, inspect the new exact handle and live report with:

```sh
systemctl --user status gr-respr-qualified-lj08-prelaunch-20261105-v2.service --no-pager
python3 -m json.tool /data/chuxiao/checks/source-retention-repair-20261104/respr-qualified-lj08-prelaunch-v2/results.json
```
