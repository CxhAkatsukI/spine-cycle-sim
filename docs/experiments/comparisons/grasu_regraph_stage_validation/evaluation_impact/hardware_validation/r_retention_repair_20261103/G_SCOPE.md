# Independent G Hardware Evidence

The four frozen AU controls compare the public-source GraSU update path
against the **weighted-SSSP integrated image**. All four satisfy the
1.15 elapsed-time gate on the reported nine-CU envelope. This is a
public-source control, not a claim to reproduce the paper's throughput.
The original run did not capture per-arm driver clocks. The integrated
host waited for its PMA completion barrier and checked the final PMA;
the barrier itself was not profiled in the envelope, so completion after
the final shard's last timed CU is not covered by that ratio.

The image roles are in `campaign-v1/results.json` under
`/data/chuxiao/checks/source-retention-20261103-v1/`. The following
short SHA-256 prefixes identify the linked XOs in the local build
manifests (not the routed timing):

| Integrated image | Cache | Search | DDR update | Device degree |
| --- | --- | --- | --- | --- |
| Weighted SSSP, tested in the AU G control | `54fba5fb` | `679b7178` | `a53bb128` | No |
| CC, not tested in that control | `54fba5fb` | `eb61ecf8` | `1f410c07` | No |
| ResPR, retained in the adapter repair | `84080cad` | `e8b7ff02` | `f72a6a1f` | `d081d64c` |

The SSSP and CC pins come from
`/data/chuxiao/builds/grasu-cache-extent-20261025/route-zfs-v2/{sssp,cc}/manifest.json`.
The repaired ResPR pins come from
`/data/chuxiao/builds/gr-directory-spans-20261103/route-respr-v1/manifest.json`.
Keeping ResPR's G XOs unchanged is useful for interpreting the adapter
repair, but is not independent evidence of ResPR's G performance.

## ResPR Single-Run Screen

- Start with one resident AU 131,072-update case, using the same frozen
  graph, operation sequence and 65,536-vertex destination partition size
  on both arms. Check logical update/shard counts and report the physical
  PMA footprints and metadata layouts separately.
- Run public-source G and the integrated ResPR update-only path once
  each on the same U55C, with an exclusive lease for each measurement.
  Capture each loaded image UUID, actual clock, host binary and affinity.
  The rebuilt public-source probe removes the original four-repeat loop
  and redundant state restore; the PMA and event checks are unchanged.
- Report first update CU start through last update CU end, including
  host gaps between shards. For ResPR, include the degree-update CU
  and in-window status transfers; report the final status check
  separately. Keep initial graph/batch residency and result readback
  outside both elapsed windows. Do not substitute the sum or union of
  busy intervals for elapsed time.
- Validate final PMA contents on the public-source arm, and touched PMA
  segments and out-degrees on the native ResPR arm. Report that difference
  in oracle coverage. The public-source arm does not maintain out-degrees;
  report this extra integrated work explicitly, without subtracting it
  from the measured elapsed ratio.

### Measured Public-Source Arm

The public-source arm completed once: **18.413633 ms** for 131,072 updates
over eight shards. All 72 update-CU events and 33,554,688 PMA words
(including guard/storage capacity) were checked. The driver reported
`150/500/450/0 MHz` on `0000:c1:00.1` with image UUID
`565fef9d-96ec-942d-44d0-178862832e4e`. Peak host cgroup memory was
822 MiB, with no memory-limit or OOM events. This is one arm, not a pass
of the integrated G gate.

The [portable raw evidence](g-reference-once.tar.gz) contains the source
snapshot, host build manifest and flags, command, input/image identities,
raw event log, and driver clock record. It does not duplicate the frozen
AU graph or the bitstream. Replay after extracting the archive with
`profiled_runs(results["row"], extracted_root)` from
`spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.analysis`.
The one-shot host builder and leased runner are the `reference_once` and
`reference_board` modules under
`spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board`.
Each accepts `--help`; the board runner requires a cgroup limit of at
most 8 GiB with zero swap. Local uncompressed evidence:
`/data/chuxiao/checks/source-retention-repair-20261104/g-reference-board-v1/`.

### Qualified Card 0 Public Reference

The public AU 131,072-update control was run once on the same U55C used
by the current R queues, `0000:82:00.1`. The update event span was
18.368928 ms; the full PMA oracle passed. Physical clocks read back
150/500/450 MHz before and after the arm. The older card 1 receipt below
remains historical and is not the denominator for the new queues.

