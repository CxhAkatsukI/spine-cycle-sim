# Pre-Extraction Baseline Issues

The first 14-case exploratory matrix ran the unchanged numerical source at
`abe4c3e`, using plugin SHA-256
`5ff6b53fae61c87b896c76d45148b61b6b9357bf38576ff4e2f8f442868e97c7`.
Eight cases passed and six runners rejected their outputs. Nothing here was
introduced by extracting SST or Spine code. These are fixture-specific
observations, not evidence that all datasets or a frozen figure fail.

| Case | Observed reason | Treatment |
| --- | --- | --- |
| FullPR, StandardMem | Default 1M-cycle limit stops before the first fallback setup finishes | Increase only the declared cycle budget to 12M; keep all three iterations and correctness gates |
| FullPR, direct DRAMSim3 | Same insufficient cycle budget | Same budget change, separate memory transport |
| Warm ResPR | Both rank oracles and frontier check pass, but active-edge ledger fails | Keep rejected; investigate iteration-level edge aggregation and reference scope separately |
| CC zero-net | Label oracles pass; frontier and active-edge reference checks fail | Keep rejected; trace the zero-net initial frontier and device scan before accepting this path |
| Legacy carry fixture | Graph values pass; fixture coverage and maintenance accounting disagree | Keep rejected; do not update hardcoded expectations inside a numerical refactor |
| Owner carry maintenance | C++ result succeeds; generic wrapper requires `candidate10_one_pass` while profile/result say `candidate10_refactor31_segmented_exact` | Keep wrapper rejection; profile-aware admission is a separate runner fix |

The bounded FullPR follow-up on the same original plugin passes at 9,595,069
cycles with 2,248 accepted/completed requests. Its large setup cost is an
existing profile assumption, not a new measured hardware latency.

The [v1 contract](../../../configs/experiments/sst_spine_component_refactor_v1.json)
and `results/sst_spine_component_refactor_v1/before` preserve the first attempt.
The [v2 contract](../../../configs/experiments/sst_spine_component_refactor_v2.json)
was frozen before extraction. It requires ten positive cases and explicitly
records four known diagnostic rejections. A timeout, crash, different exit
code, changed signature, or changed result field fails that regression.
The comparison report counts positive admissions and diagnostic rejections
separately. An unchanged failure is never relabeled as a correctness pass.

These numerical/admission issues remain open after a source-only extraction.
They must not enter a publication-matching fit as accepted measurements.
