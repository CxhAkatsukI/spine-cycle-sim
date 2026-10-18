# External Metadata Fan-In Diagnostic

## Why This Exists

The source-preserving original-G U55C attempt compiled all four kernel types,
then failed at block-design creation: its 46 AXI masters exceed HMSS's 33
ingress connections, including the host. This was neither an OOM nor a
measured slowdown. The retained failed attempt is not edited or resumed.

This separate physical-port control keeps the author's five source files,
four compiled XOs, nine compute units, URAM geometry and all 46 kernel master
interfaces. Each search CU's four binary metadata interfaces share one
external 4:1 SmartConnect; its four row interfaces share another. All grouped
interfaces already target the same bank. Eight groups reduce kernel HMSS
ingress from 46 to 22; the host uses one more. Edge, cache and DDR interfaces
remain direct. This is explicitly a U55C physical adaptation, not a
reproduction of the paper's U250/200-MHz experiment.

Arbitration can change performance. Neither that cost nor timing/resource
feasibility is assumed away. The production-G implementation and its
independent board matrix are not changed by this diagnostic.

## Ownership And Limits

`spine_cycle_sim/experiments/upstream_controls/grasu/hardware/physical_port/`
contains the bounded executor `probe.py`, admission checks in `route_inputs.py`,
an exact-service continuation in `route.py`, the pre-link hook and the post-link
contract checker. `delivery.py` owns the distinct return receipt, `replay.py`
rechecks its compilation/BD/link chain offline, and `admission.py` owns final
source/ABI/topology/clock/timing admission. The thin `follow.py` reuses the
original-G transport/wait/board driver with this explicit physical profile.
The pre-hook preserves and delegates to the installed
vendor mapper; it does not edit vendor files. The first lane establishes
the original bank, address range, offset, clock and reset. Later lanes use
the same bank/address geometry through that group's SmartConnect. Unexpected
call order, duplicate mappings, missing masters or changed banks fail closed.

The probe accepts only the retained HMSS-capacity failure and the byte-pinned
canonical XO/HLS identities from that attempt. It uses a fresh output,
explicit frozen tool environment, a finite 40-GiB cgroup, atomic full-budget
admission, 32-GiB reserve and a one-hour child timeout. It stops after
`vpl.update_bd`, before synthesis, placement, routing or bitstream generation.
Raw tool logs and failures remain available. No FPGA is programmed.

Run on the high-memory host in a bounded service:

```bash
python3 -m spine_cycle_sim.experiments.upstream_controls.grasu.hardware.physical_port.probe \
  --packet /data/chuxiao/baseline_hardware_validation_20261017/original-g-source-packet-v1 \
  --attempt /data/chuxiao/baseline_hardware_validation_20261017/original-g-source-route-v2 \
  --output /data/chuxiao/baseline_hardware_validation_20261017/fresh-physical-port-probe \
  --environment-root /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /absolute/reviewed-u55c-platform/platform.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1
```

`PHYSICAL_PORT_BD_PASS_NOT_ROUTE_TIMING_OR_BOARD_ADMISSION` means only that
Vivado completed the declared BD steps and the eight-group/46-master/address
contract passed. It does not extend the direct-46-port return admission
schema: a routed candidate uses a separately recorded physical profile,
strict timing, functional checks and a repeated matched-input board matrix.
It cannot be used to claim paper-performance matching or finalized figures.

The first deployed probe, `original-g-physical-port-probe-v1`, used service
`spine-original-g-physical-port-20261018-v1.service`, invocation
`b25eed2ab64c48d182ec5a19a4059943`, runner `bb5b341`. It left its memory queue
and ran Vivado, then failed at `create_bd`: the clock helper returns a name,
whereas `get_property` requires a resolved BD pin object. Peak cgroup memory
was about 3 GiB, with zero OOM events. This failure remains untouched. The
fix explicitly resolves the clock with `get_bd_pins`; no author source,
compiled XO, memory mapping, timing constraint or vendor file is changed.

