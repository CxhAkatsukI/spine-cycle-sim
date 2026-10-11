# Production Adapter AXI Probe

## Decision

The complete generated production RTL confirms a concrete input-path
inefficiency: eight logical 8-byte row loads become eight independent
64-byte AXI reads of the same aligned memory line. The existing local row
prefetch is not a single cache-line fetch. The skip-empty helper reduces
sparse-row control time, but does not eliminate these repeated row reads or
the occupied-source helper serialization.

This is an **RTL diagnostic with synthetic memory**, not FPGA timing, a
hardware-only bottleneck attribution, or an original-A4 performance match.
No production HLS, simulator timing, profile, default SST plugin, paper or
figure is changed by this checkpoint.

## Read And Review

- [Concise paired results](evidence/results.json): all twelve cases per arm.
- [Sealed raw evidence index](evidence/verification.json) and
  [portable raw archive](evidence/raw_adapter_axi.tar.gz): complete XOs,
  extracted RTL, bench, pinned runner sources, commands and transcripts.
- [Regression record](evidence/checks.json) and
  [regression logs and test-source snapshots](evidence/checks.tar.gz).
- Code owner: `spine_cycle_sim/experiments/sharded_k4_stages/adapter_axi/`.
  `study.py` executes; `analysis.py` validates AXI conservation; `delivery.py`
  rechecks and packages. The full-top bench is
  `cpp/tests/routed_regraph/adapter_axi_tb.sv`.
- Tests: `tests/test_sharded_k4_adapter_axi.py` and
  `tests/test_sharded_k4_adapter_axi_package.py`.

## Exact Versions

The previous arm is the adapter that actually entered the combined SSSP
route, not a similarly named earlier XO. The runner requires its exact
path and SHA-256 to occur in the frozen route manifest and command.

| Arm | SHA-256 of complete XO | Evidence boundary |
| --- | --- | --- |
| Previous combined, safe index | `93aa6b76e441eda51ffc0a9bb25c1411cfab2be2bf18326371558a0cefb1863a` | Previously routed and board-tested; this probe executes extracted RTL |
| Skip-empty production candidate | `4bae8791463a71f8b02ccad870d0178b2268cea8cfa6173c480e8a596a24417a` | Compiled production XO; not routed or board-admitted |

Both enable weighted/sharded PMA, one shared adapter AXI master, row
prefetch and stop-after-last. Only the candidate enables skip-empty.
Complete kernel ABIs match; neither defines the test-only COSIM depth flag.

## Frozen Matrix And Results

Both arms pass all twelve trials. They preserve every packet bit and
keep/strb/last sideband, hold output stable under backpressure, issue no
writes, and retire every AXI request/beat before completion. The parser
independently checks the predeclared matrix, responses, ordered timelines,
burst bounds, packet count and byte/beat/request conservation.

Here `V` is the number of sources; `segments` is the count of occupied
16-slot segments per nonempty row. Occupancy is all, last-only, first-only,
or every seventh source. `L` is synthetic AR-to-response eligibility delay;
the first accepted R beat is later than AR + L. `stall` holds the sink
not-ready for the first indicated invocation cycles. Cycles span first
`ap_start` high to `ap_done`, not AXI-Lite setup or host launch.

| Trial | V | Occupancy | Segments | L | Stall | Previous cycles | Candidate cycles | Row reads, both | PMA reads, both |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 | all | 1 | 1 | 0 | 2 | 2 | 0 | 0 |
| 1 | 1 | all | 1 | 1 | 0 | 227 | 229 | 2 | 1 |
| 2 | 8 | all | 1 | 1 | 0 | 787 | 796 | 9 | 8 |
| 3 | 9 | all | 1 | 1 | 0 | 939 | 950 | 10 | 9 |
| 4 | 17 | all | 1 | 1 | 0 | 1,651 | 1,671 | 18 | 17 |
| 5 | 17 | all | 1 | 64 | 0 | 1,735 | 1,755 | 18 | 17 |
| 6 | 17 | all | 1 | 128 | 0 | 3,079 | 3,099 | 18 | 17 |
| 7 | 17 | all | 3 | 64 | 0 | 1,803 | 1,823 | 18 | 51 |
| 8 | 17 | last-only | 1 | 64 | 0 | 1,639 | 459 | 18 | 1 |
| 9 | 17 | first-only | 1 | 64 | 0 | 246 | 248 | 9 | 1 |
| 10 | 17 | every seventh | 1 | 64 | 0 | 1,420 | 537 | 17 | 3 |
| 11 | 17 | all | 1 | 64 | 1,000 | 2,410 | 2,427 | 18 | 17 |

