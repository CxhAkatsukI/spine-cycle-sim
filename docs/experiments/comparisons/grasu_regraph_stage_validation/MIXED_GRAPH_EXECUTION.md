# Original Mixed Graph Execution

This checkpoint connects the artifact's **11 Little / 3 Big example** through
one complete original-host PageRank iteration. It uses the same admitted
Amazon and neighboring graph inputs as A4, with original DBG, task assignment,
PR initialization and argument zero. It is not a dynamic-update convergence
comparison, a reconstruction of the unknown graph-selected best topology,
or a publication-speed match.

## Allocation Finding

The source host allocates state rounded to 65,536 vertices. The Big path
publishes entire 524,288-vertex groups, including the tail. Inspecting original
`graph_preprocess.cpp` and `acc_apply.h` gives:

| Input | Original state words | Published words | Additional zero words | Unmodified host extent safe |
| --- | ---: | ---: | ---: | --- |
| Boundary ring | 196,608 | 589,824 | 393,216 | No |
| Skewed sources | 131,072 | 65,536 | 0 | Yes |
| Amazon | 786,432 | 1,114,112 | 327,680 | No |

This is a source-geometry incompatibility, not an observed crash on the
authors' board. The graph-specific deployed configuration or an unpublished
host fix could differ. It is not evidence that the already accepted A4 or
our ported FPGA matrix is wrong.

The executor rejects both unsafe original allocations. A separately labeled
**zero-extended state-tail control** then runs all three inputs. Only state
allocation grows, with zero-filled tail; source graph buffers and task captures
are unchanged. The publication work is not clipped to make timing smaller.
All 14 output replicas and their guard bytes are checked, including padding.

## Admitted Results

Authoritative run: `results/upstream_stage_controls/mixed_execution_final_v3`.
Status: `MIXED_FULL_GRAPH_PADDED_CONTROL_PASS_TIMING_PREDICTED`.

| Predeclared case | Predicted cycles |
| --- | ---: |
| Boundary ring | 173,917 |
| Boundary, reverse registration | 173,917 |
| Boundary, memory latency 128 | 325,180 |
| Boundary, one state parent credit | 2,547,323 |
| Skewed sources | 34,867 |
| Skewed, reverse registration | 34,867 |
| Amazon | 733,465 |
| Amazon, reverse registration | 733,465 |

Every row repeats. The independent CSR oracle checks every indexed pre-Apply
sum, every PR output word in all replicas, and unique/complete write-index
coverage. All registered FIFOs, private omega queues, cache requests and AXI
acknowledgements conserve work and remain bounded. Increased latency or
reduced parent credits increases cycles without changing any output word.

Amazon checks 1,114,112 pre-Apply words and 15,597,568 replica words. It reads
41,327,424 edge bytes, 3,457,024 Little-source bytes, 5,579,264 Big-source bytes
and 4,456,448 degree bytes; all 62,390,272 write bytes are acknowledged.
Big performs 327,476 logical requests: 87,176 actual 64-byte reads and 240,300
last-cacheline hits. Logical requests are not charged as distinct HBM reads.
Two successive Big groups execute with resident wrapper/bank state, and bank
clear/drain is checked at each group.

These are predictions under the [explicit implementation assumptions](../../../implementation/grasu_regraph/original_regraph_mixed_execution.md).
The 210-MHz clock is a declared model clock, not proof that a particular
publication table uses that event/frequency boundary. Neither an error versus
published throughput nor a new FPGA measurement is reported.

## Equivalence And Rejections

The pre-edit baseline freezes 60 existing original-R files and six component
executables. Only the build list and bounded Big merger entry are extended;
the old single-partition entry delegates with count one. All six old executable
outputs remain byte-identical. All eight previous complete-A4 rows preserve
their values, cycles, traffic, counters, lifecycles and 32 full replica captures.
Both complete Big Gather and frontend author-source comparisons remain exact.
Old Big references are read from verified archives, not historical absolute
runtime paths.

The indexer unit checks Little priority, Big progress while Little is absent,
finite output backpressure, registration reversal, empty restart and four
rejections. Whole-graph negative controls reject two unsafe original state
allocations plus corrupted header, task assignment, source, arithmetic, edge
value and truncation. Three independent UBSan graph runs preserve complete
states, cycles and ledgers without diagnostics.

All 13 CTest tests and 138 focused Python tests pass. The final study has 47
bounded steps, approximately 297 seconds of aggregate subprocess wall time,
and 689,448 KiB maximum individual-process RSS (not simultaneous tree RSS).
The [preservation record](mixed_preservation.json) embeds the supplementary
Python test/resource log and checks all 2,437 frozen files, 34 previous study
artifacts and the original SST plugin identity. None changed.

The preserved first preflight failed only because a negative test ended before
its invalid data became visible. The test now keeps the merge active with an
unfulfilled Big input; the rejection gate was not weakened. The second
preflight and full matrices pass. Earlier full runs `final_v1` and `final_v2`
are retained; final_v3 adds stricter raw-regression/package checks without
changing numerical components or results.

Deliverables: [results](mixed_results.json), [verification](mixed_verification.json),
[preservation](mixed_preservation.json), and [raw evidence](raw_mixed_execution.tar.gz).
Large complete-state and original-host captures are hash-indexed, not copied
into the archive; reproduce them from the pinned source/input checkpoint.
The archive contains 185 verified members, 87,542 bytes, SHA-256
`e6704991448c6043ce31447407c3f8bc7001ecfcb0bb74ad5bb2140892e5d58a`.
All 24 rejection stdout/stderr/resource logs are included; malformed input
copies are deliberately excluded.

## Reproduction

Start with [original-host input preparation](ORIGINAL_HOST_INPUTS.md), a clean
pinned author checkout and the unchanged canonical input contract. The
following uses a fresh host-input run and a pre-edit baseline extracted from
this checkpoint's raw archive:

```bash
mkdir -p results/reproduce_mixed_baseline
tar -xzf docs/experiments/comparisons/grasu_regraph_stage_validation/raw_mixed_execution.tar.gz \
  -C results/reproduce_mixed_baseline baseline
python3 scripts/run_original_regraph_mixed.py \
  --inputs results/upstream_stage_controls/reproduce_original_host_inputs \
  --baseline results/reproduce_mixed_baseline/baseline \
  --out results/upstream_stage_controls/reproduce_mixed_graph
python3 -m unittest discover -s tests -p test_original_regraph_mixed.py
```

Create the extraction destination before the `tar` command and verify the
archive SHA-256 in `mixed_verification.json`. The runner re-admits the host
captures against frozen values and uses unique outputs. Each subprocess has
a 3-GiB address-space limit, 128-MiB stack limit, 16-GiB memory reserve and a
bounded timeout; builds use two jobs. Regressions and graph cases run
sequentially. Simulator wall time is not device-cycle time.

## Remaining Study Work

- Admit graph-selected original topology, iteration/throughput denominator,
  event/frequency boundary and realistic memory timing before any approximately
  10% publication-speed claim for A.
- Implement original G finite search/URAM/update/writeback and the separately
  named source-16 versus paper-8 geometry controls; admit temporal workloads.
- Connect a PMA adapter to the same admitted A4 downstream, then measure B/A4
  differences with identical graph/state/resources and overlap accounting.
- Only then compose G, adapter+R and host orchestration C. A close system total
  cannot validate compensating stage errors.

The production SST/Spine/G+R numerical bodies and frozen paper evidence are
unchanged. Their previous SST matrix was not rerun for this independent
extension; it must be rerun when those production bodies change.
