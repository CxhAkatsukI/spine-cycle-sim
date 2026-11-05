# CC Build Memory Follow-Up

The November 5 `spine-cc-stream-admit-resume-20261105-v1.service`
invocation `fc098f3fc0c44cb4a8e2c405ea8d787e` ended at 20:51 CST with
systemd `Result=oom-kill` and `MemoryPeak=111669149696` bytes: its full
104-GiB cgroup limit. This was a contained build failure, not an FPGA
measurement or a whole-host memory exhaustion. Immediately afterward the
499-GiB host reported 483 GiB available. The predecessor's last JSON says
`BUILDING` because the supervisor was killed with its group; that stale
checkpoint is not a successful completion receipt. Original logs remain in
`/data/chuxiao/cc-stream-resume-20261105-v1/` on seele.

## Explicit Replacement Policy

`hardware/source_retention/build_resume.py` now offers the separate
`192g-v1` profile: **192-GiB max, 184-GiB high, zero task swap, 128-GiB
live host reserve and 8-GiB background reservation**. It still requires a
host with at least 480 GiB RAM, reserves full finite peer limits atomically,
rejects unbounded compiler peers and checks containment/reserve throughout.
The unchanged default is `104g-v1`. Tests check both limits and reject a
collector configured for a different memory profile.

This changes only the compiler's resource ceiling. Source, ABI, algorithm,
clock target, HBM wiring, synthesis/implementation concurrency and the
frozen [make script](../cc_resume_v1/cc-stream-build-resume-20261105.sh)
remain unchanged. It does not promise routing or timing closure.

From a fresh frozen checkout on the high-memory host:

```sh
module=spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.build_resume
python3 -m "$module" --memory-profile 192g-v1 --print-properties
# Supply those exact properties and a fresh unit/output to systemd-run.
python3 -m "$module" --memory-profile 192g-v1 \
  --script /data/chuxiao/cc-stream-build-resume-20261105.sh \
  --output /data/chuxiao/cc-stream-resume-20261105-v2
```

The latter command must run inside the declared cgroup; it does not create
containment itself. The matching `cc_au_collect` invocation must explicitly
select `--resume-memory-profile 192g-v1`; clean completion, exact unit and
invocation, original ABI log, artifact hashes, correctness smoke and the
resident comparison remain separate gates. Pending routing or the old
104-GiB failure cannot supply a CC speedup bar.

## Launched Replacement

The replacement passed atomic admission with 518,656,262,144 available
bytes, no competing compiler reservations and 352,187,318,272 required
bytes (192-GiB tree + 128-GiB reserve + 8-GiB background). Its first saved
checkpoint is `BUILDING`, not a route or board-test completion.

| Task | Exact unit / invocation |
| --- | --- |
| Remote build | `spine-cc-stream-admit-resume-20261105-v2.service` / `399a1a48cab642a5ade18796812f1aba` |
| Local collector and AU correctness/comparison | `spine-retention-cc-au-stream-resume-20261105-v2.service` / `579a21c92f744ee6a636a3cb399accd5` |
| Local follow-up matrix | `gr-retention-cc-stream-resume-matrix-20261105-v3.service` / `035b0877640e437c913ab4230c77223f` |

All three use fresh, detached source `c3db0f54`. The remote source is
`/data/chuxiao/fig8-portable-20261105/cc-build-budget-192-c3db0f54`;
local followers use `/data/chuxiao/worktrees/spine-cc-resume-192-c3db0f54`.
The frozen HLS build ABI remains
`caa178a765083ba21d6a6e3e900171f09a3e19957360db60af87f3c8fb869574`.

Live output paths are:

- Remote: `/data/chuxiao/cc-stream-resume-20261105-v2/execution.json`
  and sibling `build.log`.
- Collector: `/data/chuxiao/checks/source-retention-repair-20261104/cc-au-stream-resume-20261105-v2/results.json`.
- Follow-up: `/data/chuxiao/checks/source-retention-repair-20261104/cc-warm-stream-resume-matrix-v3/`.

The collector retains its 24/22-GiB max/high, zero-swap limit and an 18-hour
wait. It explicitly selects `192g-v1` when validating remote completion.
The matrix supervisor has a 2-GiB limit and still waits for the exact
collector invocation and correct AU result before requesting other cases.
Board leases, per-child admission and correctness gates remain mandatory.
These queued follow-ups are not a promise that routing or all tests finish.

## Terminal 192-GiB Failure

