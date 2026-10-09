# Original Big Memory/Frontend Checkpoint

This checkpoint extends the independent Big family through source requests,
finite AXI service, the original single-last-cacheline wrapper policy, response
broadcast/routing and PR Scatter. It stops before the
[previously admitted Big routing/Gather path](BIG_ROUTING_GATHER.md).
See [component ownership and assumptions](../../../implementation/grasu_regraph/original_regraph_big_frontend.md).

## Accepted Results

Authoritative run: `results/upstream_stage_controls/big_frontend_final_v2`.
All 36 bounded steps pass, including original-source UBSan, model UBSan,
repetitions, malformed captures and legacy regressions. The original capture
is 167,960 bytes, SHA-256
`df58d586033c3932edfd1e39d5bab9c7c362b73a452e85f518bde792a9140220`.
Complete comparison checks 1,796 requests including ends, 28,736 response
property words and 4,240 destination/value words, over six source fixtures.

| Finite model case | Predicted cycles | Actual 64-byte reads | Wrapper cache hits |
| --- | ---: | ---: | ---: |
| Sorted source crossings | 1,907 | 412 | 99 |
| Reverse registration | 1,907 | 412 | 99 |
| Reused partition | 1,907 | 412 | 99 |
| Only source line zero | 96 | 1 | 0 |
| Duplicated cachelines | 696 | 33 | 224 |
| Gapped source addresses | 1,265 | 127 | 380 |
| Dummy-only padding | 82 | 1 | 0 |
| Offset and source flags | 1,271 | 255 | 258 |
| Memory latency 128 | 3,635 | 412 | 99 |
| One outstanding burst | 28,452 | 412 | 99 |
| One live wrapper slot | 29,875 | 412 | 99 |
| Depth-one queues, delayed slow sink | 15,261 | 412 | 99 |

The table's reads are **source-property** reads, not edge reads. For example,
the duplicated-cacheline case has 257 logical normal requests but only 33
source reads: 224 responses reuse the wrapper's last cacheline. The sorted
case reads 26,368 source bytes plus 4,096 edge bytes. This distinction avoids
charging duplicate lane requests as separate HBM reads. It is a conserved
model ledger implementing the explicit source cache policy, not a measured
original-board transaction count.

Twelve CTest tests and 124 focused Python tests pass. The main study's bounded
steps take about 168 seconds in aggregate; maximum individual-process RSS is
689,636 KiB, not a simultaneous-tree sum. All five old component outputs,
eight complete-A4 graph rows and all 32 A4 state replicas stay exact. The
complete old Big Gather/source comparison also stays exact. The original
Spine/G+R/SST numerical bodies are unchanged; their earlier SST matrix is not
rerun for this isolated extension.

Deliverables: [results](big_frontend_results.json),
[verification](big_frontend_verification.json),
[preservation checks](big_frontend_preservation.json) and
[raw archive](raw_big_frontend.tar.gz). The archive has 135 indexed members,
258,325 bytes, SHA-256
`1728ab3a5e24c9a5541ba857bdb60fea836de41b0e028d7bc315e07fd9df78cf`.
Every archived member was independently hashed after packaging.

Unsuccessful attempts are retained. `big_frontend_preflight_v1` exposed a
descending-source fixture in the duplicated-line case, corrected by ordering
the offsets within each repeated line; the source-sorted admission gate was
not weakened. `preflight_v2` caught an unnecessary response copy under
`-Werror`; `preflight_v3` passes. `big_frontend_final_v1` fails probe compilation
because the author's end flag is a plain bool, not an `ap_uint`; the new
capture serializer was corrected before the accepted fresh final run.

## Fixed Evidence Gates

Six independent author-source fixtures cover source line zero, source-sorted
cacheline crossings, duplicated cachelines, large source-address gaps,
dummy-only padding, and flag bits with a nonzero destination offset. The
source probe directly calls unmodified `genMemRequest`, `sendCachelineRequest`,
`bigKernelReadMemory`, `receiveResponses` and `accScatter` from the pinned
author checkout. Source and simulator do not share fixture/oracle code.

The complete binary capture contains request line/lane/end fields, every
wrapper response property and every Scatter destination/value pair. The
unused initial lane and end address are canonicalized; meaningful addresses,
lane tags, values and flags are not changed. The model comparison checks all
captured fields, not only a final graph sum. The response observer snapshots
the existing FIFO head and records it only if that FIFO pops on the step;
it adds no queue, latency or backpressure.

Twelve model rows cover reversal, partition reuse, all six source geometries,
double memory latency, one outstanding AXI request, one live wrapper slot,
and depth-one queues with delayed slow consumption. Every row checks an
independent source-property oracle, exact generated requests, logical request
versus cache-hit/miss counts, physical read bytes, lane/lookup work, acknowledgements,
finite capacities and empty/conserved queues. Source and model repeat; the
source probe and both model executables also pass separate UBSan builds.

Eight internal rejection checks cover invalid allocation/capacity, unsorted
or out-of-domain sources, unknown acknowledgements and undrained restart.
Six damaged captures cover header, request, response, update, truncation and
excess bytes. They must fail rather than be silently repaired or excluded.

The frozen old five component outputs and all eight whole-A4 rows must remain
byte-exact, including four output replicas per row. The complete old Big
Gather/source comparison must also remain exact. No accepted earlier raw
package is regenerated or relabeled.

## Reproduce

Use the pinned source checkout in [the study guide](README.md), Vitis HLS
headers, GMP and G++. Python 3.11 runs the original generator. Every subprocess
is bounded; Release uses two build jobs, a 3-GiB address-space allowance,
128-MiB stack and a 16-GiB available-memory reserve. Outputs must be new paths.

```bash
python3 scripts/run_original_regraph_big_frontend_validation.py \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --baseline results/upstream_stage_controls/big_frontend_baseline_v1 \
  --out results/upstream_stage_controls/reproduce_big_frontend
python3 -m unittest discover -s tests -p test_original_regraph_big_frontend.py
```

The local pre-change baseline freezes 48 original-R files and five component
outputs at `69fcf23`. A fresh workspace can build that commit in a detached
worktree and capture those five executables with bounded resource records;
the delivered archive retains the exact local baseline. Reproduce the
[A4 whole-graph checkpoint](A4_GRAPH_EXECUTION.md) and
[Big Gather/source checkpoint](BIG_ROUTING_GATHER.md) first: these provide
the separate graph/state and complete original-Gather references.

The existing Big validation owner now includes separately named
`frontend_sources.py`, `frontend_study.py`, `frontend_analysis.py` and
`frontend_delivery.py`. The thin CLI does not contain experiment logic.
Delivery rechecks tested code/binaries/dependencies, raw model and original
captures, repeats, UBSan, old-result equality and all malformed controls.
No paper file is changed.

## Remaining Work

Connect this Big source path to the admitted omega/bank/merge and state path,
then execute the full author-host mixed Amazon schedule. The single-path
fixture's channel binding is not a complete 11+3 topology. Do not infer a
published throughput match from these predictions or from matching a total
system time. Original G, original-publication timing admission, matched A4/B
adapter overhead and C/host composition remain separate open milestones.
