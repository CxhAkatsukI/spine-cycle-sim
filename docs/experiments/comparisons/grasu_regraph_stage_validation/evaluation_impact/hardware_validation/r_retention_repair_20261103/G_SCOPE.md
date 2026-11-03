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
  each on the same leased U55C. Capture each loaded image UUID, actual
  clock, host binary and affinity. The frozen public-source probe ran
  four updates per invocation; do not rerun that binary as-is.
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

This screen is pending. A result using the pre-repair ResPR bitstream
would help diagnose G, but the final comparison needs the accepted routed
image: unchanged XOs do not guarantee unchanged routed clocks or timings.
