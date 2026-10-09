# Simulator Runtime Optimization

This collection records changes intended to reduce simulator wall time while
preserving modeled behavior. It is separate from FPGA timing calibration.

## Representative Investigations

- [R19 baseline](simulator_throughput_r19_baseline_20260728.md)
- [Direct transport](simulator_throughput_candidate24_direct_transport_20260728.md)
- [Event-driven ReGraph](simulator_throughput_candidate39_event_driven_regraph_20260729.md)
- [Payload ranges](simulator_throughput_candidate52_payload_ranges_20260729.md)
- [DRAM deadline host optimization](simulator_throughput_candidate59_dram_deadline_hostopt_20260729.md)
- [AXI response fast path](simulator_throughput_candidate81_axi_response_fastpath_20260729.md)

The numbered candidates are investigation identities, not a sequence that must
be applied to reproduce a current result. Their accompanying evidence remains
in the original `docs/evidence/` directories. Use the selected profile and
plugin identity to decide whether a change belongs to a reproduction.
