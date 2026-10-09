# Documentation

## Start Here

| What you need | Read this |
| --- | --- |
| Figures, plotting code, and the handoff explanation | [Figures 7--11 package](evaluation_refresh_20260810/figure7_10_handoff_v1/README.md) |
| Corrections and limits of that package | [September 17 evidence audit](evaluation_refresh_20260810/figure7_10_handoff_v1/EVIDENCE_AUDIT_20260917.md) |
| Architecture, algorithm semantics, and timing boundaries | [Architecture and contracts](architecture/README.md) |
| How the simulator components work | [Implementation guide](implementation/README.md) |
| Calibration, comparisons, and cost-model investigations | [Experiment guide](experiments/README.md) |
| Why an earlier implementation or result changed | [History guide](history/README.md) |
| Raw evidence and frozen identities | [Evidence guide](evidence/README.md) |
| Repository structure and remaining cleanup work | [Repository guide](repository/README.md) |

You do not need to read the full record catalog to understand the project.
Start with the relevant guide; each gives a short reading order.

## Evidence Boundaries

The selected figure package identifies its inputs and claims. Implementation
alignment, correctness, total-time calibration, per-stage calibration, and
simulator prediction are separate questions. An investigation's filename,
date, or version does not answer them.

The [refresh workspace](evaluation_refresh_20260810/README.md) also retains
earlier candidates. [Historical figures](figures/README.md) and
[earlier paper exports](paper/data/README.md) are not substitutes for the
selected handoff.

## Where New Documents Go

- `architecture/`: durable architecture and execution contracts.
- `implementation/<component>/`: component behavior and implementation records.
- `experiments/<topic>/`: measurements, model analysis, and comparison records.
- `history/`: earlier campaigns, prototypes, and runtime tuning.
- `evidence/`: frozen inputs, reports, and manifests.
- A versioned handoff directory: self-contained deliverables and plotting code.

Keep this directory's Markdown limited to this index. Extend a topic guide
when adding a useful reading entry; do not append every daily milestone here.
Dated records retain their original scope and conclusions, including failures.

## Looking Up An Old Path

The 260 former top-level records were relocated, not deleted. See the
[migration notes](repository/document_migration_20261009.md) and
[old-to-new path map](repository/document_locations.json).
Frozen packages keep their original bytes, so their historical path mentions
may need this map.
