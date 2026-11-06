# Link Evidence Retention

## Failure And Scope

The exact `spine-cc-stream-link-fresh-20261106-v1.service` invocation
`fbb13007b3984adc92d0dcbcb5c7baaf` completed Vitis linking and packaging
on seele at 15:29 CST, November 6. The script subsequently exited 1 when
copying the raw skew report: Vitis had removed its temporary project.
The HLS Makefile's compile-only `VPP_FLAGS` contained `--save-temps`, but
`VPP_LINK_BASE_FLAGS` did not. The agent's previous recovery script therefore
repeated the evidence-loss failure. This is not a compiler OOM, correctness
failure or proof that skew constraints passed.

The image remains at
`/data/chuxiao/spine-cc-stream-admit-2315cae-route-v2/xclbin/spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.xclbin`,
SHA-256 `0939fc5b51133cf79954c266434c502f1ac8cd9f541a0200d5f331931e373d28`.
Ordinary timing reports show setup WNS +0.002 ns and hold WHS +0.009 ns.
The log proves the skew-report hook ran; it does **not** reveal the report's
slack. No routed checkpoint survives. Missing evidence is not a pass.

The build peaked at 259,455,295,488 bytes (241.64 GiB), below the explicit
320-GiB task limit; all saved cgroup memory events are zero. Both dependent
local services terminated without requesting a board execution:

| Service | Invocation |
| --- | --- |
| `spine-retention-cc-au-fresh-link-20261106-v2.service` | `e3007078573249d3b279543d2256b3ca` |
| `gr-retention-cc-fresh-link-matrix-20261106-v2.service` | `225e50b5f04441d4bcd0c040ff4721f4` |

[Immutable failure receipts](fresh_link_retention_failure_receipts.tar.gz)
include the execution JSON, build/Vivado logs, ordinary timing, terminal
service properties and failed collector/matrix reports. Archive SHA-256:
`4dbf94d27f4504d1aecd2ced4354307eff8d2f35398ae70129671d7a92bf9097`.

## Correction

The new [frozen link script](cc-stream-link-retained-20261106.sh) uses the
fresh root `/data/chuxiao/spine-cc-stream-admit-2315cae-route-v3`. It does not
overwrite either old image or receipt. The host, three XOs, source and CC
connectivity are copied and hash-checked. The existing 734-MiB synthesis
cache is copied, not modified in place. Cache reuse is an optimization, not
evidence of a completed or numerically equivalent new link.

The script explicitly passes `--save-temps` through **link** flags and
`--remote_ip_cache` through the existing Makefile API. The same Bash array
drives a dry run and the real invocation. The small `source_retention.link_retention`
module rejects a dry run unless it contains exactly one link, no XO
compilation, `--save-temps`, and the exact image/temp/cache paths.
`link-command.txt` and `link-command-validation.json` preserve that check.
After link success the script requires the raw skew report and routed DCP
to exist and copies both into durable `reports/` as well. These changes do
not alter numerical kernels, ABI, topology, 150-MHz target or tool jobs.

Focused regression tests cover the original error (compile-only retention),
missing/wrong/duplicate paths, missing or multiple links, accidental XO
recompilation and shell quoting/continuations. This preflight does not
substitute for the existing route, raw skew, correctness or paired-time gates.

## Replacement Status

The first retained-link launch, `spine-cc-stream-link-retained-20261106-v1.service`
invocation `cbf15a1dd9b64a039c91c4f65a716dc6`, was rejected before starting
tools because another user's compiler had no finite cgroup memory budget.
The host had about 477 GiB available; an unbounded peer is not an ARC or
low-available-memory diagnosis. Its receipt is retained remotely at
`/data/chuxiao/cc-stream-link-retained-20261106-v1/execution.json`.
No link command was executed in the new HLS root.

The shared supervisor now has an explicit `--admission-wait-seconds` option
(default zero, maximum two hours within the existing total deadline).
It records `WAITING_FOR_ADMISSION`, rechecks under the atomic lease lock,
and holds no compiler lease or tool process while waiting. Unknown peers
or insufficient full budgets are never admitted. Changed/missing containment
fails immediately; a finite wait can expire without starting tools. Tests
cover admission after a peer retires, both timeout causes and unchanged
default rejection. This does not change the `320g-v1` resource policy:
320/304-GiB max/high, zero task swap, atomic full-budget admission and a
128-GiB live host reserve. No host cache-clearing or ZFS settings change is
required. A fresh launch/output is required. Local followers identify its
exact successful build,
then pass the AU correctness/replay gate before requesting the other seven
CC pairs. The frozen formal result remains **16/24 pairs; eight CC missing**.

## Active Queue, November 6

At 15:51 CST the replacement build was `WAITING_FOR_ADMISSION`, the AU
collector was `WAITING_FOR_ROUTE`, and the matrix was
`WAITING_FOR_WARM_CC_AU`. The observed host had about 478 GiB available;
four compiler processes from one foreign, unbounded cgroup prevented
admission. No compiler had started in the v3 root. The two-hour admission
wait does not remove the finite-peer requirement or alter another user's
task. These are launch observations, not final execution receipts.

