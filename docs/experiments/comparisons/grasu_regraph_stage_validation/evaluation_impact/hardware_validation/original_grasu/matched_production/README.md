# Same-Input Production G Control

## Question And Boundary

Does the actual production G handle the original G's logical PMA layout and
update order correctly, and, after independent routed/board admission, how
does its resident update time compare? This is separate from an original
U250 publication-performance reproduction. A host-only pass answers the
correctness prerequisite, not the performance question.

The current input owner is the immutable v4
[original board-host preflight](../board_host/README.md), report SHA-256
`c5fcccaf865c8d50cc5b0f74f4ea2dda53359a125fc927ae217915287c9d1ef6`.
All eight cases are required: empty graph, empty batch, insertion only,
full deletion, mixed reservation, hot skew, same segment and threshold ring.
Inputs are not rebuilt from the final graph or filtered to passing cases.

## What Is Held Fixed

The production control preserves vertex IDs, per-source row bounds, binary
segment heads, every initial/final logical slot, reserved space, update order,
round-robin assignment to four search lanes and hot/cold routing. An independent
replay using the original model must pass before constructing production
buffers. Every original update must select the same logical segment in the
production lookup. A fault injected into a physical padding word must fail
the complete-state checker.

The original unweighted edge becomes a production edge with constant weight
one. This preserves destination ordering. Actual physical differences remain:
the original has 64-bit edges and its own four-buffer allocation; production
uses its real 32-bit weighted representation, shared 512-bit metadata lines,
23-channel lane-aware allocation, two 131072-segment hot caches, and allocated
cold buffers. They are disclosed, not claimed to be identical hardware. The
single G-only shard is not a ReGraph partition-capacity claim.

The device path reuses the production continuous-G XRT bindings, nine G CUs
and its completion barrier. It records packing, DMA, binding/launch/wait,
kernel-event busy/span, independent oracle and verification readback separately.
Do not compare its inclusive `g_ready_wall_ms` directly with original G's
resident window that excludes preparation and upload. A later paired report
must use explicitly matched windows and preserve setup as separate evidence.

## Ownership

`cpp/tests/evaluation_impact/common_g/matched_original/` separates the input
adapter/model, leased device execution and CLI. It reuses production physical
state/update helpers and device bindings; it does not introduce a second
numerical G implementation. The CLI rejects an unleased board before XRT
enumeration, and the shared XRT binding checks the expected PCIe BDF before
creating a context.

`spine_cycle_sim/experiments/evaluation_impact/common_g/matched_original/`
separates source freezing/compile commands, typed result analysis and bounded
host preflight. It pins the real XRT headers, compiler, imported Python
modules, dependency closure, runtime libraries and source/input bytes.
Release uses `-O3 -DNDEBUG`; model-only UBSan uses `-O1` with nonrecovering
undefined-behavior checks. Neither changes hardware geometry.

## Reproduce The No-Device Prerequisite

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.matched_original \
  --root /absolute/simulator-worktree \
  --integration /absolute/reviewed-production-integration \
  --original-preflight /absolute/original-g-board-host-preflight-v4 \
  --original-preflight-sha256 c5fcccaf865c8d50cc5b0f74f4ea2dda53359a125fc927ae217915287c9d1ef6 \
  --xrt /opt/xilinx/xrt \
  --output /absolute/fresh-matched-g-host-preflight
```

Every child has a 600-second limit, a 4-GiB process-tree memory limit and a
32-GiB available-memory reserve. Release and UBSan must both pass all eight
inputs, reject a malformed header, and the Release binary must reject board
access without its external lease. Raw stdout/stderr and failures remain in
the unique output directory. No FPGA is selected or programmed by this CLI.

The fresh attempt is under the local campaign root
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`, directory
`matched-g-original-host-preflight-v1`. Its terminal `results.json` reports
`MATCHED_G_HOST_PREFLIGHT_PASS_NOT_BOARD_OR_PERFORMANCE`, with SHA-256
`67bdac62a571202901363a612e7868b55d09e3d7d911cb30b5f8b53ddb44d58e`.
All 22 child steps pass: two compilations, loader inspection, sixteen model
rows, two malformed-header rejections and the unleased-device rejection.
The summed child elapsed time is 21.697 seconds; peak sampled process-tree
RSS is 351.027 MiB. The report pins 1743 source/input/tool/runtime records.
These samples are watchdog observations, not a cgroup peak or containment
claim. Board timing, original-G performance match, publication reproduction
and final-figure admission all remain false.

