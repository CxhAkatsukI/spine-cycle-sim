# Original ReGraph Host Inputs

This package executes pinned author-host graph preparation, not a simulator
or FPGA timing experiment. Its inputs feed the separately owned original-R
cycle components; it does not replace production SST or G+R execution.

| Owner | Responsibility |
| --- | --- |
| `preparation.py` | Deterministic neighboring fixtures, safe loader admission, real-header compile command |
| `study.py` | Fixed matrix, source/input identities, bounded execution and repetitions |
| `analysis.py` | Typed work, partition/task scheduling, extent and capture-hash admission |
| `instrumentation.py` | Independent UBSan builds and complete capture equality |
| `delivery.py` | Recheck raw evidence and package metadata/logs without large graph copies |
| `cpp/tests/publication_sources/regraph_layout_*` | Original-host probe, full-edge oracle, binary capture and mapping check |

The CLI is `scripts/run_original_regraph_inputs.py`; the fixed contract is
`configs/experiments/original_regraph_inputs_v1.json`. Read the
[study results](../../../docs/experiments/comparisons/grasu_regraph_stage_validation/ORIGINAL_HOST_INPUTS.md)
and [implementation contract](../../../docs/implementation/grasu_regraph/original_regraph_inputs.md)
before changing this boundary. Reports deliberately leave device cycles and
publication-rate errors null. Large captures are indexed for reproduction;
they are not copied into Git or the small raw-log archive.
