# Repository Working Rules

These instructions apply to the complete simulator repository. Read the root
README, the relevant documentation guide, and the owning profiles/contracts
before changing an implementation or launching an experiment.

## Clear Structure Is Required

- Keep a task-oriented root README and `docs/README.md`; do not append daily
  milestones or flatten investigation documents into the documentation root.
- Put contracts in `docs/architecture/`, implementation explanations in
  `docs/implementation/<component>/`, and experimental analyses in
  `docs/experiments/<topic>/`. Each collection needs a short reading guide.
- Keep earlier campaigns and runtime tuning in `docs/history/`. Preserve
  failed experiments; a date or version suffix is not an acceptance decision.
- Keep frozen evidence and handoff paths intact. Update references and the
  relocation map deliberately when moving prose. Never silently rewrite a
  frozen manifest, input, output, plugin identity, or package to pass a check.
- New experiment code belongs to a named, cohesive package with thin CLI
  entry points and focused tests. Do not add another set of near-duplicate
  versioned top-level scripts when shared logic can have one explicit owner.
- Update guides and generated catalogs with structural changes. Run the
  document-layout and catalog checks before committing.

## Code Must Be Reviewable

- Give each module one coherent responsibility and a small explicit interface.
  Separate input preparation, execution, validation, analysis, and packaging.
- Read the affected public contracts first. Do not hide a new architecture
  inside a timing multiplier or a large conditional mode in an existing
  monolithic component. A distinct topology needs a distinct configuration
  and a reviewable implementation boundary.
- Existing large units require incremental, behavior-preserving extraction.
  Do not claim that a code map or file move has completed modularization.
  Avoid unrelated refactors and arbitrary line-count quotas.
- Keep CLI/import compatibility where existing runs depend on it. Use
  structured parsers for profiles, manifests, and result formats.
- Explain only non-obvious invariants, resource constraints, and timing
  boundaries. Test those invariants rather than merely a happy-path output.
- Before numerical-code extraction, freeze source, relevant dirty diff,
  compiler flags, profiles, plugins, inputs, and representative outputs.
  Check correctness, cycles, counters, and request conservation against that
  baseline. Passing compilation alone is not equivalence.
- Update both applicable build lists: CMake for the core and the SST
  Makefile for plugin sources. Build in a new directory, not over a frozen
  plugin used by existing evidence.

## Fair Experiments And Honest Conclusions

- Record the algorithm, graph identity and transformations, initial state,
  update batch, convergence rule, topology, clock, memory budget, and measured
  event window for each comparison. Do not mix warm and cold starts.
- Separate GraSU update, adapter/ReGraph compute, and host orchestration
  where the evidence allows. Do not double-count overlapping stages or omit
  a stage from an end-to-end claim without stating the boundary.
- Matching our routed port, matching total FPGA time, matching individual
  stage times, and reproducing published GraSU/ReGraph performance are
  different claims. Report their statuses separately.
- Original-publication reproduction and resource-matched controls are
  separate experiments. For ReGraph, identify the original topology (A),
  its resource-matched control (A4), the adapter-integrated path (B), and
  complete G+R (C). Confirm definitions from sources before implementing.
- Never fit a holdout, cherry-pick a passing row, or insert an unexplained
  slowdown/speedup factor to meet a requested error threshold. Report the
  full predeclared matrix, including timeouts, missing data, and failures.
- Distinguish measured FPGA data, conserved simulator ledgers, modeled
  energy, simulator timing predictions, and fitted model outputs. Correlation
  is not stage calibration. Missing counters remain a limitation.

## Safe Execution

- Measure available memory and per-process peak RSS before scaling a run.
  Bound parallelism by memory with an explicit reserve, not CPU count alone.
- Give runs bounded timeouts, unique output paths, and saved stdout/stderr.
  Start with a correctness smoke, then a bounded representative matrix.
  Do not silently reduce workload semantics to make a run complete.
- Preserve raw evidence and fixed model identities. Record repetitions,
  compiler configuration, affinity, and whether a value is measured or
  projected. Keep simulator wall time separate from device-cycle time.
- Keep progress updates responsive while tools run. A queued/running job is
  not a completed experiment or a background task that is guaranteed to finish.

## Delivery And Git

- Deliver each study in one documented folder containing its scope, source
  references, frozen inputs/configuration, raw or indexed outputs, analysis,
  reproduction commands, acceptance criteria, and final conclusions.
- A defensible mismatch or unsupported claim is a valid finding. It is not a
  successful paper-performance match. State what was achieved and what was not.
- Do not edit the paper unless requested. Keep figure packages and analysis
  deliverables in this repository for review.
- Preserve existing user changes. Commit only the requested, inspected scope;
  do not sweep unrelated untracked calibration outputs into a cleanup commit.
  Fetch before pushing, resolve divergence without force-pushing, and never
  commit credentials.
- Minimum organization checks: `--check-docs`, `--check-catalogs`, focused
  organization tests, and `git diff --check`. Numerical changes additionally
  require the relevant core, runner, SST, and evidence gates, with skipped or
  unavailable tests named in the delivery report.
