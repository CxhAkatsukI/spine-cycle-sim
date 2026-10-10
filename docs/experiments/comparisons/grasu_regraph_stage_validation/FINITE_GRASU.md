# Finite Original GraSU Composition

## Decision

`G_FINITE_SOURCE16_STATE_LEDGER_PASS_NOT_TIMING`.

The complete independent G path passes original-source state/search controls,
finite shared-bank resource checks, exact repetitions, reversed registration
and selected whole-path UBSan runs. This closes the prepared-source16 finite
composition checkpoint. It does **not** establish a calibrated U250 time,
a paper8 implementation, a temporal-workload throughput or an approximately
10% publication-speed match.

The production SST plugin, original R/A4 components, finite A4/B results,
paper and FPGA figure packages are unchanged. See the
[current stage status](README.md) for the remaining overall goal.

## What Was Connected

Four 64-lane search kernels feed the original ordered dispatcher, two hot
stores with sixteen cache PEs each, and two DDR halves with two sixteen-lane
subcores each. All forty-six AXI ports use the author's four physical bank
bindings. Search ports carry 8-byte words; update/cache ports carry 64-byte
words. Each DDR half's four ports alias one buffer.

The default model uses a 200-MHz clock, two-entry FIFOs, sixteen AXI bursts
and parent requests per port, registered bank arbitration, minimum 64-cycle
memory latency and 512 outstanding beats per bank. These are declared
finite assumptions, not a measured memory-controller configuration. Cache
same-row dependencies are conservatively interlocked; original URAM timing
is not independently admitted.

All nine kernels start in one resident launch window, with no host or DMA
time. Completion includes all search ends, cache writebacks, DDR responses
and fully drained queues/masters/backend. The ten recorded component-done
windows are four searches, two hot stores and four DDR subcores, relative
to batch start. They overlap and must not be added together.

The [implementation guide](../../../implementation/grasu_regraph/original_grasu_finite.md)
lists code owners, timing defaults, routing and unsupported update policies.

## Complete Matrix

Every row ran twice. These are **predicted cycles**, not FPGA cycles.

| Configuration | Updates across batches | Predicted cycles per batch |
| --- | ---: | --- |
| Empty | 0 | 524429 |
| One | 1 | 524437 |
| Three | 3 | 524437 |
| Lane 65 | 65 | 524488 |
| Lane 257 | 257 | 524945 |
| Hot only | 192 | 525063 |
| Cold only | 192 | 524554 |
| Mixed, three resident batches | 896 | 528697, 525018, 525018 |
| Lane 257, reversed registration | 257 | 524945 |
| Mixed, reversed registration | 896 | 528697, 525018, 525018 |
| Cold memory pressure | 192 | 2116707 |
| Hot memory pressure | 192 | 2121393 |

Pressure rows use latency 128 and sixteen bank credits; the hot-pressure
row additionally uses FIFO depth eight. They are multi-parameter resource
controls, not isolated latency-sensitivity measurements.

The unchanged author's source executable ran all eight logical fixtures
both normally and with UBSan. The new finite model additionally ran empty,
lane 257, three-batch mixed and cold-pressure fixtures with UBSan.
All 44 subprocess executions passed. Their summed subprocess wall time
was 146.2 seconds; fixture generation and delivery revalidation are additional.
Peak individual-process RSS was 153800 KiB, approximately 150.2 MiB.
Processes had 4-GiB address-space limits, bounded timeouts and a 16-GiB
available-memory reserve.

## What Was Checked

- C++ compares every slot of all four physical PMA buffers after every batch,
  including stale copies and end guards. Python independently checks every
  final physical buffer and the complete merged state.
- Every row-offset and binary-table request is compared in per-lane source
  order, including multiple updates reusing the same search lane.
- Updates, end markers, parent requests, completed responses, issued/completed
  beats, physical AXI payload bytes and complete drain must conserve.
