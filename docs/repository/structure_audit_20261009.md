# Repository Structure Audit

Audit date: 2026-10-09. Scope: `spine-cycle-sim`; related HLS repositories were
checked only to identify ownership boundaries. No architecture-equivalence or
performance claim is made by this audit.

## Baseline

Inspected revision: `520f8bcf1af8578090bfb6a439797abe45194f4e` on `main`.
The actual worktree is nested under the directory named
`spine-cycle-sim-sharded-k4-v3`. The enclosing `spine-cycle-sim` directory is a
worktree container, not a Git root. Other worktrees are distinct checkouts, not
duplicate source to delete.

Before this pass, tracked content included:

| Area | Files |
| --- | ---: |
| `docs/` | 2,688 |
| Top-level `docs/*.md` | 260 |
| `docs/evidence/` | 1,915 |
| `scripts/` | 222 |
| `configs/` | 156 |
| C++ files | 46 |
| Python package files | 83 |
| Test source files | 167 |
| Test fixture files | 278 |

The source/script/test-code inventory contains 184,464 lines, including the
retained `tools/` host utility; this excludes
the much larger graph-fixture line count. File count alone is not a quality
metric. The findings below concern ownership, reproducibility, and review
boundaries, not a quota for files or lines.

Existing local changes were present in
`scripts/build_current_fpga_spine_v4_index.py`, plus untracked calibration/index
evidence. They are outside this cleanup and must remain untouched.

## Findings

### P1: The entry point describes the wrong implementation era

The previous root README introduced a first-version Python model and a C++
engine under development, then accumulated many later milestones. It did not
give one short route to the current execution engine, accepted figure handoff,
or code-review boundaries. Its absolute `cd` commands also point to locations
that are now worktree containers or have moved.

Impact: a reviewer can start from the wrong model or reuse a historical result
as current evidence. A folder or branch name cannot identify a frozen plugin.

Action in this pass: replace the root entry point and preserve the former
overview in [history](../history/README_before_organization_20261009.md).

### P1: Large execution units hide component boundaries

| File | Baseline lines | Mixed responsibilities |
| --- | ---: | --- |
| [online_memory_probe.cpp](../../cpp/sst/online_memory_probe.cpp) | 11,634 | SST registration, configuration, payload/bootstrap setup, multiple execution modes, counters, serialization |
| [grasu_regraph.cpp](../../cpp/src/grasu_regraph.cpp) | 6,205 | Placement, PMA update orchestration, several readers, source service, gather/merge/apply, iteration control |
| [spine_l0.cpp](../../cpp/src/spine_l0.cpp) | 6,164 | Maintenance, carry, memory traffic, and control paths |
| [spine_split.cpp](../../cpp/src/spine_split.cpp) | 5,914 | Range resolution, source/state work, compute, and drain |
| [core_tests.cpp](../../cpp/tests/core_tests.cpp) | 10,512 | Many component and system regression suites in one executable source |

Impact: a feature change requires reviewers to reason about unrelated modes
and large private state. This is especially risky before adding an original
ReGraph control implementation; inserting another mode into these units would
make the A/A4/B/C comparison harder to audit.

Action in this pass: add a [code reading map](../../cpp/README.md). The units
are not yet split. A mechanical file move would not solve their mixed ownership.

### P1: Documentation is organized by milestones, not authority

The baseline had 260 top-level Markdown records and no documentation portal.
Candidate, native, normalized, projected, failed, and corrected results appear
side by side. Some documents explicitly supersede earlier claims, but finding
that relationship requires prior knowledge.

Impact: the nearest matching filename can be mistaken for the right evidence.
The September 17 figure correction demonstrates why provenance, not naming,
must decide which inputs belong together.

Action in the first pass: add navigation and a topic catalog. This did not
solve the flat directory itself. The follow-up physically relocated all 260
records, added short topic guides, and relegated the complete catalog to a
lookup appendix. See the [migration report](document_migration_20261009.md).

### P2: Script names encode history instead of workflow ownership

The flat CLI directory contains execution, preparation, validation, fitting,
export, rendering, and historical campaign variants. For example, several
`build_current_fpga_*`, `analyze_current_fpga_*`, and versioned finalizers consume
different input roots and contracts.

Impact: selecting a similarly named script can run the wrong stage or model.
Large runners also mix result validation, parameter assembly, and execution.
`run_sst_spine_vertical.py` is 2,647 lines; Python
`calibration/current_fpga.py` is 2,511 lines and contains several model families.

Action in this pass: add [the task guide](../../scripts/README.md) and
[role catalog](../../scripts/CATALOG.md). CLI paths are retained because tests,
records, and reproduction commands already use them.

### P2: Build and evidence identity require explicit migration

The C++ core uses CMake, while the SST plugin has a separate Makefile source
list. Plugin flags, DRAMSim3 linkage, profiles, and hashes affect the evidence.
Large fixtures, reports, and packaged figures are tracked alongside code but
serve different review purposes.

Impact: a source split checked only through CMake can miss the SST build. A
bulk path rewrite can invalidate reproduction commands or hash-pinned artifacts.
Successful core tests do not establish bit-identical simulation output.