The retained v2 deployment uses fixed runner `4472627`, service
`spine-original-g-physical-port-20261018-v2.service`, invocation
`7704538d19e74c80bb50e204ae87f4c4`, and output
`original-g-physical-port-probe-v2` under the remote campaign root above.
At the 2026-10-18 12:34 UTC checkpoint it was `WAITING_FOR_COMPLETE_MEMORY_BUDGETS`:
about 435 GiB is available and 200 GiB of full budgets/reserves is required,
but unrelated unbounded Vivado simulation processes prevent admission.
The actual cgroup reports 40/36-GiB max/high, zero swap and
`memory.oom.group=1` (`OOMPolicy=kill` in the systemd service).
After those unrelated processes exited, v2 entered BD creation and failed at
`connect_bd_intf_net`: the API requires two interface endpoints even when an
existing net is named. Its approximately 3-GiB peak and zero OOM events rule
out a memory-admission failure. The hook now explicitly resolves both the
SmartConnect master and the retained HMSS slave and connects them on that
same net. The focused Tcl regression requires both endpoints. This changes
neither author XOs nor bank/address/clock assignments. The v2 failure and its
dependent failed full-link/return attempts remain retained; a new probe and
new exact-invocation continuations are required.

Seven focused synthetic tests cover grouping, preserved vendor delegation,
delayed hook installation, duplicate/order/bank rejection, clock-object
resolution, proof corruption and stopping before tools on a bad parent.
They do not substitute for actual
Vivado, RTL simulation or FPGA measurements.

```bash
python3 -m unittest discover -s tests -p 'test_original_grasu_physical_port.py'
```

### Retained Two-Endpoint Retry

The two-endpoint correction is frozen in simulator `e5c11c1`, archive
`original-g-port-runner-e5c11c1.tar.gz`, SHA-256
`92dc51dbbe8480d9b670bd8fbcc1e6f415ba9afffa6f7505fe5b1b3f588ad995`.
Both hosts extract a read-only `original-g-port-runner-e5c11c1` directory
under their respective campaign roots. The following attempts are fresh;
the failed v1/v2 BD, full-link v1 and return v1 remain unchanged.

| Stage | Output | Service / exact invocation |
| --- | --- | --- |
| BD diagnostic | Remote `original-g-physical-port-probe-v3` | `spine-original-g-physical-port-20261018-v3.service` / `50405867b12d4cf690c161c561d781d0` |
| Full link, only after that BD passes | Remote `original-g-external-port-route-v2` | `spine-original-g-external-port-route-20261018-v2.service` / `8145f096118a4593a77ccee632f4f0ab` |
| Strict return, then guarded board matrix | Local `original-g-external-port-return-follow-v2` | `spine-original-g-external-port-return-20261018-v2.service` / `420d217e8f2245bdb4fd70effe1581be` |

At deployment the BD diagnostic is waiting for complete peer budgets: roughly
412 GiB is available versus 240 GiB required, but a new unrelated, unbounded
`dac_speedrun` Vivado prevents compiler admission. Existing bounded builds
continue. This is not a failed BD or successful route. The full-link waiter
names only v3; the local return names only full-link v2. Both compiler services
have 40/36-GiB max/high, zero swap and group OOM kill. The local follower has
4/3-GiB max/high, zero swap, CPU 120 and a 259200-second wait; its 280000-second
outer deadline also covers return and board work.

Unlike return v1, this follower requests board execution **only after** strict
source/ABI/physical-profile/clock/timing admission. It pins the immutable
original-G v4 host preflight (`c5fcccaf865c8d50cc5b0f74f4ea2dda53359a125fc927ae217915287c9d1ef6`)
and uses the existing exclusive device lease. Deployment is not a measured
G comparison; the independent matched-production G matrix remains necessary.
The correction passed all 116 original-G regressions and 15 organization
checks, plus documentation/catalog and whitespace checks. These are synthetic
test results, not hardware admission.

### Common-Attribute Discovery Correction

The v3 probe subsequently failed during platform validation, with zero OOM
events and approximately 3.35 GiB peak memory. The retained BD has the intended
eight SmartConnects, each with four original master inputs and one output to
its original HMSS ingress. However, Vivado 2024.1's HMSS
`set_slr_info_env` callback follows the interconnect to the original addressing
masters and requires exactly one. Four masters are therefore rejected even
though the physical fan-in was created. Its `set_clkrst_info_env` callback
has the same single-master assumption. Full-link v2 and return v2 consequently
fail before synthesis or board execution. These outputs remain unchanged.

