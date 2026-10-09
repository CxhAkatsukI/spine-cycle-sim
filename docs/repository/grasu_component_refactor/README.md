# G+R C++ Component Extraction

This delivery is a behavior-preserving refactor, not a new architecture,
performance optimization, FPGA measurement, or publication-performance match.
Baseline revision: `9b41c15`. The baseline plugin was built from that revision
before moving numerical code; candidate source hashes and its relevant dirty
diff are recorded separately.

## What Changed

| Owner | Responsibility | Change boundary |
| --- | --- | --- |
| [grasu_regraph_runtime.cpp](../../../cpp/src/grasu_regraph_runtime.cpp) | HBM buffer sizes, lane/channel restrictions, deterministic placement, capacity rejection | Existing implementation moved verbatim |
| [grasu_sharded_update.cpp](../../../cpp/src/grasu_sharded_update.cpp) | Degree initialization, shard launch order, native update engine lifetime, counter accumulation | Existing PIMPL and delegations moved verbatim |
| [grasu_runtime_tests.cpp](../../../cpp/tests/grasu_runtime_tests.cpp) | Placement/conservation, overflow rejection, empty-shard buffers | Three existing test bodies moved verbatim into a separate executable |
| [grasu_regraph.cpp](../../../cpp/src/grasu_regraph.cpp) | Readers, source service, gather/merge/apply, iteration control | Those implementations remain unchanged |

The public [header](../../../cpp/include/spine_sim/grasu_regraph.hpp) is unchanged.
CMake and the SST Makefile both include the two new implementation files.
The main G+R source decreased from 6,205 to 5,772 lines; this is a first
ownership boundary, not completion of the larger cleanup.

No profiles, HLS code, algorithm policies, memory timings, fitted coefficients,
frozen plugins, figure inputs, or paper files were changed. Unrelated local
calibration/index changes are excluded from this delivery.

## Fixed Regression Matrix

The [contract](../../../configs/experiments/grasu_component_refactor_v1.json)
was declared before extraction. All runs use the sharded-K4 v8 profiles,
150-MHz core, the same DRAMSim3 configuration/library, compiler, and host flags.
These cases test source equivalence, not speedup or hardware timing accuracy.

| Case | Semantics | Baseline cycles | Baseline backend requests |
| --- | --- | ---: | ---: |
| `sssp_mixed_cold` | 8 vertices; deletion/insertion/weight change; source-initialized SSSP | 99,885 | 33,848 |
| `sssp_multipart_warm` | 131,076 vertices; three destination shards; old-graph converged SSSP, then insertions | 5,997,674 | 1,775,700 |
| `cc_reciprocal` | Reciprocal bridge insertion; explicit hardware full-recompute policy | 133,841 | 50,741 |
| `residual_warm` | Old-graph warm Residual PR; hardware dangling/correction contract | 1,487,890 | 997,048 |
| `residual_update_only` | Same graph/batch; maintenance only, no PR propagation | 200 | 48 |

Acceptance requires correctness PASS, matching input/profile/semantic identities,
the explicitly requested plugin actually loaded, and equality of **every**
result field. There is no ignored-field list. This includes cycle, traffic,
stall, state/result, and request-accounting fields exposed by each runner.

**Accepted on this matrix:** all five baseline/candidate pairs pass correctness
and have byte-identical `result.json` files. The
[comparison report](equivalence.json) records equal hashes, no changed result
fields, and no changed semantic identities for every pair.

## Evidence And Verification

- [Full-result comparison and both source/build identities](equivalence.json).
- [Compressed original runs](raw_runs.tar.gz): all five cases from both phases,
  manifests, raw results, DRAMSim3 outputs, stdout/stderr, campaign commands,
  progress/resource records, and source/input/plugin hashes. No plugin binaries
  are embedded. Packaging does not alter the archived files.
- [Baseline CTest log](verification/ctest_before.txt): all four executables pass.
- [Candidate CTest log](verification/ctest_after.txt): all five executables pass,
  including the separately owned three runtime tests.
- [112 focused Python tests pass](verification/python_tests.txt), covering
  runner/profile/result gates, campaign execution, frozen figure identities,
  original publication-audit evidence, organization, and the comparison helper.
