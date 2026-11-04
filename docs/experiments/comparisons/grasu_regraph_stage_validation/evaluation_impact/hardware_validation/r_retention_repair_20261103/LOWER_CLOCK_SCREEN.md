# Lower-Clock R Screen

This diagnostic compares both R arms at the same actual clock vector below
the nominal HBM target. It does not change the 450-MHz acceptance rule or
authorize a resident matrix. Each predeclared arm is measured once. The
logical input, one-superstep semantics, event boundary, output checks and
board must match before computing the 15% retention test.

## Clock-Control Check

The runtime `DRM_IOCTL_XOCL_RECLOCK` request on trifoliate's
`0000:c1:00.1` failed with `Timer expired`; the next clock read returned
all zeros and a bounded `xrt-smi examine` timed out. There was no timed
algorithm run, no further write was attempted on that board, and the
runtime-reclock helper is not included. The separately leased board at
`0000:82:00.1` reported normal nominal clocks before its own test.

The alternate control is an **offline packaging** change: set the
`SYSTEM/hbm_aclk` entry of the public image's `CLOCK_FREQ_TOPOLOGY` with
XRT `xclbinutil`, without relinking its design. The verifier checks that
every non-clock section, including the compute bitstream, memory map,
and CU connectivity, is byte-identical. The derived image has a new
UUID; the original is untouched. The candidate must use the vendor's
own packaged clock, not a locally modified candidate. The public package
does not establish the candidate's safe or actual operating frequency.

## Measured Pairs

Both arms used the same U55C (`0000:82:00.1`) and passed their output
checks. Each arm ran one resident superstep. The full clock vector was
read after programming and again after the timed host, which can reopen
the image. Programming, state initialization and output readback are
outside the reported first-device-start to last-device-end boundary.

| Control | Actual clock vector (MHz) | Public A4 | Integrated candidate | Slowdown | 15% gate |
| --- | --- | ---: | ---: | ---: | --- |
| Weighted SSSP, reciprocal AskUbuntu, 903,774 edges | 150/500/445/0 | 2.147288 ms | 2.510750 ms | 16.93% | Fail |
| ResPR, skewed sources, `csr_degree` | 150/500/445/0 | 0.510895 ms | 0.807462 ms | 58.05% | Fail |
| ResPR, skewed sources, source bursts and unregistered Apply | 150/500/430/0 | 0.521335 ms | 0.823654 ms | 57.99% | Fail |
| CC, reciprocal AskUbuntu, 903,774 edges | 150/500/430/0 | 2.201941 ms | 2.602202 ms | 18.18% | Fail |

The SSSP candidate is the first source-burst route. The measured event
span exceeds the 15% limit by 41.37 us. The initial pair recorded the
public arm, but the candidate host rejected its pre-existing output
directory before timing. The recovery replays the original public
arm and measures only the candidate in a fresh directory. Both arms'
outputs pass their respective offline reference checks. This is one
correctness-checked superstep, not convergence or a resident speedup.

The ResPR and CC candidates are the exact returned physical retries; the
ResPR and CC packaged HBM clocks are 449 and 434 MHz, respectively.
The table uses the common **observed** frequency, not the packaged
frequency or a rescaling of measured times. The CC A4 reference uses
the public four-Little design with the explicit minimum-label UDF
adaptation, not the upstream OR-based CC UDF. Its output and the
candidate output agree with the independent offline CSR oracle.

In the ResPR trace, shard 0 gather finishes 211.9 us after its adapter
and 81.2 us before the overall pipeline ends. The CC shard-0 mux spans
1.826 ms; the other two span 0.267 and 0.257 ms. These overlapping
intervals can include stalls and are not exclusive stage service times.
The skewed ResPR candidate has a shorter host enqueue-to-completion
window (0.898 vs 1.096 ms); this is not the predeclared device R gate.
None of these paired failures is due to a different clock vector, and
none admits a resident Spine comparison or validates earlier figure data.

### ResPR Source Bursts and Unregistered Apply

The replacement link packaged HBM at 432.3 MHz after missing nominal
setup timing (WNS -0.091 ns). Both images actually ran at 430 MHz HBM
on the same U55C, with the same 150-MHz compute clock, skewed fixture
(65,537 vertices and 8,193 edges), and degree binding. Each arm ran once
and passed its output oracle. The public A4 control checks every
published replica and its guard words; this is not reproduction of a
number from the ReGraph publication.