The new explicit profile is
`original_g_external_metadata_4to1_common_attributes_v2`; it must not admit
old v1 proofs. `discovery.tcl` adapts only the addressing-master lookup in
those two callbacks, in memory, after verifying their expected signatures
and lookup expression. It does not edit installed vendor files or suppress
vendor diagnostics. All other callback logic remains in place. Unchanged
single-master ports still use the original discovery result, including its
original failure behavior for an unexpected fan-in.

Before selecting a representative master for either callback, the adapter
requires all four actual addressing masters to equal the declared lane set,
checks every SmartConnect input/output connection, and independently checks
common clock/reset nets, SLR assignments and address range/offset. It rejects
additional per-master random-access or port-location constraints until an
explicit fan-in contract exists. Exactly two unchanged adapted callbacks
must be present at post-link validation; their original-body CRCs are logged.
All three hook files are pinned through BD, full link and offline return
replay. A changed or unsupported callback fails the probe; no unchecked
fallback is used. This remains a platform-adapted original-G control,
not a publication reproduction or an assertion of zero arbitration cost.

Four additional synthetic tests cover these common-attribute and callback
invariants, including eight independently corrupted topology/attribute cases,
delayed namespaced loading, unmodified direct-port diagnostics and unsupported
or replaced callback rejection. Actual Vivado BD completion, full routing,
strict clock/timing admission and the matched board matrix are still required.

```bash
python3 -m unittest discover -s tests -p 'test_original_grasu_hmss_discovery.py'
```

### Retained Common-Attribute Retry

The common-attribute correction is frozen in simulator `3005046`. Both hosts
use the read-only `original-g-port-runner-3005046` snapshot. Its archive
`original-g-port-runner-3005046.tar.gz` has SHA-256
`835f493653df4a8de52961b06623ffd941dc31414a5efc30b1033eb4eccc8fc0`.
Remote outputs are under
`/data/chuxiao/baseline_hardware_validation_20261017`; local outputs are under
`/data/chuxiao/experiments/baseline_hardware_validation_20261015`.

| Stage | Output | Service / exact invocation |
| --- | --- | --- |
| BD diagnostic | Remote `original-g-physical-port-probe-v4` | `spine-original-g-physical-port-20261018-v4.service` / `8bcc9369ad3947f1957896fc10e91632` |
| Full link, only after that BD passes | Remote `original-g-external-port-route-v3` | `spine-original-g-external-port-route-20261018-v3.service` / `7995d359b33e4dd6b3cb0e37062fcb41` |
| Strict return, then guarded board matrix | Local `original-g-external-port-return-follow-v3` | `spine-original-g-external-port-return-20261018-v3.service` / `108651da70a246db900ec7328eb5bd4e` |

BD v4 left its memory queue and failed at platform validation at 14:31 UTC,
with zero memory-limit/OOM events. Vivado had already loaded its discovery
callbacks before the pre-link hook, so the hook's future-`source` trace never
adapted them. The stock single-master check rejected the four-member fan-in.
Full-link v3 and return v3 consequently fail before compilation or programming.
These outputs remain retained; no routed or board-admitted artifact exists.

The loading-order correction searches already-loaded Tcl namespaces at hook
entry, then keeps the existing trace for later loads. It changes neither the
two-callback adaptation contract nor any author XO, clock or bank. Two added
regressions cover preloaded global/nested callbacks and early rejection of an
unsupported preloaded callback; all 122 original-G tests must pass. A fresh
BD probe is required before another full link. Synthetic tests are not proof
that the actual Vivado callback installation or BD validation succeeds.

The loading-order retry is frozen in simulator `ad8f81e`, read-only runner
`original-g-port-runner-ad8f81e` on both hosts. The corresponding archive has
SHA-256 `7f9061d0de9e27cf0a664b75ccf671011780497ee6a0c90c0d27994232bb5549`.
The current chain is separate from all retained failures above:

| Stage | Output | Service / exact invocation |
| --- | --- | --- |
| BD diagnostic | Remote `original-g-physical-port-probe-v5` | `spine-original-g-physical-port-20261018-v5.service` / `bef43ffcea30412897463ea00490ae35` |
| Full link, only after that BD passes | Remote `original-g-external-port-route-v4` | `spine-original-g-external-port-route-20261018-v4.service` / `6ff1d25db70749f486ef91ae1c570966` |
| Strict return, then guarded board matrix | Local `original-g-external-port-return-follow-v4` | `spine-original-g-external-port-return-20261018-v4.service` / `9098654d0d7c4ec7b2c185e4b0cbeab1` |

