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
