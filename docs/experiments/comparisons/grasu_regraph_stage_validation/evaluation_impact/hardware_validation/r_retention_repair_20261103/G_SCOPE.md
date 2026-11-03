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
The candidate's board result remains pending. Unchanged G XOs do not
guarantee unchanged routed clocks or timings.

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
