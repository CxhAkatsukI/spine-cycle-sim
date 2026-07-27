# Candidate10 Figure Data

This directory is populated only from correctness-gated experiment evidence.
The TeX entry point is `../candidate10_evaluation_figures.tex`.

From the repository root, build the six-page figure pack with:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir=/tmp/candidate10-paper \
  docs/paper/candidate10_evaluation_figures.tex
```

Expected CSV interfaces:

- `correctness_coverage.csv`
- `e2e_by_dataset.csv`
- `e2e_by_algorithm.csv`
- `e2e_speedup_by_dataset_algorithm.csv`
- `differential_by_scenario.csv`
- `update_throughput.csv`
- `e2e_by_batch.csv`
- `small_batch_by_algorithm.csv`
- `memory_by_algorithm.csv`
- `physical_memory_by_algorithm.csv`
- `dense_batch.csv`
- `hbm_energy_by_algorithm.csv`
- `ppa_summary.csv`

Missing files intentionally render as explicit evidence-gate placeholders.
Compact real slices and unsliced datasets must never be mixed in one aggregate.
