# SST And Spine Refactor

Status: both extractions accepted as behavior-preserving on the frozen matrix.
This is not a timing calibration or an original-publication performance match.

This is an incremental, behavior-preserving cleanup. It does not change the
paper, profiles, HLS, fitted timing parameters, or frozen evidence. Existing
local calibration/index changes remain outside its commits.

## Acceptance Sequence

1. Freeze the verified plugin at `abe4c3e` and all source/input/build hashes.
   Run the [fixed matrix](../../../configs/experiments/sst_spine_component_refactor_v2.json).
2. Extract physical HBM mapping and the SST memory backend into cohesive units
   with explicit interfaces. Keep component setup,
   scheduler phase order, payload ownership, and serialization unchanged.
3. Build a distinct SST plugin and compare every result field with the baseline.
   Cover StandardMem and direct DRAMSim3, and retain the G+R regression cases.
4. Separate Spine range reading from SSSP/CC compute behind the existing public
   contract. Share only the existing payload encoding/ABI helpers; introduce no
   alternate architecture or state machine.
5. Repeat CMake, SST, correctness, and exact cycle/counter/conservation checks
   for this second checkpoint. Push only accepted checkpoints.

The matrix includes warm SSSP, non-monotonic deletion, CC insertion and zero-net,
FullPR on both memory transports, warm Residual PR, legacy/current maintenance
carry, and all five preceding G+R cases. Ten cases must pass correctness;
four [existing rejections](BASELINE_ISSUES.md) are diagnostic regressions, not
correctness evidence. Their exit code and rejection signature must persist,
and every result field is still compared. Historical compatibility cases are
not relabeled as current FPGA evidence. Failures and timeouts stay recorded.

## Code And Commands

The [shared regression driver](../../../scripts/run_component_refactor_regression.py)
owns campaign execution; [comparison/identity helpers](../../../spine_cycle_sim/experiments/refactor_equivalence.py)
own its validation. The old G+R CLI remains an import/command-compatible wrapper.
Use distinct output and build directories for every phase. The baseline plugin
is the preceding verified build, not the older frozen figure plugin.

```bash
python3 scripts/run_component_refactor_regression.py \
  --contract configs/experiments/sst_spine_component_refactor_v2.json \
  --lib-dir build/refactor-grasu-after \
  --out-dir results/sst_spine_component_refactor_v2/before \
  --jobs 2 --case-timeout-seconds 600
```

Before reuse, the previous plugin and numerical source hashes must match their
recorded identity. Reserve 16 GiB of available memory, stop below 12 GiB, and
bound each job. A passing compile or total-time fit is not equivalence.

## Review The Extraction

| Responsibility | Implementation | Boundary |
| --- | --- | --- |
| Logical-to-physical HBM mapping | `cpp/sst/physical_hbm_mapper.hpp/.cpp` | Pure mapping/validation; no SST dependency |
| SST memory backend | `cpp/sst/sst_memory_backend.hpp/.cpp` | Arbitration, staged submissions, StandardMem/direct transport, response queues and payload completion |
| Spine range reader | `cpp/src/spine_split.cpp` | `SpineSplitReader`, source/edge streaming and range resolution |
| Spine state compute | `cpp/src/spine_sssp_compute.cpp` | `SpineSplitSsspCompute`, SSSP/CC updates, owner/reactivation and result publication |
| Private payload ABI | `cpp/src/detail/spine_split_payload.hpp` | Only existing shared constants and five encoders/decoders |

The public `spine_split.hpp` and G+R headers are unchanged. Both build lists
include the new sources; the SST Makefile also depends on the new private
headers. CMake can test the mapper without an SST installation. No `.inc`
file, alternate timing multiplier, or copied scheduler was introduced.

SST setup, algorithm references and serialization still occupy a large
`OnlineMemoryProbe`; `spine_l0.cpp` and combined test sources also remain
large. This is an accepted incremental boundary, not completion of all code
modularization. See the [code map](../../../cpp/README.md) for current owners.