Every request in these executed cases is one 64-byte beat, including row
reads. Thus trial 5 transfers 1,152 row bytes for 136 logical row bytes.
Those row requests touch only three unique cache lines; a complete
eight-row block repeats its line eight times. The separate final-row
extent load explains why row reads can exceed V. Stop-after-last still
prefetches some rows beyond the first live source (trial 9).

The all-nonempty candidate is slightly slower, so skip-empty is not a
general occupied-path speedup. The 3.57x local last-only improvement is
specific to trial 8; it is not assigned to a real graph or the complete
accelerator. Trial 11 exercises actual output backpressure, not a stall
that expires before the first possible packet.

## Limits And Next Gate

The ordered memory responder accepts AR immediately, has configurable
response eligibility, and supplies up to one R beat per clock. It models
neither HBM banks/refresh nor AXI interconnect contention. A 10-ns testbench
clock is used to count RTL clocks; these values are not rescaled into
150-MHz measured FPGA time. Each trial resets the entire adapter, so this
does not establish repeated invocation behavior without reset. Downstream
ReGraph is replaced by a checked sink.

The next HLS candidate should explicitly load a complete row cache line
once and unpack its rows, while retaining the charged extent load, bounded
partial-block reads, PMA layout and update-maintenance costs. Changing the
row pointer width may affect the ABI and host padding contract; it must
pass those gates explicitly. Then repeat functional/RTL/synthesis checks,
route and paired board checks, and synchronize a separate model candidate.
Do not make the simulator faster while leaving this generated hardware
input path unchanged.

At this checkpoint route admission is still below the unchanged
40-GiB tree budget + 16-GiB reserve. No new xclbin has been produced and no
new board timing or A4/K4 comparison is admitted.

## Reproduction And Development History

From the simulator root, with the proprietary Vivado installation available:

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.adapter_axi.study \
  --root "$PWD" \
  --previous /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/ablations_safe_index/combined/adapter.hw.xo \
  --candidate /data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/production-v2/adapter.hw.xo \
  --route-manifest /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/route_combined_sssp/manifest.json \
  --output /data/chuxiao/experiments/fresh_adapter_axi \
  --vivado-bin /data/yxx/tools/xilinx/Vivado/2024.1/bin

python3 -m unittest discover -s tests -p 'test_sharded_k4_adapter_axi*.py'
```

Each vendor step has a 120-second timeout, 4-GiB aggregate tree RSS budget
and live 16-GiB reserve; the two arms execute serially. No timing constants
are fitted or accepted from the stored summary without parsing raw logs.
The archive can be moved: extract it and call `delivery.recheck()` on its
`accepted/` directory to revalidate without the original external paths or
installed vendor tools. Running RTL still requires the tools; their launcher
hashes are recorded, not their installation binaries.

Accepted execution is `attempt-v5`. The archive separately retains:

- `attempt-v1`: incorrect bench start detection (`ap_start && ap_idle`),
  rejected despite the simulator process returning zero; not an HLS fault.
- `attempt-v2`: insufficient sink stall to exercise backpressure.
- `attempt-v3`: corrected stall and output-stability check.
- `attempt-v4`: added complete-XO snapshots and packaging.

Attempts v1--v4 used the earlier non-safe-index `combined` XO, SHA-256
`a401feaa7bcb1cde928c70c53dc8262cadaeaa6da448181f46952f132bca431e`.
Their results are not assigned to the routed version. Version review found
the distinction before acceptance; v5 adds mandatory route-manifest binding
and reruns the entire matrix. Earlier manifests are preserved, not repaired.

## Verification Scope

All 265 selected `test_sharded_k4*.py` tests pass, including 19 focused
AXI/parser/portable-package tests. The monitored regression took 65.67
seconds, peaked at 2,042,988 KiB sampled aggregate RSS and retained at least
49.78 GiB available memory. Fifteen repository-organization tests and both
document/catalog checks also pass. Source, XO, extracted RTL, route identity,
raw transcript, result and watchdog mutations are rejected by focused tests.

No numerical C++ or production HLS source changed, so this checkpoint does
not report a new core build, HLS synthesis, route, board run or published
performance reproduction. The protected default plugin and user's separate
calibration worktree edits retain their earlier hashes and remain outside
this change.
