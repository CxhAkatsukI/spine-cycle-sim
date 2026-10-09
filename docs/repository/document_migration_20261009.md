# Document Migration

Date: 2026-10-09. Scope: the simulator repository's narrative documentation.
The 260 formerly flat `docs/*.md` records were physically relocated; they
were not deleted or replaced by 260 forwarding stubs.

## New Locations

| Collection | Relocated records |
| --- | ---: |
| Architecture and contracts | 12 |
| Spine implementation | 60 |
| GraSU + ReGraph implementation | 33 |
| Runtime integration | 13 |
| Algorithm implementation | 4 |
| Calibration investigations | 30 |
| Workloads and comparisons | 20 |
| Cost/resource analysis | 8 |
| Early component-model history | 23 |
| Campaign history | 30 |
| Runtime optimization history | 27 |
| Total | 260 |

Each collection has a short guide with selected reading entries. The main
[documentation index](../README.md) leads to those guides, not a flat list of
every milestone.

## What Changed

- Record locations and their relative Markdown links, including diagram links.
- One previously broken absolute diagram link was replaced with a repository-relative link.
- Navigation, the generated detailed catalog, and two Python docstring references.
- A layout check that detects new flat records and incomplete relocations.

The record prose, conclusions, dates, and experimental numbers were not
reinterpreted. Location is not an evidence-admission decision.

## What Stayed Fixed

Existing `docs/evidence/`, `docs/evaluation_refresh_20260810/`,
`docs/figures/`, and `docs/paper/` files retained their paths and bytes.
Their archived plain-text path mentions are intentionally not rewritten.
No profile, workload, CSV, plugin, calibration coefficient, hardware artifact,
or paper source was changed.

The pre-existing index-builder change and untracked calibration/index evidence
were preserved. The migration did not stage, commit, or push them.

## Looking Up Old References

The [JSON relocation map](document_locations.json) records all 260 old and new
paths. For an old filename mentioned by a frozen package, search the map:

```bash
rg 'spine_architecture_evidence_crosswalk.md' docs/repository/document_locations.json
```

Use the new path to read the document. Keep the frozen manifest/package
unchanged unless deliberately publishing a separately versioned artifact.

## Verification

The migration checked all 260 destinations and all 195 previously resolving
Markdown-link targets in the moved records and initial navigation documents.
A byte-identity snapshot verified 2,437 existing artifact/user files, including
the pre-existing index-builder edit. The complete figure-handoff tests check
the package's frozen identities separately.

Final checks covered 825 local links across 285 narrative/navigation documents,
with no broken targets. Comparison against the original Git records confirmed
that all 260 relocated bodies changed only for Markdown links, including the
one repaired pre-existing diagram link.

Focused tests: 63 passed, 2 skipped. These covered the organization tool,
profile/capability and sharded-K4 evidence checks, the complete figure handoff,
and the two calibration modules whose docstring references changed. The two
skips require historical evidence directories absent from this checkout.
Layout/catalog checks and `git diff --check` also passed. No complete C++/SST
rebuild or graph campaign was performed.

Routine layout/catalog checks and the remaining code-refactoring scope are
described in the [repository guide](README.md). This migration is not a timing,
correctness, calibration, or hardware experiment.
