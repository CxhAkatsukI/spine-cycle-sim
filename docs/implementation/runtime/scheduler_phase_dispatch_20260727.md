# Scheduler phase-dispatch optimization

Date: 2026-07-27

Branch: `codex/scheduler-phase-dispatch`

Baseline commit: `5154af6` (`Unify Spine maintenance timing boundaries`)

## Scope

The scheduler still advances every simulated clock edge and preserves the
global `prepare -> evaluate -> commit` order. This change only omits virtual
calls to phases that a component declares to be permanent no-ops:

- `Fifo`: no `evaluate`; registered pushes and pops still commit every cycle.
- `MemoryBackend`: no `evaluate`; memory completion remains in `prepare` and
  arbitration/submission remains in `commit`.
- `BankedMemory`: no `commit`; its timed request handling remains in
  `evaluate`.

Registration order is preserved independently in each phase. Removing a
component removes it from the identity list and all phase lists. There is no
idle-cycle skip, event prediction, queue elision, or changed timing rule.

## Verification

Build and run the C++ tests:

```bash
cd /home/chuxiao/spine-cycle-sim-runtime
cmake -S . -B build/cycle-core -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/cycle-core -j 8
ctest --test-dir build/cycle-core --output-on-failure
```

Result: both C++ test binaries passed. The new
`scheduler_phase_dispatch` test covers all phase combinations, two clock
domains, and removal from every phase list.

Run the Python regression suite against the same ignored evidence directory as
the primary worktree:

```bash
cd /home/chuxiao/spine-cycle-sim-runtime
ln -s /home/chuxiao/spine-cycle-sim/results results
python3 -m unittest discover -s tests
```

Result: 397 tests passed and 5 evidence-dependent tests were skipped.

Build the SST element:

```bash
cd /home/chuxiao/spine-cycle-sim-runtime
make -C cpp/sst -j 4
```

The frozen `syn_spread_e512` Full PageRank case was then rerun through both
architectures with the optimized SST element. The complete `result.json`, not
only headline cycles, is byte-identical to the baseline:

| Architecture | Cycles | HBM requests | Baseline/optimized SHA-256 |
| --- | ---: | ---: | --- |
| Spine Candidate10 | 231,555 | 18,415 | `47b358e7af0cf7aed38d00fec74d0957574b706ace5799ff9b2846ffbc831ab7` |
| GraSU + ReGraph | 162,791 | 52,992 | `ac54732808064b216aa532c42e98821c98a39246b5532eb081f23e654d80abd6` |

Raw optimized evidence is in
`/data/tmp/chuxiao/scheduler_phase_dispatch_verify_20260727`. The baseline is
the same case under
`/data/tmp/chuxiao/candidate10_hls_v3_formal_matrix_20260727`.

An interleaved ABBA host-wall sample on the Spine case measured baseline
3.400/3.347 seconds and optimized 3.295/3.183 seconds, approximately a 4%
median reduction under the current shared-machine load. Host wall time is not
simulated hardware performance and this small optimization does not satisfy the
large-graph runtime gate by itself.