The integrated path misses the 15% cutoff by 224.12 us. Shard 0 gather
ends 229.49 us after its adapter, and its mux window overlaps 498.48 us
of the 823.65-us elapsed time. The intervals include concurrent work and
stalls. The two candidate images ran at different clock profiles, so this
is not an isolated measurement of the Apply change. The candidate's
resident host window is shorter than A4's (0.927 vs 1.179 ms), but that
window does not replace the predeclared device retention test.

The [one-run receipts, clocks and event logs](respr-apply-off-430-raw.tar.gz)
contain the candidate result with SHA-256
`b906ae64e0d9224ec6b8317f4a7099124ac096f0ba1036d9287c86707e8c45d4`.
The candidate's independent G and resident Spine gates are not admitted
by this measurement.

## Four-Way Gather Clear

An [opt-in HLS variant](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/ed7a5ed)
interleaves the existing gather URAM by row and clears four rows per
iteration. It does not omit the initial clear, change the output stream
or skip work for one of the timed arms. Native tests with the switch
both off and on pass the SSSP, CC and PageRank suites, including partial
bank groups, a growing prefix, a shrinking prefix and reuse.

Standalone ResPR gather builds used Vitis 2024.1, the U55C target and
the same 150-MHz kernel flags, with only the banked-clear define varied.

| Gather C-synthesis | Original | Four-way clear |
| --- | ---: | ---: |
| Full-clear loop iterations | 32,768 | 8,192 |
| Clear / scatter / publish initiation intervals | 1 / 3 / 1 | 1 / 3 / 1 |
| URAM / BRAM18 / DSP | 64 / 128 / 38 | 64 / 128 / 38 |
| Estimated LUT / FF | 37,263 / 17,308 | 43,130 / 19,643 |
| Estimated clock period | 4.658 ns | 4.658 ns |

