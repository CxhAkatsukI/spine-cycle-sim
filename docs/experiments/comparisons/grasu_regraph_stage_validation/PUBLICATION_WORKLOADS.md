# Publication Input And Event Boundaries

## Decision

The complete AU, SU and WK temporal candidates now have independently checked,
repeatable event/edge counts. A common post-hoc arithmetic expression agrees
with the denominator implied by GraSU Table 4 on all three graphs. **Neither
finding recovers the original update sequence or establishes a speed match.**
The missing original converter, operation types and aggregation boundary remain
explicit admission requirements; they cannot be replaced with a fitted factor.

Use [current stage status](README.md) for G/A/A4/B/C. This report does not alter
the simulator, FPGA results, paper or figure package. G-source16 functional and
finite-resource controls remain accepted within their existing boundaries.

## Complete Trace Controls

The [fixed contract](../../../../configs/experiments/grasu_publication_workload_admission_v1.json)
declares three complete inputs, two orderings, ten equal-count batches and,
for timestamp order, ten equal-timestamp-span batches. It retains raw-event
base positions when excluding self-loops from success counts. It does not
silently remove loops or duplicates before choosing the base cut.

| Input | All raw events | Self-loop events | Complete unique edges, including loops | Complete unique nonself edges |
| --- | ---: | ---: | ---: | ---: |
| AU | 964,437 | 237,776 | 596,933 | 544,621 |
| SU | 1,443,339 | 334,600 | 924,886 | 854,377 |
| WK | 7,833,140 | 1,732,602 | 3,309,592 | 3,130,742 |

The files contain 4,100 / 17,027 / 563,579 adjacent timestamp inversions.
File order is therefore not a substitute for chronological order. Chronological
controls use `(timestamp, original event position)` to make ties deterministic.
No reciprocal expansion, vertex compaction or synthetic weights are applied.

The declared candidate base cuts are 590,000 / 920,000 / 3,310,000 **raw events**,
not recovered original initial graphs. For these cuts, the independent
simple-graph insertion oracle finds:

| Input | Remaining raw events | New edges: file order | New edges: timestamp order | New nonself edges: file / timestamp |
| --- | ---: | ---: | ---: | ---: |
| AU | 374,437 | 176,001 | 214,175 | 153,774 / 191,151 |
| SU | 523,339 | 269,764 | 325,232 | 238,259 / 294,273 |
| WK | 4,523,140 | 2,118,305 | 1,922,809 | 1,988,390 / 1,828,946 |

These are controlled insertion interpretations of contact events, not claims
about the author's insertion/deletion stream. A full-file unique edge set is
also not necessarily a valid initial temporal graph. Counts for every batch,
base-cut sensitivity and all repetitions are in
[the complete result](publication_workload_counts.json).

## What Explains Table 4's Numerator?

If Table 4's printed time and rate describe one aggregate event window, their
product implies a count. Decimal arithmetic propagates half a printed unit
of rounding in both values instead of comparing rounded central values only.

| Input | Table time (s) | Table rate (M/s) | Implied count, central | Allowed integer interval | Exploratory residual count |
| --- | ---: | ---: | ---: | ---: | ---: |
| AU | 0.00068 | 190.77 | 129,723.6 | 128,767--130,680 | 129,728 |
| SU | 0.00125 | 147.08 | 183,850.0 | 183,109--184,591 | 183,853 |
| WK | 0.01375 | 202.97 | 2,790,837.5 | 2,789,754--2,791,921 | 2,790,946 |

None of the preceding raw-prefix insertion counts lies in its implied
interval. Moving the raw base cut over its two-decimal-million rounding range
does not resolve the retained-loop insertion discrepancy either. The report
does not assume that a product of separately averaged table values must equal
the total count: the table's reduction rule is still unknown.

The exploratory residual is:

```text
all raw events - all self-loop events - full-trace unique edges including loops
```

All three residuals fall in the printed intervals. This expression was found
**after** the initial counts, not predeclared as a validation oracle. The first
count-only run is preserved; a second complete repeated run freezes the
additional analysis and reproduces the same raw counts exactly. That second
execution is a reproducibility check, not an independent hypothesis holdout.

Crucially, this expression subtracts a loop-inclusive unique set from
nonself events. It is not simply the number of new nonself edges or a proven
successful-update sequence. The coincidence suggests a common preprocessing
or accounting convention to investigate; it does not justify generating
arbitrary operations with that count. The author artifact loads a preconverted
`V, initial_count, update_count` file and insert/delete records, but does not
supply the temporal converter. We still need that converter or actual converted
inputs and the original aggregation rule before comparing rates.