| Task | Exact unit / invocation |
| --- | --- |
| Remote link | `spine-cc-stream-link-retained-20261106-v2.service` / `00449cce4545414eb4047c88c76236d6` |
| AU collector | `spine-retention-cc-au-retained-link-20261106-v2.service` / `04bfdcc356304613846852941c270dec` |
| CC matrix | `gr-retention-cc-retained-link-matrix-20261106-v1.service` / `2700c7f30d524fdcab6294141ae3d338` |

The frozen runner source is simulator commit `7d6aca20`. Local followers
use `/data/chuxiao/worktrees/spine-link-retained-wait-20261106`; the remote
runner uses `/data/chuxiao/cc-link-retained-wait-runner-20261106`.
The link-script SHA-256 is
`dfeadb69fc0aec749a6aad2ebdf6d84af4e005c63fbc350c9eba69f946ac1236`;
the new supervisor SHA-256 is
`b9b7173d02a4edf2f91f442e37ece718eb6e53698b7639b8046c35f7835eab4f`.
Hardware source `2315caefdaa40b4a4fb9619f6286232aafa8dee7` and ABI
`caa178a765083ba21d6a6e3e900171f09a3e19957360db60af87f3c8fb869574`
are unchanged.

Live receipts, distinct from every earlier attempt:

- Remote: `/data/chuxiao/cc-stream-link-retained-20261106-v2/execution.json`;
  sibling `build.log` is created only after admission.
- AU: `/data/chuxiao/checks/source-retention-repair-20261104/cc-au-retained-link-20261106-v2/results.json`.
- Matrix: `/data/chuxiao/checks/source-retention-repair-20261104/cc-warm-retained-link-matrix-20261106-v1/matrix.json`.

After successful link and raw-skew validation, the collector requests one
resident AU execution against its pinned G+R anchor. Only a passing exact
AU receipt releases the other seven paired CC executions. Collector limits
remain 24/22 GiB max/high; the matrix coordinator remains 2/1 GiB and each
board child 32/30 GiB, all with zero task swap. There is one repetition per
arm, with no warmups. Board leases, ARC-aware admission and correctness
checks remain mandatory; a queued follower does not establish a speedup.

Verification before launch: 58 focused runtime/evidence tests and 15
repository-organization tests passed, as did document-layout, catalog and
whitespace checks. No numerical simulator, kernel or frozen figure data
changed in this recovery.

An additional compiler-free check generated the command from the actual
copied Makefile, using the frozen script's exact argument array. Its
[dry-run output](link-plan-preflight-20261106.txt) passed
[link-command validation](link-plan-preflight-20261106.json), with plan
SHA-256 `d9d7f788e0916bd83e51e75081d258aa560f399d64bd49c0f3b4fc32872b2e83`.
All inherited artifact hashes also passed. This check writes neither the
live build's plan nor an image; the admitted build must repeat it before
starting Vitis. It is not routing, clock or performance evidence.

## Matrix Coordinator Repair

An offline replay on November 6 found that `cc_warm_matrix` omitted the
required algorithm argument when validating the odd-frontier R control.
The earlier test used an unrestricted mock and missed the signature error.
The failing test reproduces the error before the fix; the corrected call
passes `cc` explicitly. Signature-checked regression tests also exercise
the replacement-AU continuation across all seven remaining datasets,
preserving the same candidate, baseline controls and one-shot protocol.
The focused evidence/runtime/organization suite passes all 139 tests.
Document-layout, catalog and whitespace checks pass as well.

Only the waiting matrix coordinator was replaced. Its exact invocation
`2700c7f30d524fdcab6294141ae3d338` still reported
`WAITING_FOR_WARM_CC_AU`, with all eight cases `NOT_REQUESTED`, before it
was stopped. The old output and frozen runner remain intact; this is a
coordinator correction, not a failed hardware measurement. The remote
retained-link invocation and AU collector listed above were not restarted.

The replacement is `gr-retention-cc-retained-link-matrix-20261106-v2.service`,
invocation `d7d53a88b8044c30aaaefcfa17753dc9`, running clean frozen commit
`14cfb326dee5096975b14a58e78c48116969187e` from
`/data/chuxiao/worktrees/spine-cc-matrix-control-fix-20261106`.
Its output is
`/data/chuxiao/checks/source-retention-repair-20261104/cc-warm-retained-link-matrix-20261106-v2/matrix.json`.
Only the output, child-unit prefix and runner source changed; the pinned AU
parent, stage/layout receipts, memory policy, budgets and timing boundary
are unchanged. The launch receipt, including the old observation and exact
new command, is
`/data/chuxiao/checks/source-retention-repair-20261104/cc-warm-matrix-control-fix-20261106-handoff.json`,
SHA-256 `d065e4e1f993268603d5936b4c2eb9f2df1644e08f10c265e1478c9c61c0ef63`.
The new coordinator is waiting for the same AU parent; this correction adds
no measured pairs. The formal checkpoint remains **16/24**, with CC pending.