The [definition audit](definition_equivalence.json) checks all 87 reader and
49 compute definitions, including constructor initializers and literals.
Their AST leaf-token sequences are unchanged. The 35 backend and three mapper
method bodies also passed this check during SST extraction. The independent
full-result regression is the numerical acceptance gate.

## Results And Evidence

Both [SST equivalence](sst_equivalence.json) and
[Spine equivalence](spine_equivalence.json) report **14/14 byte-identical
result files**, zero ignored fields, ten correctness-admitted executions and
four unchanged known rejections. All cycle, traffic, stall, FIFO, payload,
owner, and conservation fields in each result are compared, not a selected
subset. Positive manifests additionally retain the same semantic identities
and prove the requested plugin was loaded. Diagnostic rejections retain their
raw failed runs; they are never promoted to correctness/calibration evidence.

| Case | Unchanged cycles | Unchanged backend requests | Admission |
| --- | ---: | ---: | --- |
| Spine warm SSSP | 25,469 | 2,382 | Pass |
| Spine SSSP deletion | 69,215 | 8,598 | Pass |
| Spine FullPR, StandardMem | 9,595,069 | 2,248 | Pass |
| Spine FullPR, direct DRAMSim3 | 9,595,069 | 2,248 | Pass |
| Spine warm ResPR | 117,222 | 7,040 | Known rejection |
| Spine CC insertion | 25,525 | 2,446 | Pass |
| Spine CC zero-net | 11,055 | 1,341 | Known rejection |
| Spine legacy carry | 11,734 | 1,863 | Known rejection |
| Spine owner carry wrapper | 8,157 | 1,215 | Known rejection |
| G+R mixed cold SSSP | 99,885 | 33,848 | Pass |
| G+R multipart warm SSSP | 5,997,674 | 1,775,700 | Pass |
| G+R CC | 133,841 | 50,741 | Pass |
| G+R warm ResPR | 1,487,890 | 997,048 | Pass |
| G+R update-only | 200 | 48 | Pass |

Six C++ test executables pass after each checkpoint; 126 focused Python tests
pass. [Verification logs](verification/) retain the pre-extraction core run,
both C++ checkpoint runs, and Python output. The full Python suite and a new
FPGA matrix were not run. Source-only equivalence on this matrix does not
prove every untested workload correct or establish stage timing accuracy.

The [raw archive](raw_runs.tar.gz) contains the initial rejected v1 attempt,
the unchanged-code FullPR budget probe, and all three v2 phases: `before`,
`after_sst`, `after_spine`. Each phase records source/input/plugin hashes,
compiler and build flags, command lines, raw results, DRAM output, resource
logs, and runner outcomes. Builds use GNU C++ 15.2.0, `-O3 -DNDEBUG -flto`,
no native flags and no PGO; each phase uses a distinct plugin directory.
Campaigns run at most two jobs, reserve 16 GiB and stop below 12 GiB.

To check or replay a candidate against an available frozen baseline:

```bash
make -C cpp/sst BUILD_DIR=../../build/review-sst \
  DRAMSIM3_ROOT=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729 \
  NATIVE_HOST=0 PGO_MODE=off
python3 scripts/run_component_refactor_regression.py \
  --contract configs/experiments/sst_spine_component_refactor_v2.json \
  --lib-dir build/review-sst --out-dir results/review-refactor \
  --baseline-dir results/sst_spine_component_refactor_v2/before \
  --jobs 2 --case-timeout-seconds 600
```

Use a fresh output directory; the driver refuses to overwrite a frozen run.
The baseline is available in the raw archive. The original figure plugin and
2,437 protected artifact/user files remain unchanged. Existing local v4
calibration/index edits are not included in this cleanup commit.

## Next Study

After these checks, execute the separate
[G/R stage-validation plan](../../experiments/comparisons/grasu_regraph_stage_validation/PLAN.md).
Do not infer per-stage accuracy from complete-system timing agreement.
