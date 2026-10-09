# spine-cycle-sim

Execution-driven cycle simulation for Spine and the GraSU + ReGraph baseline.
The current execution engine is C++ with an SST/DRAMSim3 integration. Python
provides workload preparation, experiment runners, validation, analysis, and
plotting; the earlier Python timing model is also retained for regression.

## Start Here

Contributors and coding agents must follow [the repository working rules](AGENTS.md).

| Task | Entry point |
| --- | --- |
| Understand the code and review a change | [C++ code map](cpp/README.md) |
| Find architecture, implementation, and evidence records | [Documentation index](docs/README.md) |
| Choose an experiment or analysis command | [Script guide](scripts/README.md) |
| Reproduce the accepted figure handoff | [Figures 7--11 package](docs/evaluation_refresh_20260810/figure7_10_handoff_v1/README.md) |
| Understand the organization problems and cleanup order | [Repository structure audit](docs/repository/structure_audit_20261009.md) |
| Audit original GraSU/ReGraph publication comparisons | [Publication-match study](docs/experiments/comparisons/grasu_regraph_publication_match/README.md) |

## Repository Boundaries

This repository owns simulation and analysis, not the production HLS source.
Spine HLS and GraSU/ReGraph HLS live in separate repositories. A simulator
profile must identify the hardware or architecture it models; matching our
ported FPGA implementation does not establish equivalence to the original
GraSU or ReGraph publication.

Use the actual Git worktree root, not a directory name, to identify a checkout:

```bash
git rev-parse --show-toplevel
git branch --show-current
git status --short
```

The local directory named `spine-cycle-sim-sharded-k4-v3` currently holds
`main`; the similarly named parent directory contains several worktrees and
is not itself a repository. There is no required absolute checkout path.

## Layout

| Directory | Responsibility |
| --- | --- |
| `cpp/include/spine_sim/`, `cpp/src/` | Cycle engine, finite resources, and architecture components |
| `cpp/sst/` | SST plugin, memory-backend integration, and run serialization |
| `cpp/tests/`, `tests/` | C++ and Python checks; `tests/data/` contains fixtures |
| `spine_cycle_sim/` | Python orchestration, oracles, calibration, and evidence analysis |
| `scripts/` | CLI entry points, including retained historical experiment commands |
| `configs/` | Versioned architecture profiles, contracts, and evidence identities |
| `docs/` | Navigation, implementation records, evidence, and figure handoffs |
| `build/`, `results/` | Local generated output, not architecture authority |

## Quick Checks

Run from the worktree root. These commands do not run a graph campaign or
rebuild a frozen SST plugin:

```bash
python3 scripts/audit_repository_structure.py
python3 scripts/audit_repository_structure.py --check-docs
python3 scripts/audit_repository_structure.py --check-catalogs
python3 -m unittest discover -s tests -p 'test_repository_structure.py'
```

For C++ core checks, use a separate build directory:

```bash
cmake -S . -B build/review-core -DCMAKE_BUILD_TYPE=Release
cmake --build build/review-core -j2
ctest --test-dir build/review-core --output-on-failure
```

The C++ core does not require SST. SST plugin builds additionally require
SST and the selected memory backend; see the [code map](cpp/README.md).
Do not overwrite a campaign's hash-pinned plugin to perform a quick check.

## Evidence Rules

- A figure package's manifest and provenance define its evidence boundary.
- Correctness, total-time calibration, per-stage calibration, and simulator
  prediction are different claims. Keep their statuses separate.
- Do not infer the current model from a filename, date, or `vN` suffix.
- Frozen profiles, evidence paths, negative results, and plugin hashes remain
  intact during organization work.

The previous long development overview is preserved in
[the historical README](docs/history/README_before_organization_20261009.md).