The clear-loop iteration difference is 24,576 cycles, or about 164 us
at 150 MHz before pipeline startup effects. This is a local estimate for
one full clear, not an end-to-end saving: several workers can overlap,
and subsequent frames need not clear the full array. The measured ResPR
pair must save about 220 us to pass; CC must save about 70 us. This variant
is not a stand-alone ResPR fix, and its CC effect has not been measured.
The CC fixed-publication variant has passed C-synthesis and interface
checks; its physical link and one-shot measurement are queued. See the
[CC route handoff](REMOTE_LINKS.md#cc-four-bank-gather-clear) and the
[native and synthesis evidence](banked-gather-csynth.tar.gz).

### Weighted SSSP Component Check

The fixed-frame weighted gather was also built in both modes with Vitis
2024.1 for the U55C at 150 MHz. Both XOs match the pending SSSP route
input's kernel interface and compile definitions, apart from the new
banked-clear switch. The two component builds use the same source revision
(`1f63511`), not a relink of the existing SSSP image.

| Gather C-synthesis | Original | Four-way clear |
| --- | ---: | ---: |
| Full-clear loop iterations | 32,768 | 8,192 |
| Clear / scatter / publish initiation intervals | 1 / 1 / 1 | 1 / 1 / 1 |
| URAM / BRAM18 / DSP | 64 / 128 / 0 | 64 / 128 / 0 |
| Estimated LUT / FF | 36,536 / 11,804 | 42,544 / 14,474 |
| Estimated clock period | 5.860 ns | 5.860 ns |

The same 164-us reduction in local full-clear work is larger than the
41.37-us SSSP gap to the gate, but may overlap adapter work; the extra
LUTs and FFs also need placed-and-routed checks. This is a component
candidate, not an admitted route or measured speedup.
The [synthesis reports and logs](sssp-banked-gather-csynth.tar.gz) are
from `sssp-fixed-gather-clear-csynth-v2`, invocation
`65a5993a00994d9ea2805df18c827d0a` (peak 1.8 GiB). The banked XO
SHA-256 is
`d244e50c168def1bf0888822743c3166e09d7d28c1fbdcd2b9a8e0fed55c5faf`.

## Host Dispatch Control

On the same ResPR image, card, 445 MHz HBM profile and skewed-sources
fixture, a separately compiled probe binds all shard arguments before
the first enqueue. The original event envelope is unchanged; resident
wall time still includes argument binding. The existing A4 result was
reused and the changed candidate host ran once, passing its oracle.

| ResPR skewed-sources | Event span (ms) | Resident wall (ms) |
| --- | ---: | ---: |
| Public A4 reference | 0.510895 | 1.095811 |
| K4, original dispatch | 0.807462 | 0.897555 |
| Same K4, prebound dispatch | 0.791752 | 0.933416 |

The changed host was still 54.97% slower in the event envelope and
made the candidate's resident wall time worse. Do not adopt it or
qualify the image on this result. The code is opt-in via
`source_retention.build --prebound-dispatch`; run and replay via
`source_retention.dispatch_probe`. The local receipt is
`hbm-respr-tail-445-prebound-skew-v1/results.json`, SHA-256
`ef206853a514a49f3b8c718047e4e2a91b823a053bc4c128ece8150afeba51d8`
(service `gr-retention-respr-prebound-445-20261104-v1.service`,
invocation `c5ab58c82ec34538a232348f7e6ecce3`, peak 306.1 MiB).
The [raw replay evidence](respr-prebound-dispatch.tar.gz) preserves the
new timed log, the compiler manifest and the before/after clocks.

## ResPR Packed Validity Clear

The [opt-in gather change](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/1f63511)
clears packed validity in BRAM instead of clearing the full accumulator
array in URAM. Invalid entries read as zero, including when published.
Recent writes forward both the accumulated row and its shared validity
word so consecutive updates to different rows cannot erase each other's
bits. The publication format and row count remain unchanged.

Ten native checks passed, including bitmap-word collisions, repeated
destinations and an empty frame after a populated one. Vitis C synthesis
retained clear/scatter/publish II of 1/3/1 and estimated 4.658 ns; it
reported 64 URAM, 144 BRAM18, 38 DSP, 44,214 LUT and 20,957 FF for
the full gather kernel. The baseline used 128 BRAM18, 37,263 LUT and
17,308 FF. C synthesis does not certify placed-and-routed timing or RTL
behavior under stalls.

At maximum shard size the initial clear loop has 512 iterations instead
of 32,768, a local difference of 215 us at 150 MHz. That is smaller than
the 224 us gap to the gate in the 430-MHz skewed-sources pair. These are
different builds, and the local difference is not a predicted end-to-end
gain: clear can overlap other components, and the bitmap also clears on
warm frames. Do not infer that the change passes the hardware gate. See the
[synthesis evidence](lazy-gather-csynth.tar.gz) and the
[single-component route](REMOTE_LINKS.md#respr-packed-validity-gather).

### Replay the Remaining 430-MHz Gap

The public A4 sample sets a 599.535-us target at the 1.15 gate. The
source-burst/Apply-off candidate takes 823.654 us and finishes its last
adapter at 493.954 us relative to the first kernel start. With that adapter
endpoint unchanged, the rest of the envelope would have a budget of
105.581 us; the observed remainder is 329.700 us. The last gather, mux,
Apply and HBM commands finish at 723.441, 765.142, 795.973 and 823.654 us,
respectively. These are overlapping command timestamps, not standalone
stage service times. The paired board result cannot identify how much
of the remaining gap is clear, scatter, backpressure, or dispatch.

**Full-shard publication bandwidth.** This input has 65,537 vertices.
The [tail-publication host](../../../../../../../cpp/tests/publication_sources/source_retention/device.hpp)
rounds each shard to whole 16-vertex Apply beats and emits eight
two-vertex gather packets per beat. Shard 0 therefore emits 32,768
packets; shard 1 emits eight. In the framed HLS, gather consumes the
terminal update before starting the dense publication loop, and the
ordered mux sends at most one 64-bit packet per compute cycle. Even
without stalls, shard 0 publication takes about 218.45 us at 150 MHz.
With that interface unchanged, its terminal update must reach gather by
roughly 381.09 us after the first CU starts to meet the gate, even
allowing zero time for the remaining drain. That is a bandwidth budget,
not an inferred terminal timestamp; the adapter CU end at 493.954 us
does not measure terminal arrival.

Shard 1 gather is finished by 384.871 us, but its ordered mux command
does not start until 724.411 us and still spans 40.731 us for eight
packets. This window cannot be explained by packet count alone. It
includes waits in the streaming and command paths; there is no
ready/valid trace to divide them. The packed-validity retry retains the
same publication width. For its one-shot screen, first compare total
elapsed time against the gate and then check whether the full shard
ends earlier and whether the short mux and final write tail persist.
If the gate still fails, these are separate optimization targets:
earlier terminal delivery or wider full-shard publication, and tracing
the downstream waits. Do not subtract the ideal clear savings from the
board elapsed time as if all of those cycles were exposed.

Extract [the raw pair](respr-apply-off-430-raw.tar.gz) into `$raw` and run
from the simulator root. This replays both clock vectors and correctness
and timing records before calculating the candidate's windows:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.shard_windows \
    --derated-respr --raw-root "$raw" \
    --results "$raw/derated-respr-tail-bursts-apply-off-430-v1/results.json"
```

## Receipts

Paths below are relative to
`/data/chuxiao/checks/source-retention-repair-20261104` on trifoliate.

| Item | Receipt | Status |
| --- | --- | --- |
| Runtime-reclock check | `hbm-control-qualification-440-v2/results.json` | Failed, no algorithm run |
| SSSP same-clock AskUbuntu pair | `sssp-burst-au903k-445-recover-v4/results.json` | Correctness pass; performance gate fail |
| ResPR public 445-MHz package | `hbm-respr-a4-445-repackage-v1/package.json` | Ten non-clock sections byte-identical |
| ResPR public 445-MHz skewed-sources run | `hbm-respr-a4-445-skew-board-v1/results.json` | Passed, reference arm only |
| ResPR same-clock skewed pair | `hbm-respr-tail-445-skew-pair-v1/results.json` | Correctness pass; performance gate fail |
| CC public 430-MHz package | `hbm-cc-a4-430-repackage-v1/package.json` | Verified offline; used in the paired run |
| CC same-clock AskUbuntu pair | `hbm-cc-physical-430-au903k-pair-v2/results.json` | Correctness pass; performance gate fail |

The ResPR reference-only receipt SHA-256 is
`f97471f56f75dc7e1c1c3f1234203ab0d66d5df1ba1ba84d3bbd6173b8e45d00`.
The service was `gr-retention-hbm-respr-a4-445-20261104-v1.service`,
invocation `1a0f5b4f0f15481d894a24a042d2113c`; its peak was 186.5 MiB.

The [paired board evidence](lower-clock-pairs.tar.gz) includes the two
ResPR and CC pair receipts, timestamp and clock records, and raw timed-host
logs. The [SSSP stage admission record](SSSP_STAGE_ADMISSION.md#matched-445-mhz-hbm-diagnostic)
links the canonical [SSSP board evidence](sssp-au903k-burst-hbm445-screen.tar.gz)
for the recovered pair and original public arm.
The recovered receipt SHA-256 is
`eaf43e0e826240f9833f48a5e72758384835d5f2be84773a1e8928ad67b7a2e3`.
The ResPR pair receipt SHA-256 is
`d468d6860497354c661ffab679fbdf7dbe241a78d9f15ac3c94d2db13bbb64e2`
(service `gr-retention-hbm-respr-tail-445-20261104-v1.service`,
invocation `4b74f7fc939449ffa92ceaf1dd223be7`).
The CC pair receipt SHA-256 is
`017356b34620d2bb6d64b09b0614c68c2677ebab1ee00c8dae5bd6a5d73d9cfe`
(service `gr-retention-hbm-cc-physical-430-au903k-20261104-v2.service`,
invocation `3cb465f108c945c7ba4cf9b377af92dd`, peak 491.9 MiB).
CC setup v1 stopped in preflight because it compared a two-field fixture
pin to a three-field fingerprint. No image was programmed and no timed
arm ran in v1.

The offline entry point is `source_retention.repackage_hbm`, with native
verifier source `cpp/tests/publication_sources/source_retention/verify_clock_repackage.cpp`.
The opt-in board preparation helper `source_retention.matched_hbm` checks
the complete counter vector before and after a timed host. Neither entry
point changes the nominal qualification path or the frozen figures.
