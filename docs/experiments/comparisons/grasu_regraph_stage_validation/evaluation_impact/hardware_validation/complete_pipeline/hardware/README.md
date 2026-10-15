# Diagnostic Full G Link

## Scope

`g-complete-route-v1` is a fresh diagnostic hardware link, started concurrently
with the adapter-only `r-adapter-route-v3`. Its purpose is to test the
resource/timing feasibility of the reviewed search and full-cache exports in
the existing 150-MHz G+R topology. It is **not** yet a complete-G RTL,
production-baseline, board-performance or publication-match admission.

The inputs are eleven frozen XOs for 22 CUs. Only two XOs are replaced:

| Kernel | Evidence | XO SHA-256 |
| --- | --- | --- |
| `bin_search` (four CUs) | Eighteen wrapper RTL transactions and independently reviewed ABI | `d57b5827e2bbb09614e4bcd95fbe97adc79721db05e567820b6a9ac50eb39f1f` |
| `process_cache` (two CUs) | Six full-state wrapper RTL transactions, tokens and ABI | `caeb04635bc0eea9d36a04ebafb576d5b31ceb608b78f89acd206f218bfec9d8` |

The other nine XOs match the adapter-route basis, including the current
bank-streaming adapter. Both hot halves retain 131072 segments. The only
placement change is `lksg_stream_4:SLR0` to `SLR1`, justified by the
[storage screen](../resource_evidence/README.md). Memory mappings, stream
connections, kernel counts and clock are unchanged.

The composition and exported synthesizable search/cache cores are checked
against their frozen source. One exact host-only difference is recorded:
`HostReport` becomes `thread_local` in the concurrent C-simulation fixture.
`network.hpp` excludes that header under `__SYNTHESIS__`. No arbitrary host
or hardware drift is admitted. Separate control/testbench translation units
are not part of the shared hardware core.

## Concurrent Admission

Other FPGA tools need not exit when their budgets fit. Before vendor tools
start, the supervisor reserves the actual full compiler-cgroup memory budget
under a short atomic admission lock. It does not hold a global lock for the
lifetime of the route. Pending builds count even before a Vivado process is
visible; multiple processes in one cgroup count only once. A dead supervisor
does not free a lease while its compiler cgroup remains populated.

For this launch, one other route has a 40-GiB bound. Admission requires:

`40 GiB own + 40 GiB other route + 24 GiB system reserve + 8 GiB background = 112 GiB`

Eight consecutive two-second samples passed; the final sample recorded
135640289280 available bytes (about 126.3 GiB). Six environment preflight
checks passed and the link actually started. These are launch observations,
not a permanent guarantee of available memory or a completed route.

Each route has a 40-GiB hard / 36-GiB high cgroup limit, no swap and group OOM
kill. The owned process-tree watchdog samples RSS and global available memory
every two seconds, preserving a 24-GiB live reserve. It terminates only its own
workers on a guard violation. There are two synthesis/implementation jobs,
a six-hour link timeout, a 24-hour admission timeout and a 31-hour service
lifetime. Unbounded or unverifiable competing compilers fail admission.

## Monitor

Raw attempt:
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-complete-route-v1/`

Service: `spine-grasu-complete-route-20261016-v1.service`.
Invocation: `873fe3b111d3460b94457140f3df58be`.
Do not infer a pass from a running service's `Result=success`.

```bash
systemctl --user show spine-grasu-complete-route-20261016-v1.service \
  -p ActiveState -p SubState -p Result -p MemoryCurrent -p MemoryMax
cat /data/chuxiao/experiments/baseline_hardware_validation_20261015/g-complete-route-v1/execution.json
tail -n 30 /data/chuxiao/experiments/baseline_hardware_validation_20261015/g-complete-route-v1/route.stdout.txt
```

`manifest.json` pins every XO, configuration, validation report, launcher,
runner and explicit environment dependency. `execution.json` records actual
admission and status; `summary.json` and `route.resources.json` appear after
link termination. `cgroup_events.json` is saved when the supervisor exits.
A failed attempt stays failed. Never restart or overwrite this attempt.

## Verification

The focused regression suite passed all 187 tests, covering memory leases,
source identity, resource screens, export gates, route supervision and existing
component/cleanup contracts. It ran in a 2-GiB hard-limit, zero-swap cgroup;
sampled process-tree peak RSS was 93964 KiB. Raw logs and resource observations
are in `verification-concurrent-resource-v2/` beside the route attempts.
The separate repository-structure suite passed all 15 tests.

`verification-concurrent-resource-v1/` is retained as a failed test-launcher
attempt: its inherited 2-GiB virtual-address-space hard limit prevented three
cleanup tests from setting their child limits. The fresh v2 attempt used the
existing 64-GiB per-process address-space allowance while retaining the 2-GiB
physical-memory cgroup and tree watchdog. No assertions were relaxed. These
tests validate orchestration contracts, not integrated hardware correctness
or performance; neither live route has passed those gates yet.

## Reproduce And Next Gates

The thin entry point is:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware --help
```

It requires `--build`, `--basis`, `--search`, `--review`, `--cache`,
`--composition`, `--fit` and a fresh `--output`. Preparation is tool-free;
`--execute` requires a bounded service with the policy above. Preparation
revalidates the component exports, complete-state source composition and
platform storage ledger. The raw manifest records exact selected input paths.

The packages keep gates, source identity, input freezing, execution and memory
admission separate. Current route inputs are immutable while tools run.

A successful link still needs timing/utilization review, complete G
backpressure/state and real-host validation, then physical PMA handoff,
continuous batches and board timing. G, adapter/R and host windows must be
measured separately before publication/source controls and new Spine speedups
are accepted. The existing adapter-only route cannot stand in for this route.
