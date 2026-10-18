# Pairwise Source Services

This checkpoint adds an explicit, default-off topology for the later sharded
K4 HLS wrapper: workers 0/2 share one source reader on HBM23, and workers 1/3
share another on HBM24. Source-state writeback shares those two physical
masters. This is a correctness and conservation checkpoint, **not** FPGA
timing calibration, an original-ReGraph performance match, or final figure
admission. It does not change the paper or frozen figure package.

## Review Order

1. `cpp/include/spine_sim/routed_regraph.hpp`: select
   `RoutedSourceTopology::kTwoPairwise` explicitly. The default remains
   `kFourDedicated`, matching the earlier measured weighted-SSSP wrapper XO.
2. `cpp/src/routed_regraph/source_topology.cpp`: physical-master selection,
   source-service ownership, and per-worker invocation counts.
3. `cpp/src/routed_regraph/composition.cpp` and `rounds.cpp`: connect the
   unchanged frontend chains and start each shared service exactly once.
4. `cpp/tests/routed_regraph/system_tests.cpp`: independent SSSP oracle,
   padded source replicas, complete drain, and transaction conservation.
5. `spine_cycle_sim/experiments/sharded_k4_stages/system_report.py`: strict
   matrix validation, separate from the frozen 13-row report parser.

The HLS counterpart is
`kernels/regraph_k4_shared_hbm_wrapper/kernel_hbm_wrapper.cpp` in the
GraSU/ReGraph integration repository. Its two-input reader arbitrates source
blocks for workers 0/2 and 1/3. The simulator reuses the existing finite
`RoutedSourceService`; it does not add a fitted service-rate multiplier.

Four adapter masters plus two source masters plus one Apply/status master
give **seven** physical masters. The retained dedicated-reader mode has
four adapter, four source, and one Apply/status master: **nine**. Logical
write/read clients do not create extra physical memory bandwidth. Diagnostic
output names both the service count and each worker's actual source service.

## Validation Status

Campaign root:
`/data/chuxiao/experiments/sharded_k4_source_pairs_20261019/`.
Before editing, `baseline-v1` froze revision
`a56ea07e050d313814090e59ca71a3a1120ae75e`, inputs, source, compiler,
build flags, and three executable reports. Its source archive SHA-256 is
`2f001d600e357f2a3849f47544031560ebffb9bf4a14238cb652bf3e65cd8280`.

`candidate-v1/results.json` records these passing direct core checks:

- The complete pre-edit system stdout is an exact prefix of the candidate
  stdout. All 30 existing execution records preserve cycles and counters.
- Source-service and shared-AXI test stdout are byte-for-byte unchanged.
- Twelve additional executions comprise three dedicated references and
  nine pairwise runs. They cover 129, 65,569, and 262,273 logical vertices,
  one/two/five destination partitions, all four workers, repeated worker-0
  invocations, pressure, stream depth 1, whole-line directory reads, empty
  work, fixed-round completion, and expected nonconvergence.
- Normal/reverse registration preserves complete counters, invocation
  intervals, round records, state, and cycles. Pairwise/dedicated executions
  preserve state, convergence, and traffic; different cycles are allowed.
- Invalid topology is rejected before issuing memory traffic.

Together the current report has **42 executions**: 38 converged, two fixed
round, and two expected limit failures. There are 13 admission rejections.
Neither expected nonconvergence nor rejected input is a correctness-admitted
converged workload. The parser retains the frozen 13-row and preceding
30-row formats, but the current runner requires the new pairwise section.

The five-shard paired run predicts 5,415,890 cycles versus 5,413,225 for its
dedicated reference, with identical traffic. This approximately 0.05% change
is one synthetic fixture, not a bound for real graphs or measured hardware.
These tests use a registered mock memory backend, not DRAMSim3.

The remaining regression gates now pass:

| Gate | Evidence | Result |
| --- | --- | --- |
| Fresh SST plugin | `sst-gates-v2/plugin.resources.json` | Release build passed; plugin SHA-256 `5d56ec78f7363632f9af20f201f1c2d76e3a3848c9583b6a32cbb9143e5d83b6` |
| Complete C++ suite | `sst-gates-v3/all-core-ctest.stdout.txt` | 34/34 passed |
| Current system runner | `sst-gates-v3/system_final/summary.json` | All 42 executions and 13 admission rejections checked |
| Exact legacy SST replay | `sst-gates-v4/legacy_final/equivalence.json` | All five cases preserve every result field and semantic identity; no ignored fields |
| Python contracts and organization | `delivery-v1/python-tests.stderr.txt` | 50 tests passed |

The legacy replay preserves 99,885 cycles for mixed cold SSSP, 5,997,674 for
multipart warm SSSP, 133,841 for CC, 1,487,890 for warm Residual PR, and 200
for residual update-only. These are unchanged **old-mode** results, not
calibration of the new pairwise topology.

Failed attempts are retained. `sst-build-v1` exhausted its 1-GiB process
address-space allowance. In `sst-gates-v2`, plugin compilation passed but
the nested system wrapper had incompatible address-space/CPU settings.
`sst-gates-v3` passed the complete core suite but its multipart warm legacy
case exceeded a 240-second wall timeout. `sst-gates-v4` reruns all five cases
with a 600-second per-case wall allowance and the identical plugin, source,
inputs, and simulated timing parameters; it passes in 316 seconds overall.
The plugin build's recorded soft-limit-only addendum raises `memory.high`
from 768 to 960 MiB, retaining its 1-GiB physical cap and zero swap. All
follow-ups use finite physical cgroups and full-budget atomic admission.

[evidence.json](evidence.json) records the acceptance checks and SHA-256
identities. The complete raw index and archive are under campaign
`delivery-v1/`, outside Git; their paths and hashes are in that record.
The archive includes source snapshots, compiled test fixtures, build
configuration, before/after outputs, and failed attempts. This delivery
does not admit hardware timing, original-publication matching, or figures.

## Reproduce

From the simulator root, use fresh build/output directories:

```bash
cmake -S . -B build/source-pairs-review -DCMAKE_BUILD_TYPE=Release
python3 scripts/validate_sharded_k4_system_model.py \
  --core-build build/source-pairs-review --output results/source-pairs-review
```

Use `TMPDIR=/data/chuxiao/tmp` on the current hosts; their `/tmp` filesystems
are full. The separate SST regression command is
`scripts/run_component_refactor_regression.py`; select a freshly built plugin,
the fixed five-case contract, and the recorded legacy baseline. Do not reuse
or overwrite a hash-pinned plugin from earlier evidence.

## Remaining Work

The new topology is not yet selected by an SST architecture profile. Current
G search/cache production selection, optimized adapter parameters, production
algorithm variants, and a complete G-to-R campaign require separate wiring
and evidence. Builds in progress are not routed/board performance results.
The two-service source model must not be substituted for the four-reader
artifact when explaining older FPGA measurements. Final Fig7--11 still
requires the declared latest baseline validation and matched experiments.