- Both build entry points compile successfully with GCC 15.2.0. The SST build
  retains existing warnings from SST headers and serial LTO compilation.
- Layout/catalog checks, parser-checked local links, and `git diff --check` pass.
- All 2,437 protected artifact/user-file hashes remain unchanged. The original
  `build/sst/libspine_cycle.so` hash remains
  `9a26e1fb51ecf7b99ccf0784c9e5bbc459cf857d293add557b9c52770b2c9d79`.

Fresh comparison plugin hashes:

| Phase | SHA-256 |
| --- | --- |
| Before | `dbf38cc09c6aafc006cc2e03c95960d13c2d5518ec729112188dac70271d9360` |
| After | `5ff6b53fae61c87b896c76d45148b61b6b9357bf38576ff4e2f8f442868e97c7` |

The largest sampled SST process-group RSS is 112.7 MiB. This is one-second
sampling, not an allocator-peak measurement. The full Python suite and the
large-graph/hardware matrices were not rerun by this refactor.

## Reproduce

From the repository root, build a distinct plugin directory:

```bash
make -C cpp/sst \
  BUILD_DIR="$PWD/build/refactor-grasu-after" \
  DRAMSIM3_ROOT=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729 -j1
python3 scripts/run_grasu_refactor_regression.py \
  --lib-dir build/refactor-grasu-after \
  --out-dir results/grasu_component_refactor_v1/after-new \
  --baseline-dir results/grasu_component_refactor_v1/before \
  --jobs 1 --case-timeout-seconds 600
cmake -S . -B build/grasu-refactor-core-after \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/grasu-refactor-core-after -j2
ctest --test-dir build/grasu-refactor-core-after --output-on-failure --timeout 120
```

Use a fresh output path. The runner rejects overwriting an existing run,
records source/input/build identities, and checks loaded-plugin identity.
It also checks candidate source/input files and plugin immutability after
execution. The baseline predates that additional post-run source-file check;
its recorded hashes were checked separately after execution.

The raw archive can restore the comparison baseline on another checkout:

```bash
mkdir -p results/grasu_component_refactor_v1
tar -xzf docs/repository/grasu_component_refactor/raw_runs.tar.gz \
  -C results/grasu_component_refactor_v1
```

Extract only into a new/empty result root. Recorded absolute paths describe the
original machine; the comparison reads results/manifests relative to the phase
directory. Adjust the DRAMSim3 location explicitly on another machine; changing
its library requires a new paired baseline rather than claiming the saved
build identity.

The baseline used a 240-second per-case wall-clock limit. Its multipart case
completed in 238.2 seconds, so the candidate was given an explicit 600-second
limit. This changes only the process timeout, not simulated cycles, inputs,
convergence conditions, memory budgets, or the regression matrix. Actual
commands are saved in each campaign manifest. Neither run is CPU-affinity
pinned or used for a host wall-time performance claim.

To rebuild the pre-extraction numerical sources, use a detached worktree at
`9b41c15`. Copy the new regression contract, two multipart fixtures, runner,
and equivalence helper from this delivery into that worktree; leave its C++
sources unchanged. Build a fresh `before` plugin and invoke the same runner
without `--baseline-dir`. The helper's timeout/source-verification additions
are not part of the numerical model. Original per-phase hashes remain the
authority for the saved run.

The campaign runs one SST process at a time, reserves 16 GiB of available
memory, and uses a 12-GiB emergency threshold. The update-only case can finish
between one-second samples; a recorded zero peak is missing sampling coverage,
not a zero-memory claim.

## Remaining Work

Next separate G+R readers/source service, compute components, and iteration
control, preserving registration order and backpressure. Then address SST
parameter/bootstrap/serialization ownership and the large Spine units.

The five SST cases are bounded regression fixtures, not the full large-graph
matrix. Full PR is covered by existing C++ tests but not by a new SST FullPR
case here. Reproducing original GraSU/ReGraph paper performance still needs
the distinct models and experiments identified by the
[publication-match study](../../experiments/comparisons/grasu_regraph_publication_match/README.md).
