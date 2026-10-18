# Original-R / K4 Arithmetic Control

This offline prerequisite defines an explicit candidate for the pending
adapter/K4 hardware comparison. It neither runs a board nor measures speed.
The production default remains unchanged.

| Module | Responsibility |
| --- | --- |
| `arithmetic.py` | Independent CSR gather and original fixed-point versus explicit binary32 payload arithmetic, with overflow/exact-gather/truncation bounds |
| `sources.py` | Pin the reviewed author UDF and clean production gather/apply source anchors; not compiled-code equivalence |
| `study.py` | Recheck all six admitted layouts and both divisor bindings under finite memory, preserving failures and false hardware claims |

Read the [arithmetic-control guide](../../../../../docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/original_regraph/arithmetic_control/README.md)
for formulas, scope, results and reproduction. The author output is an
integer property; the candidate comparison output is the floating-point
**source payload**, not the new rank state. Numeric equality does not imply
bitwise equality of integer words and float bit patterns.

Reject any input whose signed fixed-point intermediates overflow or whose
nonnegative integer gather exceeds binary32's exact-integer range. Zero
divisors produce zero payload in both controls. Output differences must remain
visible; the original truncation formula must not be silently replaced by the
candidate or by the production defaults (damping 0.85, base, dangling share).

```bash
python3 -m unittest discover -s tests -p 'test_original_regraph_arithmetic.py'
```
