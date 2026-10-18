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
contract checker. The pre-hook preserves and delegates to the installed
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
contract passed. It does not extend the original route/return admission
schema: a routed candidate needs a separately recorded physical profile,
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

The fresh v2 deployment uses fixed runner `4472627`, service
`spine-original-g-physical-port-20261018-v2.service`, invocation
`7704538d19e74c80bb50e204ae87f4c4`, and output
`original-g-physical-port-probe-v2` under the remote campaign root above.
At 2026-10-18 12:34 UTC it is `WAITING_FOR_COMPLETE_MEMORY_BUDGETS`:
about 435 GiB is available and 200 GiB of full budgets/reserves is required,
but unrelated unbounded Vivado simulation processes prevent admission.
The actual cgroup reports 40/36-GiB max/high, zero swap and
`memory.oom.group=1` (`OOMPolicy=kill` in the systemd service).
It has not executed BD creation, routed or programmed an FPGA.

Seven focused synthetic tests cover grouping, preserved vendor delegation,
delayed hook installation, duplicate/order/bank rejection, clock-object
resolution, proof corruption and stopping before tools on a bad parent.
They do not substitute for actual
Vivado, RTL simulation or FPGA measurements.

```bash
python3 -m unittest discover -s tests -p 'test_original_grasu_physical_port.py'
```

## Full-Link Continuation

`route.py` can wait for the exact v2 BD service/invocation above and then run a
fresh full link under profile `original_g_external_metadata_4to1_v1`. It does
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
  --bd /data/chuxiao/baseline_hardware_validation_20261017/original-g-physical-port-probe-v2 \
  --unit spine-original-g-physical-port-20261018-v2.service \
  --invocation 7704538d19e74c80bb50e204ae87f4c4 \
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
board measurements. The full `test_original_grasu*.py` group passes 103 tests.

```bash
python3 -m unittest discover -s tests -p 'test_original_grasu_physical*.py'
```
