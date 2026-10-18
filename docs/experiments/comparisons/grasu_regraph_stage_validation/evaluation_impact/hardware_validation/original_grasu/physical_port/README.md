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
contains a thin `probe.py` entry point, the pre-link hook and the post-link
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

Six focused synthetic tests cover grouping, preserved vendor delegation,
delayed hook installation, duplicate/order/bank rejection, proof corruption
and stopping before tools on a bad parent. They do not substitute for actual
Vivado, RTL simulation or FPGA measurements.

```bash
python3 -m unittest discover -s tests -p 'test_original_grasu_physical_port.py'
```