- Receipt: `/data/chuxiao/checks/source-retention-repair-20261104/g-reference-card0-v1/results.json`
- SHA-256: `c431518e8b98a44153c53b8dd5f035f6dd570445ac9ba4d943b6c75a9545f26f`
- Producer: `gr-retention-g-reference-card0-20261104-v1.service`,
  invocation `9f1f0c8fb1fc4fd19d94298f961d0ac6`

This establishes the denominator only. Each candidate still has to pass
the full PMA oracle and the latency limit on the exact image used by its
R control. A failed R performance screen does not turn an independent G
measurement into a joint admission.

### Candidate Readiness

The pinned production ResPR host passes offline preparation on the same
AU input (515,281 vertices, 390,847 initial edges, 131,072 logical and
physical updates, eight shards, and 2,245,472 logical PMA slots). The
candidate runner uses that host's `--update-only` path on the exact image
from the completed R screen. It validates all ten CU events per shard and
checks the elapsed window against the host's reported total. The raw logs
also permit reporting busy time separately. A completed R performance
failure still permits this independent G diagnostic; it cannot admit the
combined baseline. The runner does not program the old image while
waiting or run an untimed warmup.

Reproduction entry point:
`python3 -m spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.candidate_board --help`.
Use the frozen reference result, native host build directory, exact route,
and completed R report in a fresh cgroup with at most 8 GiB and no swap.
Unchanged G XOs do not guarantee unchanged routed clocks or timings.

### Packed-Validity ResPR Result

The packed-validity ResPR image from the [nominal R screen](LOWER_CLOCK_SCREEN.md)
was measured once against the frozen card 0 public control. Both used
`0000:82:00.1` and read back `150/500/450/0 MHz` before and after.
The public PMA oracle and the integrated PMA and degree oracles passed.

| AU, 131,072 updates | Elapsed update window | Relative to public G |
| --- | ---: | ---: |
| Public-source GraSU | 18.368928 ms | 1.00x |
| Packed-validity ResPR image | 133.499578 ms | 7.27x |

The integrated image spends 131.506600 ms inside the union of CU event
intervals and 1.992978 ms in inter-shard gaps. Thus the observed gap cannot
be explained by inter-shard host relaunch alone. The integrated path also
maintains out-degrees, unlike the public update kernel. The source issues
an HBM read-modify-write per degree delta and dispatch can block on the
degree stream. Overlapping CU events cannot isolate this cost; there is
no no-degree ablation for this image.

The runner recovered the preserved failed R receipt after a reporting
error without reprogramming the card or repeating an R sample. The
[raw G evidence and joint replay](respr-packed-nominal-g-board.tar.gz)
retain the one sample from each arm and both clock records. The joint
replay returned `BASELINE_STAGES_NOT_ADMITTED`: G exceeded the elapsed
limit and the skewed R fixture exceeded it independently. No resident
Spine comparison was run on this image.

### Strict ResPR Stage Replay

The queued ResPR runners preserve per-arm clock evidence, but their original
status labels do not require equality between reference and candidate
clocks. Before promoting any queued resident result, replay the raw stages
with `source_retention.respr_retention_audit`. It checks both R cases against
the frozen public A4 image, input hashes and superstep profile, recomputes
the device event envelopes, and requires the same driver clocks within each
R pair and within the independent AU G pair. The G PMA oracle and raw event
envelope must replay on the exact R-screened image and resident host.
The candidate clock must also agree across the two R cases and G. A
successful receipt is stage evidence, not a convergence comparison.

```bash
root=/data/chuxiao/checks/source-retention-repair-20261104
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.respr_retention_audit \
  --r-board "$root/after-follow-v2/board-once/results.json" \
  --frozen-r-board "$root/before-once/results.json" \
  --route /data/chuxiao/builds/gr-directory-spans-20261103/route-respr-v1 \
  --r-report "$root/after-follow-v2/results.json" \
  --g-report "$root/g-candidate-board-v2/results.json" \
  --g-reference "$root/g-reference-board-v1/results.json" \
  --host /data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/hosts/respr/sharded_k4_residual_pagerank_native_host \
  --output "$root/respr-directory-strict-audit.json"
```

For R-only replay, omit `--route`, `--r-report`, `--g-report`,
`--g-reference` and `--host`. The pre-repair replay returned
`R_NOT_ADMITTED`: 1.361358 vs. 0.461233 ms on skewed sources, and
70.254409 vs. 10.365434 ms on Amazon. Those legacy receipts also lack
per-arm clocks. No new board sample is launched by this audit.

