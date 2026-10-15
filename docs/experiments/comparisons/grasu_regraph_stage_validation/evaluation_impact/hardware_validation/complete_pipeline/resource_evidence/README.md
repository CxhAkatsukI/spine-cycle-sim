# Complete G Storage Screen

## Decision

The original placement cannot accommodate the new full-capacity cache and
four Little CUs: SLR0 requires 384 URAMs but contains only 320. The device
total, 768 of 960, hides that local conflict. Moving only `lksg_stream_4`
from SLR0 to SLR1 changes the requirements to 320 / 128 / 320 URAMs.

Vivado queries of both physical sites and the actual U55C platform hard
pblocks report 320 / 320 / 320 URAM sites. This admits a **storage-placement
screen only**, not complete resource fit. The shell, interconnect, LUT/FF/BRAM
capacity, congestion and routed timing remain to be checked. No cache is
removed, no capacity is reduced and the four-Little topology is unchanged.

| HLS estimate | Original SLR0 | Original SLR1 | Original SLR2 | Total |
| --- | ---: | ---: | ---: | ---: |
| LUT | 352613 | 211418 | 360684 | 924715 |
| FF | 223717 | 144919 | 261714 | 630350 |
| BRAM_18K | 532 | 298 | 302 | 1132 |
| URAM | 384 | 64 | 320 | 768 |

The eleven kernel reports cover all 22 configured CUs. These are summed HLS
estimates, not post-implementation utilization. After relocation SLR0/SLR1
LUT estimates are 313826 / 250205; SLR2 is unchanged.

## Retained Evidence

The [index](index.json) pins five portable archives, including their frozen
runners, reports, CSVs, source/configuration and raw tool output:

| Attempt | Result |
| --- | --- |
| `g-resource-query-v1` | Physical site query passes; 320 URAM per SLR |
| `g-platform-query-v1` | Retained 300-second timeout while loading/querying the platform; not a capacity failure |
| `g-platform-query-v2` | Same platform query passes with a 900-second bound; 365.629 seconds observed wall time |
| `g-resource-fit-v1` | Physical-site screen identifies original SLR0 conflict |
| `g-resource-fit-v2` | Actual platform hard-pblock screen confirms original conflict and relocated storage feasibility |

Vendor XSA/DCP files are indexed by path and SHA-256 but not redistributed.
The platform is `xilinx_u55c_gen3x16_xdma_3_202210_1`, with Vivado 2024.1.
The platform query uses an 8-GiB hard / 7-GiB high no-swap scope and retains
a 24-GiB system reserve plus other declared build/background budgets.

The raw root is
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.
No failed report, source tree or original configuration was rewritten.

## Reproduce

From the simulator repository root:

```bash
python3 -c 'from pathlib import Path; from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.resource_delivery import verify; verify(Path("docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/resource_evidence"))'
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.resource_probe --help
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.resource_fit --help
```

Use fresh output paths and bounded supervisors. The archived `results.json`
records exact query commands, inputs and finite timeouts. The fit runner
rederives every per-SLR sum from frozen connectivity and HLS XML, rather than
accepting a manually entered resource total. See the
[hardware guide](../hardware/README.md) for the separate link attempt.