- Repetition and registration-order controls compare all reported numerical
  fields and every capture hash, including stalls and completion windows.
- Source and finite-model final state agree with an independent sorted-set
  oracle. UBSan must reproduce the same observations without new diagnostics.
- A new Release build passes all fifteen CTest executables, including the
  fourteen existing tests. Python regression passes 211 tests, including
  seventeen new evidence gates, old refactor checks and organization checks.

An empty invocation still loads and writes both full hot regions: 16 MiB
read plus 16 MiB write. This dominates these small-update fixtures, explaining
their similar cycle predictions. It does not establish large-batch or
publication throughput.

The first matrix preflight rejected a response-identity mismatch at 65
updates. The generic AXI fixture can return a later parent first. BIPA now
matches transaction IDs and retires in order within sixteen pending credits;
the shared AXI core was not changed. A subsequent complete preflight passed.
Both attempts and the diagnostic run remain archived and unadmitted.

## Evidence And Preservation

- [Frozen result/model/input/build manifest](finite_grasu_results.json)
- [Revalidation, archive membership and large-capture index](finite_grasu_verification.json)
- [Old-code, protected-evidence and regression record](finite_grasu_preservation.json)
- [Raw/source package](raw_finite_grasu.tar.gz): 594 members, 1304778 bytes;
  SHA-256 `fed4c89f38ac983ae60497badd3a7802bf54065d0a0afe03fd93ef51b3041362`.

The archive contains source snapshots, compiler/flags records, raw traces,
protocols, resource logs, regression output, frozen baseline and preflights.
Large PMA/input captures stay in the ignored runtime tree with 204 indexed
paths/hashes; they are deliberately not all committed. They can be regenerated
by rerunning the prepared fixtures. This is an indexed evidence package, not
a standalone compiler/Vitis installation.

All 2437 protected evidence files remain unchanged. Of 164 previously frozen
code/build files, only `cpp/CMakeLists.txt` changed: removing the two new
independent library/test declaration blocks exactly recovers its preimage.
No old numerical body or production plugin changed. The user's unrelated
calibration patch and outputs were preserved. SST and FPGA matrices were
not rerun because this library is not linked into either production path.

## Reproduce

The same-workspace runner requires the pinned clean upstream checkout and
the original normal/UBSan source-probe binaries identified in the contract.
Their compiler/header dependencies are rechecked. To recreate those controls,
start with the [original source instructions](GRASU_SOURCE_PATH.md); do not
silently accept a differently built binary by dropping its identity check.

Use fresh output directories. Build with
`-DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON`; create a
separate UBSan build adding
`-DCMAKE_CXX_FLAGS="-fsanitize=undefined -fno-sanitize-recover=undefined -fno-omit-frame-pointer"`.
Build the normal test suite and both new targets with `-j2`.
The accepted runtime tree is `results/upstream_stage_controls/grasu_finite_final_v1/`.

Extract `baseline/baseline.json` from the package into a fresh baseline
directory after verifying its archive hash, then run:

```bash
python3 scripts/run_original_grasu_finite.py \
  --binary results/reproduce_G/build/cpp/original_grasu_execution \
  --ubsan-binary results/reproduce_G/ubsan/cpp/original_grasu_execution \
  --baseline results/reproduce_G/baseline \
  --out results/reproduce_G/run
python3 -m unittest discover -s tests -p test_original_grasu_finite.py
```

The optional `--deliver-to` packages only a complete admitted matrix and
refuses to overwrite previous delivery names. `--smoke` is explicitly
unadmitted. Compiler/build and all model/input identities are fixed throughout
each run; collection cannot continue across a source edit.

## Remaining Gates

Original temporal trace and success-count admission, paper8 geometry,
cache/search RTL timing, original DDR/clock/window admission and published-rate
comparison remain open. The existing R/A4/B controls retain their separately
stated timing limitations. C still requires G-produced inputs, measured host
orchestration and non-overlapping/overlapping window accounting.