## CC And Weighted SSSP Single-Run Screens

The two adapter-repair images have separate update-only screens on the
same frozen AU 131K input. They reuse the measured public-source G arm on
`0000:c1:00.1`, not the old four-repeat weighted-SSSP campaign. Each
candidate waits for its exact completed route, then reserves its full
8-GiB host budget with a 32-GiB live reserve and leases that same board.
Its nine update CUs must match the declared roles on each of the eight
shards, and its touched PMA output must pass the native oracle. The final
completion barrier is awaited but is outside the measured event envelope.
Equal driver-reported clocks and a raw elapsed ratio of at most 1.15 are
both required. A candidate timeout or mismatched image, output or clock
is not an admission. The independent R pairs use a different board;
these G receipts do not by themselves qualify a convergence comparison.

| Algorithm | Route | G result directory | G service invocation |
| --- | --- | --- | --- |
| CC | `route-cc-v2` | `g-cc-board-v2` | `4d2e1d78c0b145859f228c968e04f77f` |
| Weighted SSSP | `route-sssp-v2` | `g-sssp-board-v2` | `d0f3d6da16f04df09f56215921611b6a` |

Result directories are under
`/data/chuxiao/checks/source-retention-repair-20261104/`. The entry point is
`python3 -m spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.active_min_candidate --help`.
Both launchers are waiting for route completion at this checkpoint;
neither has attempted to program the card. The exact archived reference
log replays to 18,413,633 ns, and both algorithm hosts resolve the recorded
public-control XRT library before any board request.

Both `v1` G queues were stopped while their exact routes were still waiting
for compiler memory, before either had attempted a board launch. Their
reports remain in `g-{cc,sssp}-board-v1/`. The `v2` launchers compare the
clock record to the expected clock-image identity (which includes byte
size), rather than directly to the path/SHA-only route pin. No route or R
screen was restarted and no measurement was repeated.

## Joint Admission For CC And Weighted SSSP

Before using an image in a resident comparison, replay both stage receipts
with `source_retention.active_min_admission`. The R receipt is the
`pair/results.json` inside the corresponding R queue directory. The tool
replays the A4 and K4 raw events and published state against the offline
Amazon oracle, and replays the AU update envelope and PMA check. It verifies
the exact candidate image and native host from both commands and confirms
the same driver clocks across the two candidate observations, even though
the stage pairs used different PCI devices. A status label or successful
link cannot replace either measured stage ratio.

For CC, from the simulator worktree:

```bash
root=/data/chuxiao/checks/source-retention-repair-20261104
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.active_min_admission \
  --algorithm cc \
  --route /data/chuxiao/builds/gr-directory-spans-20261103/route-cc-v2 \
  --host /data/chuxiao/checks/gr-active-min-candidate-20261104-v1/connected_components/sharded_k4_cc_native_host \
  --r-report "$root/cc-active-pair-v1/pair/results.json" \
  --r-inputs "$root/a4-active-amazon-v2/inputs" \
  --g-report "$root/g-cc-board-v2/results.json" \
  --g-reference "$root/g-reference-board-v1/results.json" \
  --output "$root/cc-stage-admission.json"
```

Use `--algorithm weighted_sssp`, `route-sssp-v2`, the pinned weighted
native host, `sssp-active-pair-v2/pair/results.json`, and
`g-sssp-board-v2/results.json` for weighted SSSP. A successful receipt is
explicitly `BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE`. A later comparison
must still record its own bitstream, host, actual board clocks and
old-state-to-updated-state correctness; this tool does not start that run.

### Resident SSSP and CC on the admitted image

`source_retention.active_min_resident` is the one-case board runner for the
production Spine resident host interface. It replays the two stage gates
itself and takes the G+R host and image only from that result. The October
single-pass matrix supplies the graph/batch, source, memory limit, and
compatible Spine host and image; its G+R artifacts and latencies are not
reused. The case plan and executed manifest must agree and both must pin
the graph and Spine artifacts. The runner requires a fresh output directory,
uses the per-board and legacy locks on board 1, and runs one sample per arm
with no timing warmups. It replays the G+R clock readback against the stage
screens and checks both runs for updated-state correctness and a continuous
resident wall through final readback, including inter-round host relaunch.

For example, after the weighted SSSP stage gates succeed (replace `OUT`
with a fresh absolute directory):

