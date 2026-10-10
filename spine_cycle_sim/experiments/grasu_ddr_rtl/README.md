# Original GraSU DDR RTL Control

This optional control synthesizes the pinned, unchanged `process_ddr` source
and executes that RTL in XSim against a finite, shared physical memory. It is
not part of the production simulator, an FPGA test, a complete G timing model,
or a reproduction of published throughput.

| Owner | Responsibility |
| --- | --- |
| `fixtures.py` | Post-search packets and independent sorted-set state oracle |
| `preparation.py` | Author source, baseline, tool-independent identities and HLS schedules |
| `study.py` | Bounded sequential tool/source/RTL execution and complete step order |
| `trace.py` | FIFO requests, minimum service latency, response credit, port routing and conservation |
| `analysis.py` | Complete source/RTL state, diagnostics and explicit mismatch status |
| `delivery.py` | Recheck raw evidence and package results without a publication-match claim |
| `cpp/tests/grasu_ddr_rtl/` | Source probe, kernel bench, shared bus and independent bus selftest |

Run through `scripts/run_original_grasu_ddr_rtl.py`. Use new baseline/output
paths with `--capture-baseline` for a new experiment; an existing baseline is
for checking preservation relative to its original checkout state. The
runner refuses output overwrite and preserves failed attempts. A missing
production plugin is recorded as null in a newly captured baseline; the
isolated RTL control itself does not require SST.

Exit zero means the complete experiment finished, not that every row passed:
inspect the explicit state-pass or state-mismatch status. Tool failure exits
nonzero. Expected illegal-bus rejection is checked separately from tool
crashes; a crash after a correct rejection is still not admitted.

The [study report](../../../docs/experiments/comparisons/grasu_regraph_stage_validation/GRASU_DDR_RTL.md)
owns results, boundaries, commands and the remaining G-stage work.