At the 14:50 UTC checkpoint, BD v5 is waiting for complete peer memory
budgets: available memory exceeds its full budget/reserve calculation, but
unrelated unbounded compiler processes prevent admission. Existing admitted
bounded builds continue. The full-link and local-return stages wait for the
exact prerequisites above; neither is a tool pass or a measured board result.

Both compiler services retain 40/36-GiB max/high, zero swap and group OOM
kill. The local follower retains 4/3-GiB max/high, zero swap and a
259200-second child wait within its 280000-second outer deadline. It requests
device 0 only after strict source/ABI/physical-profile/clock/timing admission,
using the exclusive device lease. Its original-G v4 preflight remains pinned
to `c5fcccaf865c8d50cc5b0f74f4ea2dda53359a125fc927ae217915287c9d1ef6`.
All failed earlier attempts remain unchanged. The correction passes 122
original-G regressions and 15 organization checks, plus documentation,
catalog and whitespace checks; these are not actual Vivado or board results.

## Full-Link Continuation

`route.py` waits for one exact BD service/invocation and then runs a
fresh full link under the current common-attribute v2 profile. It does
not resume or overwrite the BD output. `route_inputs.py` independently checks
the terminal service, preserved compiled inputs, original 150-MHz command,
raw resource record, finite containment, zero OOM events, unchanged hooks
and the eight-group wiring proof. A replaced invocation, missing proof,
changed input or failed parent stops before a compiler starts.

The continuation reuses all four author XOs, retains every kernel interface,
copies the exact tested hooks, reruns all six environment probes, and removes
only the BD stopping point from the link command. It requires 160 GiB free
disk, the same atomic full-budget memory admission and 40/36-GiB max/high,
zero swap and group OOM kill. The BD wait is bounded at 24 hours and the
compiler child at 12 hours; the enclosing service must allow both waits and
the memory-admission wait. No board is programmed by this command.

```bash
python3 -m spine_cycle_sim.experiments.upstream_controls.grasu.hardware.physical_port.route \
  --packet /data/chuxiao/baseline_hardware_validation_20261017/original-g-source-packet-v1 \
  --attempt /data/chuxiao/baseline_hardware_validation_20261017/original-g-source-route-v2 \
  --bd /data/chuxiao/baseline_hardware_validation_20261017/original-g-physical-port-probe-v4 \
  --unit spine-original-g-physical-port-20261018-v4.service \
  --invocation 8bcc9369ad3947f1957896fc10e91632 \
  --output /data/chuxiao/baseline_hardware_validation_20261017/fresh-external-port-route \
  --environment-root /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /absolute/reviewed-u55c-platform/platform.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1
```

`EXTERNAL_PORT_LINK_PASS_AWAITING_CLOCK_TIMING_AND_BOARD` is **not** hardware
admission. A separate return/schema must preserve this changed physical
profile and verify actual 150/500/450-MHz clocks, final routed timing,
source/ABI/topology, and matched board correctness before accepting a timing
comparison. The old direct-46-port schema must not be reused to conceal the
external arbitration. Published-performance matching and final-figure
admission remain false even if this link succeeds.

Ten additional synthetic continuation tests cover exact terminal producer
identity, timeout without compilation, immutable hooks/platform/proof,
raw execution and memory policy, complete 150-MHz XO commands, preflight,
child failure preservation and the distinction between link and board
claims. Together with the seven BD tests these are 17 tests, not tool or
board measurements. These tests do not admit a returned binary.

```bash
python3 -m unittest discover -s tests -p 'test_original_grasu_physical*.py'
```