```bash
root=/data/chuxiao/checks/source-retention-repair-20261104
systemd-run --user --unit=gr-retention-sssp-resident-au \
  --property=MemoryMax=16G --property=MemoryHigh=14G \
  --property=MemorySwapMax=0 --property=OOMPolicy=kill \
  --property=KillMode=control-group --property=RuntimeMaxSec=8h \
  --working-directory="$PWD" /usr/bin/python3 -m \
  spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.active_min_resident \
  --algorithm weighted_sssp --dataset AU \
  --previous /data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/matrix \
  --route /data/chuxiao/builds/gr-directory-spans-20261103/route-sssp-v2 \
  --host /data/chuxiao/checks/gr-active-min-candidate-20261104-v1/weighted_sssp/sharded_k4_sssp_native_host \
  --r-report "$root/sssp-active-pair-v2/pair/results.json" \
  --r-inputs "$root/a4-active-amazon-v2/inputs" \
  --g-report "$root/g-sssp-board-v2/results.json" \
  --g-reference "$root/g-reference-board-v1/results.json" \
  --comparator /home/chuxiao/grasu-regraph-sim-aligned/scripts/compare_resident_fpga_logs.py \
  --wait-seconds 21600 --output "$OUT"
```

Use the declared per-case `memory_gib` (16, 24, or 32) and a `MemoryHigh`
at least 2 GiB below it. This runner does not substitute the newly found
CC repair image: that image uses a separate host and reports both
pre-upload and post-upload clocks for the batch. Its AU correctness and
timing-window screening is a separate experiment, not a replacement row
selected on the basis of timing. A failed or interrupted pair retains its
attempts and logs; it does not automatically retry.

To queue the same one-shot case before its screens finish, use
`source_retention.active_min_resident_follow` instead, with
`--r-unit` / `--r-invocation`, `--g-unit` / `--g-invocation`, and
`--stage-wait-seconds`. Both exact invocations must be active when queued.
Allow for the stage wait plus the resident wait in `RuntimeMaxSec`. While
waiting for stage gates, the follower holds no board or memory reservation.
It requires both terminal pass receipts and checks their hashes against
the resident runner's raw replay before any board access.

The AU SSSP follower on trifoliate uses unit
`gr-retention-sssp-resident-au-v2-20261104.service` and writes
`/data/chuxiao/checks/source-retention-repair-20261104/sssp-resident-au-v2/queue.json`.
Its R producer is `gr-retention-sssp-pair-v2-20261104.service` (invocation
`7c08c96c7dcc494bb5714fd590cd731a`); its G producer is
`gr-retention-g-sssp-v2-20261104.service` (invocation
`d0f3d6da16f04df09f56215921611b6a`). It uses the paths in the example and
will save the board receipt under `pair/results.json` only if it requests
the comparison. This is one preregistered screening case, not a Fig. 7 row
or a claim about the eight-graph matrix until the actual result is reviewed.

### Single-pass SSSP continuation

`source_retention.sssp_matrix` queues SU, WK, SO, PK, LJ, LJ08, and R19
in that order. It waits for the exact AU resident smoke and the high-activity
odd-frontier R screen. Both must finish successfully, and the runner replays
the same-image G and R receipts before dispatching any of the seven cases.
The AU gate is correctness and timing-window validity, independent of which
system wins. AU is not measured a second time.

Use the command above with the module changed to `source_retention.sssp_matrix`,
a fresh output directory, and these additional flags:

```bash
--au-unit gr-retention-sssp-resident-au-v2-20261104.service
--au-invocation 748522d410f44532ab625d1b2e6509a2
--au-output "$root/sssp-resident-au-v2"
--odd-unit gr-retention-sssp-odd-pair-20261104.service
--odd-invocation ed0e867a14f047e7baa9fec2b3b62ea9
--odd-output "$root/sssp-odd-pair-v1"
--odd-inputs "$root/a4-active-amazon-odd-v1/inputs"
--odd-fixture "$root/a4-active-amazon-odd-v1/manifest.json" 81e9430421d52acf665a507f808a7f467f745818f491aa7dc1fc605ae95e9add
--child-prefix gr-retention-sssp-matrix-20261104
```

Enqueue while both prerequisites are live. Give the coordinator a small
zero-swap cgroup and allow the stage wait plus seven bounded case windows
in its runtime limit. The coordinator itself does not acquire a board or
compiler reservation. It dispatches one bounded child at a time, with
16, 24, or 32 GiB per the frozen case. The matrix journal links the AU
receipt and per-case receipts, including failures; it never retries a case.
It does not certify CC or ResPR or substitute October latencies for new
measurements.