That v1 execution remains historical: its original-G prerequisite contains
three development-module pins that subsequently changed. The matched-G v1
board waiter rejected this mismatch before programming. A replacement must
run from an immutable snapshot and use a freshly reviewed original preflight.
`--original-preflight-sha256` selects that exact report in the host preflight;
both `--preflight-sha256` and `--original-preflight-sha256` are required for
new reports in the board and board-follow commands. Defaults retain the old
reviewed identities. No option disables schema, source-pin, oracle or timing
checks, and no report is accepted merely because its checksum is supplied.

Focused tests, including compiled production-header model tests:

```bash
env SPINE_G_INTEGRATION=/absolute/reviewed-production-integration \
  python3 -m unittest discover -s tests -p test_grasu_matched_original.py -v
```

The paired original-G board comparison is still blocked by the separately
preserved original source's U55C HMSS port-capacity failure. Do not substitute
a compact-port implementation and label it original G, or report this host
prerequisite as a measured performance match.

## Current Immutable Prerequisite

`matched-g-original-host-preflight-v2` passes all 22 child steps with no
FPGA programming. Its report SHA-256 is
`e35f1e1a252324f030fc52c7b3587f12cc503cc0e531b01c54257be7674f5c0b`.
Service `spine-matched-g-host-preflight-20261018-v2.service`, invocation
`7c30418583ab45c6b10344ba7054236f`, exits zero with a 363216896-byte cgroup
peak. Both compilation variants preserve all eight original inputs and pass
complete state checks. Admission independently rechecks all 2677 transitive
pins; supplying report digests does not waive those checks.

It uses the same immutable `f50a185` snapshot as original-G v4, not the
development checkout. The replacement board follower is
`spine-matched-g-production-board-20261018-v2.service`, invocation
`53dfab92c4684c7a86328227cde86a49`, output
`matched-g-production-board-follow-v2` under the local campaign root. It
explicitly pins both report digests and waits for SSSP production qualifier
`spine-g-production-remote-follow-20261018-v3.service`, invocation
`adf99e92398e4905a1909150d14fa131`. It retains 4/3-GiB max/high, no swap,
group OOM kill, CPU 120 and a 140000-second lifetime. Its deployment state
is `WAITING_FOR_EXACT_PRODUCTION_QUALIFIER`, with no board request or timing
result. The failed v1 follower and both historical preflights are unchanged.

## Independent Production Board Matrix

The `matched_original.board` package owns input admission, device execution
and raw-event analysis separately. It requires the exact host preflight above
and independently checks the returned production artifact's source, ABI,
topology, actual 150-MHz clock and strict setup/hold timing. It acquires the
shared exclusive board lease and checks the PCIe BDF before creating an XRT
context. All eight cases run three times; a failed case stops the matrix
without an automatic reset or retry. Complete logical state, physical cold
padding and both metadata copies must pass, not just a count or checksum.

The raw event records retain every queued/submit/start/end timestamp. The
analysis separately reconstructs producer-only and publication-barrier-inclusive
busy/span times, checks DMA completion before kernel enqueue, and records
packing, transfer, binding/enqueue/wait, oracle and verification readback.
Repeated summary fields are medians; they are not fitted timing predictions.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.matched_original.board \
  --preflight /absolute/matched-g-original-host-preflight-v2 \
  --preflight-sha256 e35f1e1a252324f030fc52c7b3587f12cc503cc0e531b01c54257be7674f5c0b \
  --original-preflight /absolute/original-g-board-host-preflight-v4 \
  --original-preflight-sha256 c5fcccaf865c8d50cc5b0f74f4ea2dda53359a125fc927ae217915287c9d1ef6 \
  --returned /absolute/strictly-qualified-returned-artifact \
  --parent /absolute/g-production-route-v1 \
  --original /absolute/frozen-parent.xclbin \
  --receipt-sha256 EXACT_RETURN_RECEIPT_SHA256 \
  --output /absolute/fresh-matched-g-board --device 0 --repeats 3 --execute
```

The launcher requires a finite 4-GiB cgroup, zero swap and OOM-group
containment, plus atomic full-budget admission with a 32-GiB reserve.
`matched_original.board.follow` can wait for one exact production qualifier
unit/invocation, recheck its successful board report and sealed return, then
invoke the same matrix. Failed timing, a changed prerequisite or incomplete
qualification is rejected before requesting a device. A queued continuation
is not a measured result. Even a production matrix pass alone does not
establish a paired original-G speed match or publication reproduction.

Focused guard and timestamp-replay tests:

```bash
python3 -m unittest discover -s tests -p test_matched_g_board.py -v
```
