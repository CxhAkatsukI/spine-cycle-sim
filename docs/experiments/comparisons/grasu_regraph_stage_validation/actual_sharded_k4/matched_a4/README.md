# Matched A4 And Actual K4 Controls

This collection separates algorithm admission from a later performance
comparison of four original-style Little frontends and the actual sharded-K4
adapter/compute path. It does not replace the frozen publication controls.

Start with the [weighted-SSSP correctness gate](sssp_control/README.md).
It admits arithmetic and complete resident one-round state only. A4/K4
performance, original-publication reproduction and new FPGA timing are not
admitted by that checkpoint.

The subsequent [real-topology resident-round control](sssp_real_round/README.md)
preserves author DBG/tasks, overlays the same SSSP problem on both paths, and
checks complete state/traffic under two explicit mock-memory services. Its
single-partition cycles are diagnostic; it is not a resource-matched speed
claim or an update-to-convergence comparison.

The production candidate's preceding hardware/model evidence remains in the
[initial-residency study](../model_sync/sst/input_residency/README.md).
Correcting that path's observed input migration does not establish the
independent A4 model's timing.
