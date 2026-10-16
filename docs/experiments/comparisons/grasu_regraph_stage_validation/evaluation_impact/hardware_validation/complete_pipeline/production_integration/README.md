# Connected Production G Host Check

## Decision

The promoted production-source candidate passes eighteen connected host
transactions and a deliberate stale-metadata rejection:
`CONNECTED_G_HOST_FUNCTIONAL_PASS_NOT_RTL_OR_DEVICE_REFRESH`.
This supplements the earlier simulator-owned connected source tests; it does
not replace them or claim that integrated RTL, routing or FPGA timing passed.

The [evidence index](evidence/index.json) contains a 423,727-byte archive of
188 members, including both the failed first attempt and the passing retry,
their frozen sources/runners, compiler dependency lists, commands and raw logs.
SHA-256: `d7b23516ab744db09a1225f1c169c26e472205b90fabfecb075122237b4c1f6d`.
Installed vendor headers, compiler/runtime dependencies and compiled binaries
are hash-indexed, not redistributed. The production code and reproduction
entry points are at integration commit
[`6342a56`](https://github.com/CxhAkatsukI/grasu-regraph-integration/tree/6342a56/validation/grasu_complete/integration).
No simulator cycle model or fitted timing factor is used in this check.

## Tested Contract

- Four actual production search calls feed upstream dispatch, two full-capacity
  registered cache halves and two upstream cold-DDR calls. There is no direct
  cache shortcut or reduced capacity: each hot half has 131,072 segments.
- Each count in 0, 1, 63, 64, 65, 127, 128, 129 and 257 runs with both metadata
  generations. Contents change at the same row/binary pointer addresses;
  PMA allocations and state persist throughout all eighteen transactions.
- All six PMA buffers, including reserved cold prefixes, are compared in full
  against an independent sorted-segment oracle after every transaction.
  The updates cover insertion, deletion, repeated destinations and hot/cold
  routing. This is a synthetic functional fixture, not a real-graph benchmark.
- Twelve external FIFOs are finite: update queues have depth two and completion
  queues depth one. Delayed consumers force blocked writes for counts at least
  63. Four completions, payload/sidebands, update/END conservation and 1,356
  search-internal channels, including metadata-credit conservation, are checked.
- The negative run deliberately omits the generation-one metadata refresh.
  It must fail at exactly one update, generation one, with a complete-state
  mismatch. A timeout, crash or arbitrary nonzero exit is not an admitted
  negative result.

## Retained Attempts And Safety

`g-production-connected-functional-v1` completed eighteen C++ state checks,
but its analyzer rejected the upstream cold insertion width warnings. Its
report remains `FAILED_RETAINED`, with no admitted functional rows.
The retry admits exactly 417 pairs of the two known width messages, independently
counted from the declared insertion/deletion sequence; any unknown message or
different count is rejected. Kernel code and test vectors were not changed
to silence warnings. The full intermediate-state gate remains mandatory.

`g-production-connected-functional-v2` passes all eighteen rows and the exact
negative control. Compilation takes 6.41 s, positive execution 23.31 s and
negative execution 6.42 s. These are host verification costs, not FPGA latency.
The user service invocation is `eb4580e16cde4cedbf9e763ca98db3e2`.
All cgroup memory-event counters are zero; peak service memory is about 385 MiB.
Twenty-six related production validation/identity/RTL/admission tests also pass.

Containment is 1-GiB hard / 768-MiB high, zero swap, group OOM kill, CPUs
122--123 and bounded child/service lifetimes. Atomic admission counted both
active routes at their full 40-GiB caps plus the 24-GiB reserve and this 1-GiB
job: 105 GiB required, about 131.6 GiB available at admission. Consequently
this check ran concurrently; it did not wait for unrelated FPGA tools to exit.
Raw attempts remain under
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.

## Reproduction And Remaining Gates

From the production integration checkout, set `PYTHONPATH` to that checkout
and the pinned simulator checkout. Run inside the mandatory contained source
job described in its `validation/README.md`:

```bash
python3 -m validation.grasu_complete.integration.study \
  --output /data/fresh-connected-host-attempt \
  --fixture /path/to/simulator/cpp/tests/evaluation_impact/common_g/hls \
  --upstream /path/to/integration/repos/GraSU/GraSU/GraSU_kernels/src \
  --include /path/to/Vitis_HLS/2024.1/include

python3 -c 'from pathlib import Path; from validation.grasu_complete.integration.delivery import verify; verify(Path("/path/to/simulator/docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/production_integration/evidence"))'
```

Internal cache/cold streams remain unbounded in C simulation. Host sleeps and
finite queues test functional progress, not RTL scheduling or throughput. No
XRT calls, actual device-BO refresh, adapter/R handoff or board timers run here.
The separate diagnostic G route still uses older frozen exports, not this
production owner. Its completion cannot close this candidate's production
routing or board gates. Next are integrated RTL/backpressure, device metadata
lifecycle, same-version physical admission and measured resident-batch controls;
publication matching and the complete Spine comparison remain uncompleted.