The exact v2 build above ended at 23:21 CST on November 5 with
`Result=oom-kill`, `ExecMainStatus=9` and a 206,158,430,208-byte (192-GiB)
peak. Its collector and dependent matrix also terminated, without a new
CC sample. The build's last JSON still says `BUILDING`: group OOM killed
the supervisor before its final checkpoint. Systemd's terminal state, not
that stale JSON, determines the outcome. Its original per-attempt log and
receipt are retained; the next attempt reuses the original build directory
and can replace intermediate tool products there.

[Retained 192-GiB failure receipts](192g_failed_receipts.tar.gz) contain the
original remote execution checkpoint/build log and the terminal local
collector/matrix reports. Archive SHA-256:
`1aa98331b7f3baf0face2bfd6497cc350d8bc6f7b42a8bf8608c87bd50141bdf`.

At 15:24 UTC the remote host reported 519,523,016,704 available bytes
(about 484 GiB), so this was the task's imposed limit, not host exhaustion.
The separate explicit `320g-v1` policy now permits 320-GiB max / 304-GiB
high. With no peers it requires **456 GiB** at atomic admission (320 tree +
128 reserve + 8 background), and retains the same zero swap, live 128-GiB
reserve, >=480-GiB host check and exact-containment verification. Neither
older profile changes. The collector must select this new profile explicitly.

This is an operational resource change only, not a source/ABI change,
successful route, timing closure or a board result. A fresh invocation and
output are required; the failed v2 service is never restarted in place.

## Running 320-GiB Replacement

The separate v3 build passed admission at 15:29 UTC on November 5 with
519,461,150,720 available bytes, no peer reservations and
489,626,271,744 required bytes. Its observed status at 15:33 UTC was
`BUILDING`, with about 5.5 GiB in its cgroup. This is not routing completion.

| Task | Exact unit / invocation |
| --- | --- |
| Remote build | `spine-cc-stream-admit-resume-20261105-v3.service` / `c9a1583f0d644a1cb972bb29237c7abf` |
| Original local collector (superseded) | `spine-retention-cc-au-stream-resume-20261105-v3.service` / `e061098f78594c5d8081b89517440c53` |
| Original local matrix (superseded) | `gr-retention-cc-stream-resume-matrix-20261105-v4.service` / `bb56598515124534896760fae3983f8b` |

These three initial runners used frozen simulator source `5cd13bbc`. The remote runner
root is `/data/chuxiao/fig8-portable-20261105/cc-build-budget-320-5cd13bbc`;
the local follower worktree is `/data/chuxiao/worktrees/spine-cc-resume-320-5cd13bbc`.
The remote supervisor SHA-256 is
`8f96c62065210671bf1ddf586436c8e617fd8e1e104f537dec7c7b5372ee345f`.
The HLS source, ABI and frozen make-script hash remain unchanged.

New receipts, distinct from both failed predecessors:

- Remote: `/data/chuxiao/cc-stream-resume-20261105-v3/execution.json`
  and sibling `build.log`.
- AU collector: `/data/chuxiao/checks/source-retention-repair-20261104/cc-au-stream-resume-20261105-v3/results.json`.
- Matrix: `/data/chuxiao/checks/source-retention-repair-20261104/cc-warm-stream-resume-matrix-v4/matrix.json`.

The collector explicitly requires `320g-v1`, retains its 24/22-GiB max/high
and zero swap, and waits for the exact new invocation. The matrix retains
its 2-GiB limit and cannot launch later cases until AU passes. No CC bar is
admitted by this launch record. The newly completed LJ08 ResPR pair is
independent of these queued CC tests.

### Local ARC-Aware Followers

Both original local followers were deliberately stopped while still waiting,
before either attempted a board run. Their reports and systemd journal
entries retain the original unit and invocation. The remote build was not
stopped or restarted.

The replacements run frozen source `c03ca5e2` in
`/data/chuxiao/worktrees/spine-cc-board-arc-c03ca5e2` and select
`zfs-arc-clean-half-settle10-v1` only for local board admission. They retain
the same memory limits, zero swap, route and input identities, single-pass
tests, clocks, correctness checks and timing boundary. No global ARC
setting changed.

| Task | Exact unit / invocation |
| --- | --- |
| AU collector | `spine-retention-cc-au-stream-resume-20261105-v4.service` / `c5294337b09b4fdd83bf28f09fd953fe` |
| Follow-up matrix | `gr-retention-cc-stream-resume-matrix-20261105-v5.service` / `161594dc941347d295cf7f36424fc342` |

The local reports under `/data/chuxiao/checks/source-retention-repair-20261104`
are `cc-au-stream-resume-20261105-v4/results.json` and
`cc-warm-stream-resume-matrix-v5/matrix.json`. At replacement, the remote
build was still synthesizing, the collector was waiting for its route and
the matrix was waiting for AU. This update does not admit any CC result.
