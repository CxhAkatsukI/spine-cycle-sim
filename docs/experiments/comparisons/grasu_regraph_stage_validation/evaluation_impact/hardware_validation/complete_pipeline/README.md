# Complete G Source Composition

## Decision

The latest `g-complete-source-v6` passes twelve declared rows:
`COMPLETE_G_SOURCE_COMPOSITION_PASS_NOT_INTEGRATED_RTL`.
This closes a source-level composition check, not complete G production,
integrated RTL, routed timing, FPGA performance or publication reproduction.
The [evidence index](evidence/index.json) retains raw failed attempts as well
as the passing source, commands, dependencies, resource logs and output.
The [shared-core index](shared_core_evidence/index.json) owns the newer v6
identity. The [diagnostic hardware guide](hardware/README.md) covers the
resource screen and memory-admitted concurrent link; a running link is not a
completed integration or performance result.

## What Was Checked

Four finite-FIFO search CUs use the production-shaped eleven-argument wrapper
with aliased metadata BOs and distinct per-thread host reports. Their outputs
feed the production dispatch, two full-capacity hot-cache halves and the
production cold-DDR functions. Each hot half retains 131,072 segments; no
capacity reduction or direct-memory cache shortcut is enabled. Cold segments
retain their full indices, including the reserved hot prefix.

Each original/registered-cache arm runs two metadata generations. The row
table and binary-search metadata change at the same pointer addresses between
generations. Three batches (0, 257 and 129 updates) share resident PMA state
within each generation. The fixture exercises all four output ports, repeated
segments, insertions/deletions, end tokens, lane stalls and packet sidebands.
All four complete PMA buffers and reserved-prefix canaries are compared with
an independent state oracle after every batch.

The actual bank-streaming adapter directly reads these resulting buffers;
there is no replacement compact edge array. Every handoff checks the full
physical packet count and logical weighted edge set. Expected live edge
counts after the batches are 40, 43 and 46. There are 1,544 physical edits
across both arms and generations, and twelve adapter handoffs.

This is a synthetic reserved-layout stress fixture, not a real-trace or host
PMA-reservation validation. External search/dispatch/cache/DDR stream queues
are bounded in the host harness. Internal cache/DDR `hls::stream` queues are
unbounded in C simulation, so this result does **not** establish integrated
RTL progress, backpressure behavior, a cycle count or resource fit. ReGraph
computation and host-inclusive timing are not part of this check.

## Retained Attempts

| Attempt | Decision | Reason |
| --- | --- | --- |
| v1 | `FAILED_RETAINED` | Same-basename runner copies collided during source freezing; no successful execution |
| v2 | Preparation error | Incorrect upstream directory; partial source and systemd journal retained, no compiler/HLS launch |
| v3 | `FAILED_RETAINED` | All twelve functional rows ran, but the analyzer rejected vendor width diagnostics |
| v4 | `FAILED_RETAINED` | All twelve functional rows ran; concurrent identical diagnostics joined on one line and failed the line-based checker |
| v5 | Source composition pass | Exact diagnostic counts and all complete-state/edge checks pass |

The original cache and production DDR perform a 512-bit `|=` with a 32-bit
insertion. Vendor C simulation emits two width-warning messages per such
insertion. The v5 analyzer requires exactly 544 occurrences of **each** known
message and no other stderr content. It does not hide warnings or admit an
unknown diagnostic. Complete intermediate-state checks are mandatory.
Earlier reports and frozen runners were not rewritten as passes.
The portable archives contain v3--v5. v1 has colliding source identities, so
the packager deliberately rejects it as a reproducible frozen-source archive;
its original failed report and partial tree remain at the raw campaign path.

After extracting the registered cache core into `cache_pipeline.hpp`, the
fresh `g-complete-source-v6` reruns the same twelve rows and passes unchanged
complete-state and edge-set checks. Both the isolated probe and production
cache wrapper now call this shared core. The separate
[shared-core evidence index](shared_core_evidence/index.json) pins this new
source identity; the original v3--v5 archives are unchanged. v6 compilation
took 6.42 s with about 514 MiB peak process RSS, and verification took 26.76 s
with about 114 MiB peak process RSS. These are host verification costs, not
accelerator performance.

The v2 journal belongs to systemd invocation
`134a656971814b3298e278fc83b656bf`; its partial directory is under the campaign
root below. It has no `results.json` and is not represented as an executed
test in the portable result archives.

## Reproduction And Safety

From the repository root, verify the portable capsule:

```bash
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/evidence"))'
```

The entry point is
`python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.study`.
Use a fresh `--output`, pristine GraSU kernel sources as `--upstream`, the
production G+R root as `--integration`, and vendor `--hls-include`. It freezes
inputs, pins G++ and dependencies, and uses C++20/O1 with assertions. Tool
scopes have 4-GiB hard/3-GiB high limits, no swap, CPUs 124--125, a 120-GiB
available-memory reserve and 300/900-second compile/run timeouts.
The supervisor must also have its own bounded lifetime and memory scope.
Other FPGA tools need not finish when their bounded budgets and reserves fit.

Raw attempts:
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-complete-source-v1`
through `g-complete-source-v5`. v5 compiled in 6.47 s with about 514 MiB peak
RSS and executed in 27.51 s with about 114 MiB peak RSS. These are **host
verification costs**, not accelerator latency or throughput measurements.
The v6 raw attempt is a sibling at `g-complete-source-v6`.

Production cache-wrapper export/ABI verification has independently passed.
The [storage evidence](resource_evidence/README.md) identifies an SLR-local
URAM conflict and a one-CU relocation that passes the hard-pblock storage
screen. It does not establish shell-free logic capacity or routed timing.
Next gates are complete G RTL/backpressure and resource/timing closure,
production integration, and board state/timing checks.
The [production cache-wrapper guide](../../cache_probe/README.md#production-wrapper-gate)
owns its independent RTL/export attempt and memory-admitted launch policy.
See the [campaign guide](../README.md) for the independent R and Spine gates.
