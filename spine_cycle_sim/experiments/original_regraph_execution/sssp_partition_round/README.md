# Four-Partition Resident-Round Extension

`preparation.py` selects and records an induced real topology. `study.py`
uses the preceding real-round study's hash-frozen executable and author probe;
it does not rebuild or change numerical code. `analysis.py` checks complete
states/traffic, partition coverage, registration order and warm latency
sensitivity. The outer process-tree watchdog also covers Python preparation.

This is a diagnostic one-round control, not convergence, FPGA calibration,
strict resource matching or reproduction of original-paper performance.

`contract.py` binds declarations to actual raw command arguments and budgets.
`layout_audit.py` derives PMA work and a serial-control lower bound from the
captured CSR, including the routed dummy source-0 reservation. It does not
measure exclusive runtime stalls. `history.py` preserves unsuccessful attempts
and checks numerical equality to the preceding pass before delivery.

The outer watchdog tracks observed nested sessions through Linux pidfds.
It is sampled process accounting, not cgroup containment; a fork/reparent
between samples remains a limitation.