Action in this pass: document both build boundaries and preserve fixtures,
profiles, manifests, raw evidence, figures, and existing plugin libraries.

### P2: There is no concise review/verification ladder

The core has focused owner and vertex-lifecycle tests, but its broad tests are
large. Python tests mix unit, profile, fixture, runner, and evidence validation.
No root guide distinguishes quick checks from a long SST campaign.

Impact: reviewers can either skip meaningful verification or launch an
unnecessarily large experiment while checking a small change.

Action in this pass: document a core/runner/SST/evidence ladder. The complete
test suite and a fresh hardware matrix have not been run by this structure audit.

## Organization Completed in This Pass

- Root README: current implementation, ownership, quick checks, and evidence rules.
- `docs/README.md`: current handoff plus scoped architecture/evidence navigation.
- `cpp/README.md`: component map and build/test boundaries.
- `scripts/README.md` and generated `CATALOG.md`: task and command-role navigation.
- `docs/history/`: preserved previous README with relative documentation links.
- `audit_repository_structure.py`: repeatable tracked-file inventory and catalog checks.
- Physical documentation migration: 260 records in 11 collections, with topic guides.
- Relocation map and layout checks; parser-checked Markdown/diagram links.

No execution behavior, timing model, result CSV, profile, plugin, or hardware
artifact is modified. Two Python docstring references were updated for the
relocation. Code modularization remains incomplete.

## Next Extraction Order

| Order | Change | Required gate |
| --- | --- | --- |
| 1 | Extract runner validation from CLI assembly, keeping CLI/import compatibility | Existing runner tests and deterministic manifest checks |
| 2 | Separate G+R placement/update, edge/source readers, compute components, and round controller behind the existing public header | C++ G+R tests plus byte/cycle/counter-equivalent SST smokes |
| 3 | Separate SST parameter parsing, payload/bootstrap preparation, component wiring, and result serialization | CMake and SST builds; identical accepted result schemas and ledgers |
| 4 | Split core tests by component ownership and calibration code by model family | Same test discovery and preserved public imports |
| 5 | Reorganize historical CLIs with import/command compatibility; narrative document migration is complete | Preserved pinned evidence, old commands still usable |

The original-publication ReGraph A/A4 model should have an explicit component
and profile boundary. Do not implement it as a hidden timing multiplier or
silently replace the currently routed G+R path while restructuring.

Before any execution refactor, freeze source revision, relevant dirty diff,
compiler flags, profiles, plugin hashes, input hashes, and representative
baseline outputs. Numerical/counter equivalence and input/output conservation
are required; changes in calibration coefficients are not a refactor gate.

Worktree removal, fixture externalization, and evidence deletion are separate
decisions, not prerequisites for improving code navigation.

### First Extraction Checkpoint

Native GraSU/ReGraph runner validation and capability/topology gates now live
in `spine_cycle_sim/experiments/grasu_native_validation.py`. The legacy CLI
re-exports its public functions; the matrix imports the canonical module.
Two fresh pre/post SST result JSON files are exactly equal, including a
preserved mathematical-correctness rejection. A separate Release CMake build
passes all four C++ test executables. See the
[publication-match study](../experiments/comparisons/grasu_regraph_publication_match/README.md)
for source admission, raw results, and the unfinished original-model work.
The large C++ units and the larger Spine runner have not yet been split.

### First C++ Extraction Checkpoint

The subsequent [G+R C++ extraction](grasu_component_refactor/README.md)
moves HBM runtime placement and destination-shard PMA update orchestration to
two implementation files, keeping the public header unchanged. Three runtime
placement tests have their own executable. Both CMake and SST source lists
include the new files. The remaining G+R readers/compute/controller, SST
bootstrap/serialization, and large Spine units still require incremental
extraction. This checkpoint does not replace the original-publication A/A4
implementation or performance experiments.

## Verification of The Initial Navigation Pass

- Seven organization-tool unit tests passed.
- Ten profile/capability tests passed.
- Seven sharded-K4 profile/evidence tests passed.
- Four complete figure-handoff tests passed, including frozen input gates,
  cross-figure plugin identity rejection, and output-manifest hashes.
- Both generated catalogs match their expected contents.
- All local links in the eight navigation/archive documents resolve.
- `git diff --check` passed; the pre-existing script diff remains unchanged.

This is 28 focused tests, not the full Python suite or a C++/SST rebuild.
No graph simulation, FPGA execution, fit, or rendering was launched. Core
modularization remains future work; pinned material should stay in place.

## Documentation Migration Verification

- All 260 original records have one new destination and no flat forwarding copy.
- All 195 previously resolving Markdown-link targets were preserved during relocation.
- A byte snapshot confirmed 2,437 existing artifact/user files unchanged.
- Guides distinguish current handoffs from historical and failed investigations.
- The layout check prevents new top-level dated records and detects missing destinations.
- Final navigation checks: 285 documents, 825 valid local links, no broken targets.
- Follow-up focused tests: 63 passed, 2 skipped for unavailable historical evidence.

The [migration report](document_migration_20261009.md) defines the exact scope.
Frozen packages and evidence are deliberately not physically reorganized;
the new guides provide their human reading entry points.
