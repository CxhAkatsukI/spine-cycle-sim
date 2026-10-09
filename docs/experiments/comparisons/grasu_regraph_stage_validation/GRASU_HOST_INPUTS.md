# Original G Host And Kernel Composition

## Conclusion

Eight predeclared cases pass original GraSU trace-aware host preparation,
original source16 kernel-function composition and original host merge, with
**two explicit host bounds guards and defined upload padding**. Every case
passes two normal runs and one UBSan run with identical complete recorded
states, protocols and counters. All eight earlier prepared-PMA kernel cases
are freshly compiled and remain exactly equal to their frozen results.

This admits the repaired functional chain. It does **not** admit unchanged
original-host correctness, concurrent RTL behavior, finite-resource device
timing, a real temporal workload or a published-throughput match. Device
cycles and publication error are null. No production simulator, HLS port,
frozen plugin, paper or figure is modified.

Accepted run: `results/upstream_stage_controls/grasu_host_final_v1`.
Author revision: `e95da256be9e7f2361449323b6fe0abf98c1b152`.
See the [implementation ownership guide](../../../implementation/grasu_regraph/original_grasu_host.md)
for code boundaries and the [current study status](README.md) for other gates.

## Observed Host Failures

The unchanged original PMA class reads beyond the last element when counting
the sorted union's rows. After guarding that loop, its initial-edge filtering
still reads beyond `init_edges_vector`. The unchanged and row-only variants
both abort at the `std::vector` bounds assertion on the same empty-batch
input. These are observed host C++ failures, not measured FPGA failures.

Two versioned patches add only `cur_loc < vector.size()` to the respective
conditions. The runner makes isolated copies and requires the source diff
to contain exactly one changed line per guard. The original header hash is
`1c0ddec4066cb6370675e1fd3e913269d15ffa502af74ee93527aa7cf231437e`;
the author checkout stays untouched. Every accepted case uses both guards.

The original upload block allocates cache-sized buffers even for tiny graphs
but does not initialize every padded slot. The control uses the same parity
split and duplicate cache/DDR layout, explicitly filling padding with the
empty-slot value. This prevents uninitialized preload data from being silently
treated as a valid original-host behavior. The original upload block itself
is not executed; its OpenCL/DMA cost is outside this control.

## Fixed Matrix

Counts below are per execution. All inputs are synthetic original-format
traces; `threshold_ring` is not a publication dataset or a real temporal graph.

| Case | Vertices | Initial edges | Updates | Final edges | Reserved segments | Search reads |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Empty graph | 8 | 0 | 0 | 0 | 0 | 0 |
| Empty batch | 64 | 32 | 0 | 32 | 32 | 0 |
| Insertion only | 64 | 0 | 32 | 32 | 2 | 64 |
| Full deletion | 64 | 32 | 32 | 0 | 2 | 64 |
| Mixed reservation | 96 | 64 | 80 | 112 | 8 | 80 |
| Hot skew | 128 | 44 | 44 | 72 | 9 | 53 |
| Same segment | 32 | 3 | 62 | 3 | 1 | 62 |
| Threshold ring | 262,208 | 262,208 | 262,208 | 524,416 | 262,208 | 262,208 |

Insertion-only starts with empty reserved segments and fills them to sixteen
live entries. Full deletion starts with two full segments and empties them.
Mixed reservation checks future-insertion space, stale search heads and
initial-edge compaction. Hot skew checks unequal trace-aware priorities and
multi-segment rows. Same-segment performs sequential repeated insert/delete
pairs; this checks source-functional state, not concurrent DDR hazards.

Threshold ring reaches both sides of the two-half cache boundary. Its update
routes are `[131072, 32, 131072, 32]` in cache-even, DDR-even, cache-odd,
DDR-odd order. Thus 64 updates actually reach cold DDR segments rather than
only exercising a small all-hot graph. Original host mapping is checked as a
permutation and nonincreasing priority; equal-priority IDs are not forced into
a fabricated order.

Every accepted execution checks all four physical buffers: 8,388,608 slots
for the seven small cases and 8,390,656 for threshold ring. The independent
Python oracle checks all recorded mapping/offset/search/prepared/final-state
values and every request/dispatch packet. Original host merge receives the
observed device buffers, then restores the exact final external-ID edge set.