## Source Event Windows

Pinned GraSU revision: `e95da256be9e7f2361449323b6fe0abf98c1b152`.
[Its host](https://github.com/qgwang-hust/GraSU/blob/e95da256be9e7f2361449323b6fe0abf98c1b152/GraSU/GraSU/src/host.cpp#L267)
waits for all nine kernels and computes earliest OpenCL command start to
latest command end. Its printed numerator is `update_edge_size`, not an
observed successful-mutation counter. Host preparation, upload, readback and
host merge are outside that window. The original cache kernel's preload and
writeback are inside its command. GraSU Section 6.1 explicitly says experiments
use 200 MHz; Table 3's maximal synthesized frequencies are not the run clocks.
The source16/paper8 geometry difference remains unresolved for timing.

Pinned ReGraph revision: `365456826cef495285383d939907f847e05ad74b`.
[Its host](https://github.com/Xtra-Computing/ReGraph/blob/365456826cef495285383d939907f847e05ad74b/host/host.cpp#L159)
starts a host wall timer **after** enqueuing the Little and Big tasks, then
finishes all queues. The final throughput uses that wall duration. A separate
max-of-summed-kernel-event duration is calculated but not used in the final
print. Work may execute before the timer starts; without actual profiling
logs its extent cannot be quantified. This source observation is not proof
that the paper used exactly the same timing routine.

ReGraph Table IV reports graph-selected best/system combinations; the public
11L+3B example is not automatically either. The
[scheduler](https://github.com/Xtra-Computing/ReGraph/blob/365456826cef495285383d939907f847e05ad74b/host/preprocess/partition_schedule.cpp#L11)
leaves top-level topology/partition selection as a TODO and accepts `numD`
from the host. The independent mixed control's `numD=1` remains explicit.

Alternative paper anchors have their own boundaries. Original ReGraph Figure
9 reports single-Little/Big PR time per eight partitions on PK/HD/WP/G23,
not AM. Figure 10 includes AM and fixed pipeline combinations at 210 MHz;
the corresponding dense/sparse cut and original event window still need
admission. Do not transfer Figure 10's normalized clock to Table IV silently,
or tune the partition cut/model to an observed paper bar. Recover the exact
curve/control and preprocessing before declaring a numerical match.

## Reproduce And Verify

```bash
python3 scripts/audit_publication_workloads.py \
  --source-root /data/feiyang/Graph_Datasets \
  --out results/upstream_stage_controls/reproduce_publication_counts
python3 -m unittest discover -s tests -p test_publication_workload_admission.py
```

Use a fresh output directory. The source-root path is machine-local; filenames
and compressed SHA-256 identities are portable in the contract. The tool uses
Python's standard library and disk-backed SQLite, not a new simulation model.
Preparation, ordered count analysis, exploratory denominator analysis and
bounded execution have separate owners in
`spine_cycle_sim/experiments/publication_admission/`; the CLI is thin.

Accepted collection: `publication_workload_counts_final_v2`; the preceding
`publication_workload_counts_final_v1` remains a count-only checkpoint.
Both performed six sequential subprocesses with 4-GiB address-space limits,
16-GiB additional memory reserve and 900-second per-process timeouts. Database
scratch files are removed only after a successful complete collection. All
source identities are checked before/after ingestion; raw/decompressed hashes,
per-batch counts, code identities, SQLite/Python versions and resource logs
are retained. Output and input identities are not inferred from filenames.
The accepted run took 206.4 seconds of summed subprocess wall time and peaked
at 165,176 KiB individual-process RSS. Sixteen focused new tests and 102 related
Python tests pass; fifteen C++ tests pass in the unchanged accepted G build.

[Raw package](raw_publication_workload_counts.tar.gz) contains both collections,
the code, contract and tests; external copyrighted papers and large input
archives are not redistributed. [Verification](publication_workload_verification.json)
records package identities, tests and preservation checks. This work does not
rerun the FPGA matrix or claim new calibrated device cycles.

Sources: [GraSU paper](https://doi.org/10.1145/3431920.3439288),
[ReGraph camera-ready](https://soldierchen.github.io/assets/pdf/regraph.pdf).
Inspected PDF SHA-256 identities are recorded in the verification; paper
table values are manually transcribed anchors, not automatically extracted
or verified by the input-count runner.
