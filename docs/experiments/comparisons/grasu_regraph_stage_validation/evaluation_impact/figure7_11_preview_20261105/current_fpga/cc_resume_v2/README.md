# CC Build Memory Follow-Up

## Current Status, November 6

The 320-GiB build completed routing with setup/hold timing met at the
150-MHz target. Packaging succeeded after adding two private Boost libraries.
The successful image is preserved, but an agent-caused packaging retry deleted
the original temporary bus-skew report. **No new CC performance sample is
admitted.** A direct AU correctness diagnostic now passes state, work and
clock checks under bounded ARC-aware admission; a separate fresh link is
rebuilding complete route evidence from the same host, XOs and wiring.
See the [diagnostic and current queues](#arc-admission-and-au-diagnostic)
and the [recovery record](#route-packaging-and-evidence-recovery).
The dated records below are retained history, not current build status.

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

### What The Queued CC Batches Change

An offline topology audit checked the exact graph and update byte counts
and SHA-256 digests pinned by the AU collector anchor and the seven matrix
input manifests above. It treated every old directed record as an
undirected edge for union-find and checked that the 16 update records form
eight distinct reciprocal insertions. Each insertion is classified against
the **old** connected components, before applying any of the batch.

| Dataset | Old directed edges | Inserts within old components | Inserts across old components | Input manifest SHA-256 |
| --- | ---: | ---: | ---: | --- |
| AU | 679,246 | 8 | 0 | `2222676a7e2993ae969b9dec2e54c3dfabedbbbe5bcf35f08e0e7ec833332a74` |
| SU | 1,061,248 | 8 | 0 | `9486fae3e66b1cc0755febd68a731206754a1926eca7abe7d70211309fb97a1e` |
| WK | 2,032,558 | 1 | 7 | `ef3d5ebc4af75f80535bc45c53ac2d26f6a2e6e8c4ab931098f235d536e301b4` |
| SO | 41,008,044 | 8 | 0 | `239e1660410802e3eb9c367bc8f3fc356666a38a1ce4495e7b376af582fbfb0a` |
| PK | 44,603,928 | 8 | 0 | `87c4ed14d003444caee54b3977bf12c7debbad78ba663450aee31b483014a571` |
| LJ | 85,702,474 | 8 | 0 | `7c469824ebf49946d6cc89119c2ad9aeb6622bd47c37e27bd16131a5c55091dd` |
| LJ08 | 99,028,542 | 8 | 0 | `d05ba4f7e47470da103471f9ff21a8e057cab4fc105da40da313ce0efe27b98e` |
| R19 | 29,732,038 | 6 | 2 | `2edadba1f26b126b442c34e18f3d224df5eb39158201326bf4b7d9b599499d5c` |

The AU digest is that of the collector's pinned
`cc-warm-au-source-bursts-resident-v8/results.json` anchor; the other
digests are of the corresponding `inputs.json` files passed to the matrix.
For six batches the edges still have to be inserted, but the CC partition
and converged minimum labels do not change. WK and R19 require a change in
CC state. Cross-component insert counts are not counts of distinct merges,
changed vertices, propagation rounds or device cycles. This check does
not replace the paired FPGA runs or admit any Fig. 7 bar; all eight tests
remain in the matrix.

### Synthesis Diagnostic For The Queued Image

The remote `2315cae` build passed HLS and entered Vivado block synthesis.
At about 89 minutes into that phase, the build cgroup used about 244 GiB
(238 GiB anonymous memory), with no cgroup high, max or OOM events at that
sample. This is compiler memory on seele, not the local board host's ZFS
file cache. Neither placement nor routing was complete.

The HLS reports under `temp/compile_engine-4-1-2-2-1/` in the remote build
root `/data/chuxiao/spine-cc-stream-admit-2315cae-route-v1` show two instances
of the same row walker in distinct CC command paths:

| HLS hierarchy | Estimated LUTs |
| --- | ---: |
| `cc_control / cc_admit_source / spine_row_next` | 46,054 |
| `cc_control / cc_live_row / spine_row_materialize / spine_row_next` | 46,054 |
| `spine_partconv_rdmaint_kernel` (entire kernel) | 444,417 |

See `cc_control_csynth.rpt` and the top-level `*_csynth.rpt` in the HLS
solution's `syn/report/`. These are HLS estimates, not placed utilization;
the top estimate is slightly above the report's nominal single-SLR LUT
capacity of 434,560, not above whole-device capacity. The duplicate walkers
are a candidate for resource reduction, not a diagnosis of the earlier OOM
or a demonstrated routing or latency fix. Admission and propagation run
sequentially; a reviewed shared walker would need to retain streamed
admission without HBM scratch and bounded row materialization for propagation.
No such source change is in the running build or the queued board tests.

The same invocation (`c9a1583f0d644a1cb972bb29237c7abf`) subsequently
completed Vivado 2024.1 out-of-context `synth_design` for the CC kernel in
2 h 18 min 36 s, with zero errors, and wrote a checkpoint. Its synthesized
utilization report lists **190,148 CLB LUTs** (171,363 logic and 18,785
memory), 239,007 registers, 68 BRAM tiles and 27 DSPs. The report accounts for
LUT combining; use this count rather than summing the raw LUT primitives
in `runme.log`. The report is
`ulp_spine_partconv_rdmaint_kernel_1_0_utilization_synth.rpt` in
`temp/partitioned_split_e2e_link_engine-4-1-2-2-1/link/vivado/vpl/prj/prj.runs/ulp_spine_partconv_rdmaint_kernel_1_0_synth_1/`
under the same build root (SHA-256
`b789e8235fd3e599603446faa8f0ba9c49751733ed54ecf8ed90b3c9e40ff564`).
This supersedes the HLS estimate as evidence of the synthesized kernel's
size. It is not a placed platform or per-SLR report, does not show that the
walkers were deduplicated, and does not establish timing closure or a
board-ready image. The queued paired tests remain gated on the exact
packaged image and board correctness.

## Route, Packaging And Evidence Recovery

The v3 implementation above subsequently finished route and bitstream
generation on November 6. Its retained final timing report says all user
constraints are met: setup WNS +0.002 ns / TNS 0, hold WHS +0.009 ns / THS 0,
and zero failing pulse-width endpoints. The build then failed in packaging:
XRT's `xclbinutil` could not find `libboost_filesystem.so.1.74.0` and
`libboost_program_options.so.1.74.0`. This was not a routing or board failure.
The original build peaked around 244 GiB without an OOM event under `320g-v1`.

The libraries were copied into the private
`/data/chuxiao/cc-stream-package-runtime-20261106/lib` on seele; no global
library or ZFS settings changed. The [packaging-only script](cc-stream-package-resume-20261106.sh)
succeeded in invocation `1b85c876f7194daeb9d495965b8e0972` of
`spine-cc-stream-package-resume-20261106-v1.service`. Its image, adjacent
manifest and successful Vitis log were moved out of the disposable project
before the next attempt. Local copies are in:

```text
/data/chuxiao/checks/source-retention-repair-20261104/cc-stream-packaged-return-20261106-v1/
  spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.xclbin
  spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.xclbin.weighted-manifest
  v++_spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.log
  host_cc_repair
  impl_1_hw_bb_locked_timing_summary_postroute_physopted.rpt
  vivado.log
```

Image SHA-256: `4c5e9ee7648cb57de2e47d3b43cd9913e0cc45df9b997a9ca70633c066a97987`.
Host SHA-256: `f16bb3c7cd69d461e4fd35ed2b2db3933f717a29e66f5984f5808ea4ac9622a1`.
The image is 59,042,593 bytes and has the unchanged ABI printed above.
These large binaries are indexed here, not duplicated into Git.

The v1 collector rejected the short systemd launch description before any
board test. The agent incorrectly retried packaging to obtain a different
launch record. Vitis recreated its temporary project, deleting the original
routed checkpoint and raw `bus_skew_routed.rpt`; that v2 attempt was stopped.
The saved image and final timing/Vivado logs remain intact. The raw skew
report is **missing**, so the existing complete-route gate cannot be replayed
for this image. A report-generation marker in the log does not establish
passing skew slack. Neither an older image's report nor a reconstructed
report is substituted.

The independent diagnostic `spine-cc-packaged-au-smoke-20261106-v1.service`
(invocation `47193ef017764bfd81c218d500ed62ef`) uses the saved image and frozen
AU inputs. Its report is
`/data/chuxiao/checks/source-retention-repair-20261104/cc-stream-packaged-au-smoke-20261106-v1/results.json`.
At 07:27 CST it was still waiting for memory-pressure admission, not running
on the FPGA. It explicitly records `performance_admission: false`. Even a
successful diagnostic does not replace the missing route gate.

### Fresh Link And Queued Tests

The [fresh-link script](cc-stream-link-fresh-20261106.sh) runs a normal link
in the separate `/data/chuxiao/spine-cc-stream-admit-2315cae-route-v2` on seele.
Host, all three XOs and `system_cc_repair.cfg` match the predecessor's
SHA-256 digests. A retained `make -n` confirms no host/HLS recompilation and
the same 150-MHz configuration and ABI. The script verifies inherited
artifact hashes and copies the final skew report and routed checkpoint out
of the disposable project after success. It must not be rerun over an
existing output image. Its SHA-256 is
`a3b39b8ed67a054a98da6ebb07a29109e3afa8a9f9d5f561f2f9420195cc94a1`.

| Task | Exact unit / invocation |
| --- | --- |
| Fresh remote link | `spine-cc-stream-link-fresh-20261106-v1.service` / `fbb13007b3984adc92d0dcbcb5c7baaf` |
| AU route collector and paired check | `spine-retention-cc-au-fresh-link-20261106-v1.service` / `cf6c19a6b55944ca8dfe269993466b43` |
| Remaining seven datasets | `gr-retention-cc-fresh-link-matrix-20261106-v1.service` / `89f5bd3760744eb8935e6baa1e098eab` |

The remote supervisor remains frozen `5cd13bbc`, `320g-v1`, with a 128-GiB
live reserve and zero task swap. Local followers remain frozen `c03ca5e2`
with `zfs-arc-clean-half-settle10-v1`; correctness, route, clock and paired
timing gates are unchanged. Reports respectively live at:

- `/data/chuxiao/cc-stream-link-fresh-20261106-v1/execution.json` on seele.
- `/data/chuxiao/checks/source-retention-repair-20261104/cc-au-fresh-link-20261106-v1/results.json` on trif.
- `/data/chuxiao/checks/source-retention-repair-20261104/cc-warm-fresh-link-matrix-20261106-v1/matrix.json` on trif.

All are pending at this checkpoint; no CC bar or all-win claim follows from
launching them. The already accepted sixteen SSSP/ResPR pairs are unchanged.

### ARC Admission And AU Diagnostic

The v1 local queues above were stopped while idle, after preserving their
unit properties, exact commands and pending reports. The diagnostic had
not started its board child; the collector and matrix were waiting on
their predecessors. Their frozen reports were not overwritten. No remote
build or other user's task was stopped.

The earlier request for administrator cache release was unnecessarily
conservative. ARC is reclaimable without manually clearing it. With the
half-clean-ARC estimate, roughly 79 GiB was available at the new smoke's
admission, exceeding its full 24-GiB budget plus 32-GiB reserve. The old
queue instead rejected the approximately 2% global full PSI against its
1% threshold, even with no owned board child running. This was a pressure
policy rejection, not proof of insufficient capacity or OOM.

The separately declared
[`zfs-arc-clean-half-background5-v1`](../../../../../../../implementation/runtime/board_arc_admission.md#background-pressure-profile)
keeps full budgets, the reserve, cgroup limits, zero task swap, exclusive
board leases and timeouts. It permits full PSI below 5%, some below 10%,
and stops a running child after ten consecutive seconds above the limits.
Missing observations or a physical-reserve breach still stop immediately.
Old profiles are unchanged. The new runners use clean frozen source
`ad6fea1e00c2a379a524403c675453e4d6e60047` at
`/data/chuxiao/worktrees/spine-board-background-ad6fea1e`.

The AU diagnostic completed at about 07:47 CST on November 6:

| Check | Observation |
| --- | --- |
| Workload | 515,281 vertices, 679,246 old directed edges, eight reciprocal insertions / 16 physical records |
| State and work | All raw labels, graph and round work pass; eight within-component insertions, zero propagation rounds |
| Actual clock | Driver reports 150/500/450 MHz under the exclusive board lease |
| Host pack to final checked readback | 4.542262 ms |
| Batch resident to final checked readback | 4.413918 ms |
| Containment | 24/22-GiB max/high, zero swap, group OOM enabled; peak 9,177,985,024 bytes (8.55 GiB) |
| Live observations | Minimum discounted available 77,204,808,704 bytes (71.90 GiB); maximum full/some PSI 2.0%; no pressured checks |
| Memory events | High, max, OOM and OOM-kill all zero |
| Admission status | Correctness-only; `performance_admission: false` |

This is not a fresh G+R pair or an admitted Fig. 7 point. It checks the
saved image despite its missing raw skew report; it cannot repair that
missing evidence or establish performance on WK/R19's propagation cases.
The linked fresh image must independently pass its complete route and
board gates before replacement performance data are exported.

| Current task | Exact unit / invocation | Report under `/data/chuxiao/checks/source-retention-repair-20261104/` |
| --- | --- | --- |
| Completed diagnostic | `spine-cc-packaged-au-smoke-20261106-v2.service` / `3cba804f01dd4e3997b04110dcec3abb` | `cc-stream-packaged-au-smoke-20261106-v2/results.json` |
| Waiting for fresh remote link, then AU check | `spine-retention-cc-au-fresh-link-20261106-v2.service` / `e3007078573249d3b279543d2256b3ca` | `cc-au-fresh-link-20261106-v2/results.json` |
| Waiting for that exact AU collector, then seven cases | `gr-retention-cc-fresh-link-matrix-20261106-v2.service` / `225e50b5f04441d4bcd0c040ff4721f4` | `cc-warm-fresh-link-matrix-20261106-v2/matrix.json` |

At the 07:49 CST snapshot the unchanged remote invocation remained
`BUILDING` in block synthesis, using about 11.1 GiB. The collector and
matrix were waiting, not measuring. The local launch initially rejected
unsupported systemd property `MemoryOOMGroup=yes` before starting any new
unit. Launching with supported `OOMPolicy=kill` then produced verified
`memory.oom.group=1`; no containment requirement was removed. The focused
runner/policy regression suite passed all 85 tests.

[Admission, queue replacement and diagnostic receipts](background-admission-au-smoke-receipts.tar.gz)
retain the old idle-queue records, three new launch/containment receipts,
tests, exact diagnostic outputs and clocks, and dated pending local/remote
snapshots. SHA-256:
`0632ae28e5e7ff518e5cf7fffc24d9d0cf48aeb238d8631fd1abe77e58abb91c`.
The archive is a frozen checkpoint, not live status or completed CC coverage.

### Retained Recovery Receipts

| Archive | Scope | SHA-256 |
| --- | --- | --- |
| [Packaging failure](package-failure-receipts.tar.gz) | Original v3 packaging failure and terminal followers | `0a7fc5ea75c2da20f5e8beaf6538a224f9c56942330af5eb5534a94ac76b5e69` |
| [Collector v1](package-collector-v1-failure.tar.gz) | Successful packaging receipt and rejected collector/matrix | `205ca00f05c4c12d2173baaf38fca1af9970bc53e40a08126a563f88dc3ed0e0` |
| [Stopped v2 followers](package-followers-v2-failure.tar.gz) | Terminal collector/matrix without a board run | `a190e4f36e99c8684cda1c22c61d6964670d2e3d0a71530e1ef9ad1f7fddb192` |
| [Route and packaging](route-packaging-receipts.tar.gz) | Final timing, Vivado log, successful packaging log/manifest, interrupted retry, unit records, library hashes, inherited-artifact hashes and dry-run command | `1350ac4f8c255a52aa5e421662516dc3f7960059104bdcf8c751c7026fc27f7d` |