The retained first full-link continuation was deployed as
`spine-original-g-external-port-route-20261018-v1.service`, invocation
`0596cbd29fcf448ca4aa7b1f3c38f90f`, output
`original-g-external-port-route-v1`. Its frozen runner is `3c2b869`, archive
`original-g-external-port-route-runner-3c2b869.tar.gz`, SHA-256
`ad2eb7e0ca8e9d336673b3ef7c96f7954eada607bc5d0cfda3b02d0f04b080e7`,
all under the remote campaign root. Its deployment cgroup confirmed
40/36-GiB max/high, zero swap and `memory.oom.group=1`. Its 70-hour outer
deadline covers the separately bounded BD wait, memory-admission wait and
compiler child. The first saved state is `WAITING_FOR_EXACT_EXTERNAL_PORT_BD`
with no errors. Its exact v2 BD producer subsequently failed on the missing
interface endpoint, so full-link v1 and its return failed before compilation
or FPGA programming. The current retry table above replaces these wait states,
not the retained failed outputs. No deployment promises successful routing,
clock closure or board admission.

## Return And Admission

The separate `original-grasu-external-port-return-v1` receipt carries the exact
terminal producer invocation, unchanged author sources and compiled XOs/HLS,
the retained failed direct link, the tested BD proof/hooks, complete full-link
preflight/raw resource records, the candidate and final routed timing report.
Its fixed member set is digest-checked against the receipt SHA obtained over
SSH. Offline replay rejects substituted origins, duplicate/extra members,
changed hooks, failed raw steps, unbounded memory, OOM or a different physical
profile. Source code is unchanged; physical interconnect is explicitly changed.

Local admission independently extracts candidate metadata and requires all
46 logical AXI bindings, nine compute units, eight streams, actual
150/500/450-MHz clocks, and passing final setup/hold/pulse-width timing. Merely
finishing v++ is insufficient. The resulting status is
`ORIGINAL_G_EXTERNAL_PORT_ABI_CLOCK_TIMING_PASS_AWAITING_BOARD`, not a measured
performance or publication match. The shared board driver preserves this
profile in its results and cannot label it as the direct-46-port control.

For return/admission without programming a card:

```bash
python3 -m spine_cycle_sim.experiments.upstream_controls.grasu.hardware.physical_port.follow \
  --target chuxiao@10.129.161.241 --port 23333 \
  --runner /absolute/frozen-return-runner \
  --packet /data/chuxiao/baseline_hardware_validation_20261017/original-g-source-packet-v1 \
  --attempt /data/chuxiao/baseline_hardware_validation_20261017/original-g-external-port-route-v1 \
  --returned /absolute/fresh-remote-return \
  --unit spine-original-g-external-port-route-20261018-v1.service \
  --invocation 0596cbd29fcf448ca4aa7b1f3c38f90f \
  --output /absolute/fresh-local-follow --maximum-wait 259200
```

Run the local follower in a finite 4/3-GiB max/high service, with zero swap,
group OOM kill and an enclosing deadline longer than the declared wait.
Board execution additionally requires an independently reviewed, immutable
Release/UBSan host preflight and both `--execute --board-preflight ...`.
Do not reuse a preflight whose pins refer to files changed since its capture.
The follower without these flags never asks for a device.

Thirteen synthetic return/admission tests cover relocation, trusted digests,
independent raw replay, service replacement, false profiles, source and memory
closure, downclocking, negative routed slack and shared-driver selection. They
use no real SSH, vendor tool or FPGA. The complete original-G group now has
116 tests; actual routing, board correctness and matched performance are
separate pending evidence.

```bash
python3 -m unittest discover -s tests -p 'test_original_grasu_external_return.py'
```

The return-only follower is deployed locally as
`spine-original-g-external-port-return-20261018-v1.service`, invocation
`9fac2bbfcc954d0b916a32903f8939c1`, output
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/original-g-external-port-return-follow-v1`.
Its local and remote runner snapshots are `60d8073`, archive
`original-g-external-port-return-runner-60d8073.tar.gz`, SHA-256
`bd5aaf426ad7fe29c8b83dc8ba04a684550741cbded87d5e96b88abedf8c7434`.
It waits for the exact full-link invocation above, under a 4/3-GiB max/high
cgroup with zero swap, group OOM kill and a 259200-second wait. It does not
have either board-execution flag: return/admission cannot program a card.
At the 2026-10-18 13:13 UTC checkpoint the remote BD prerequisite is still
queued and this follower is waiting, not a returned or admitted result.
For a fresh board-capable follower, pass the separately reviewed immutable
host report using `--board-preflight-sha256` as well as its path. Reusing a
development-directory preflight is forbidden even if it once passed.
