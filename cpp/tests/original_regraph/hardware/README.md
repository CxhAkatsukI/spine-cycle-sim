# Original ReGraph Board-Control Host

This optional XRT host is separate from the simulator core and SST plugin.
It keeps the original device code unchanged and provides a reviewable path
to one fixed-point PR superstep (`arg=0`). No board execution is admitted yet.

| File | Responsibility |
| --- | --- |
| `model.hpp` | Strict admitted A4/mixed task input, independent CSR/task equality, named divisor binding, bounded allocations and full-line guards |
| `events.hpp` | Monotonic event validation and union/span, never the sum of overlapping kernels |
| `opencl.hpp` | Mandatory external board lease, fixed index/BDF, 32-bank XRT buffers and profiling queues |
| `device.hpp` | Explicit generated-A4 or 11-Little/3-Big kernel ABI, resident enqueue-to-completion window and all-replica checks |
| `control.cpp` | Thin offline/board CLI and explicit observations |
| `model_tests.cpp` | Fixed-point overflow, publication capacity, guards and overlapping-event tests without XRT |

The host supports exactly two board geometries: generated A4 (4 Little,
0 Big) and the reviewed example (11 Little, 3 Big). The Python board owner
requires matching source, ABI, routed topology and strict implemented-clock
timing before either can launch. This does not imply that the 11+3 prebuilt
can be used as four Little pipelines. Historical offline evidence still
describes its old host, not this source change.

`author_initial` reproduces the reviewed host's divisor-buffer binding;
`csr_degree` uploads actual CSR degrees. These controls are not interchangeable
and neither is, by itself, a publication-performance reproduction.

Publication allocation covers `max(aligned_vertices, published_vertices)`,
with a separate 16-word guard. Output starts at the guard sentinel; every
published word, unused tail and guard is checked. All four or fourteen source replicas,
the divisor and every resident task buffer are also read back unchanged.
The larger allocation is an explicit host safety repair, not unmodified-host
equivalence.

Resident timing starts before argument binding and the first kernel enqueue,
and stops after all lane, Apply and publication queues finish. It excludes
initial preparation, program load, transfers, profiling and readback. Those
must be separately measured before making a host-inclusive claim. Kernel
event union and span are retained separately from this wall interval.

For a portable offline validation, use
[the Python validation owner](../../../../spine_cycle_sim/experiments/original_regraph_execution/hardware/README.md).
It compiles Release and UBSan controls, checks the fixed 48-run matrix against
the independent frozen oracle and verifies fail-closed launch conditions,
including the external lease requirement for both board geometries.
There is no CMake/SST source change because these files are optional external
OpenCL test controls, not simulator components.

Do not run `board` manually or program the prebuilt merely because this host
compiled. Artifact source/ABI identity, implemented-clock timing, exclusive
board admission and an external timeout remain required hardware gates.