## Validation And Resources

All 47 bounded steps pass their declared exit gates. They include four new
compiles, two expected bounds aborts, 24 accepted executions, seven malformed
input rejections, a fresh old-probe compile and eight exact old-case runs,
and ten focused Python tests. Twelve actual-capture corruptions are separately
rejected: mapping, offsets, search heads, prepared/final state, operation,
protocol header/route/address, counter type, diagnostics and truncated state.

There are no UBSan diagnostics. The original Vitis two-line width warning
is retained and counted once per insertion; extra or different diagnostics
fail. The warning is neither suppressed nor relabeled as a sanitizer failure.

Summed subprocess wall time is approximately 86 seconds. Maximum individual
process RSS is 507,476 KiB (UBSan compiler), below 0.49 GiB. Launches are
sequential with a 4-GiB address-space limit, 128-MiB stack, 16-GiB available
memory reserve and 300-second compile/run timeout. RSS is `wait4`'s maximum
individual-process value, not simultaneous process-tree usage or the Python
analysis process. Wall time is test cost, not hardware latency.

Compilation uses GNU g++ 15.2.0, `-std=c++17 -O1 -g0`, assertions,
function/data sections, Vitis HLS 2024.1, real XRT/OpenCL headers and GMP.
UBSan adds `-fsanitize=undefined -fno-sanitize-recover=all`. Original loader,
priority comparator and merge are executed from included original `host.cpp`;
its renamed device main is unused and discarded by linker section GC.

The earlier G result comparison includes complete final state, every protocol
field, warnings and counters, not just a final checksum or elapsed time.
The frozen 141-file pre-change source/evidence baseline remains unchanged.
Additional core/protected-evidence/organization checks are recorded in
[preservation verification](grasu_host_preservation.json): 13 existing C++
tests and 160 focused Python tests pass, including 15 organization tests.
The unchanged C++ build is reused, not rebuilt. The earlier exact
SST/Spine matrix is preserved, not claimed to be rerun by this source control.

## Reproduce And Review

Use the clean author checkout described in the [study guide](README.md).
The archive includes a baseline copy, so reproduction does not require this
machine's previous `results/` directory. Verify the archive/member hashes in
[delivery verification](grasu_host_verification.json) before extracting it.

```bash
mkdir -p results/reproduce_grasu_host
tar -xzf docs/experiments/comparisons/grasu_regraph_stage_validation/raw_grasu_host.tar.gz \
  -C results/reproduce_grasu_host baseline/baseline.json
python3 scripts/run_original_grasu_host.py \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --xrt-include /opt/xilinx/xrt/include \
  --baseline results/reproduce_grasu_host/baseline \
  --out results/reproduce_grasu_host/run
python3 -m unittest discover -s tests -p test_original_grasu_host.py
```

[Results](grasu_host_results.json) record sources, binaries, dependencies,
inputs, compatibility variants, resources and every analysis. The
[raw package](raw_grasu_host.tar.gz) retains all input traces, mapping/protocol
captures, prepared source/diffs, logs and four nonaccepted preflights. Large
complete prepared/final states and binaries are hash-indexed, regenerable,
and rechecked before delivery rather than copied into Git.

Preflight v1 failed during XRT type inclusion. V2 exposed that `git apply`
had skipped patches in the ignored subdirectory, leaving all three variants
unchanged. V3 used explicit GNU patch plus a changed-line-count gate and
passed the first smoke. V4 passed the eight-case normal preflight before
the final runner/validation/package identities were frozen. None substitutes
for the final repeated/UBSan matrix; their original diagnostics are retained.

## Remaining Gates

Both cache halves still imply 16 MiB preload and 16 MiB writeback per
invocation, even with zero updates. Cold update reads/writes imply 64 bytes
each per selected segment. These are source-loop/logical counts, not measured
AXI bursts or service cycles. A finite G model must account for preload,
dependent search responses, update pipelines, DDR alias hazards, writeback
and backpressure; an update-count multiplier is insufficient.

Publication admission still needs the real temporal trace/batches, successful
update numerator, source16 versus paper8 geometry, clock/memory configuration
and original event window. A4/B must hold downstream resources fixed before
attributing a difference to the adapter. C still needs measured host windows
and overlap accounting. No approximately 10% publication match is claimed.
