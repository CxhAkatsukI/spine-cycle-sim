# Original G Board-Host Prerequisite

## Scope

This is the standalone host for the unmodified original-G kernel topology:
four search, one dispatch, two URAM-cache and two DDR-update CUs. It is not
the older integrated bitstream or an original-U250 performance reproduction.
No command in this preflight programs a board or reports device cycles.

The current Release command links `libxilinxopencl` directly, not the generic
OpenCL ICD loader, and freezes its resolved dependencies plus the dynamically
loaded PCIe core. This avoids silently selecting the NVIDIA loader installed
on the measurement host. The old v1 self-test below remains historical;
it does not establish this newer runtime-closure check.

The C++ owner `cpp/tests/publication_sources/grasu_board/` separates:

- `model.hpp`: bounded binary input, four physical PMA buffers and an
  independent sequential insert/delete oracle.
- `runtime.hpp`: checked XRT calls, four-bank allocations, device identity
  and externally held exclusive board lease.
- `execution.hpp`: original nine-CU bindings and concurrent launch, complete
  immutable/state/guard readback and individual event timestamps.
- `control.cpp`: self-test versus explicitly requested board entry point.

The Python owner
`spine_cycle_sim/experiments/upstream_controls/grasu/hardware/board/`
rechecks the frozen author-host captures before exporting inputs. Compiler
flags, headers, runner modules, inputs and binaries are hash-pinned. The
preflight has a four-GiB process-tree watchdog, a 32-GiB live-memory reserve
and ten-minute per-child timeout; the executed user service also has a
four-GiB cgroup, three-GiB memory.high, zero swap and group OOM kill.

## Input And Timing Contract

The input is a bounded little-endian `OGB1` packet, version 1, containing
vertex/segment/update counts followed by offsets, search heads, prepared
PMA, original-order mapped updates and the independently checked final PMA.
All three author-host executions (first, repeat, UBSan) are revalidated
before exporting each of the eight inputs. Their mapping, future-union
reservation, protocol, padding and complete-state checks must agree.

As in the author's host, search lanes receive every fourth update, all four
search metadata ports alias the lane's own table, the two DDR controllers
alias their four PMA arguments, and the cache buffers contain the full
131,072 hot segments per half. Empty allocations have defined backing and
all PMA padding is defined empty. Every buffer has guard storage. The
oracle checks both live-owner and stale-duplicate buffers, unused capacity
and guards, not only live edges.

The future board output distinguishes two resident-stage windows:

- `kernel_event_span_ns`: earliest START to latest END among all nine CUs;
  overlapping events are not summed.
- `resident_wall_ms`: immediately before argument binding through queue
  completion, including host enqueue/wait overhead.

Both exclude CPU preparation, programming, initial DMA and correctness
readback. They must not be compared as though they include the complete
resident-update-to-result readback boundary used by the new paired matrix.
No publication performance or integrated G+R claim follows from this host.

## Current Immutable Preflight

The valid replacement is `original-g-board-host-preflight-v4` under the local
campaign root. It completes all 21 child steps, including eight Release and
eight UBSan cases and both malformed-header rejections. Its report SHA-256 is
`c5fcccaf865c8d50cc5b0f74f4ea2dda53359a125fc927ae217915287c9d1ef6`.
Service `spine-original-g-board-host-preflight-20261018-v4.service`, invocation
`d2e111fd84964b96985283cb247e4d19`, exits zero with a 370913280-byte cgroup
peak. It is still host/model evidence, with no FPGA programming or timing.

Both `PYTHONPATH` and `--root` use the immutable `original-g-host-runner`
directory under that campaign root, exported from simulator `f50a185`.
Archive `original-g-host-immutable-runner-v1.tar.gz` has SHA-256
`c04fc546be55df0939f4294718894808eeb6c432fec4a5e77e85a2dfe6bb4e82`.
The snapshot was made read-only after generation; no imported runner is
pinned to the development checkout. Supply the exact reviewed v4 report
digest explicitly to a new board command. Earlier preflights remain intact.

## Historical Preflights

Raw output:
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/original-g-board-host-preflight-v1`.
The user-service invocation is `05c5f8f9ecbb4ab78fd90317f411cae0`.
Its `results.json` SHA-256 is
`a01fe60154dc976b398d1a1e9c0e0ce58e5287c5103bb521dd034565115d517a`.

Status: `ORIGINAL_G_BOARD_HOST_PREFLIGHT_PASS_NOT_BOARD_OR_TIMING`.
Eight cases pass in both the real-XRT-linked Release build and the separate
model-only UBSan build: empty graph, empty batch, insertion-only, full delete,
mixed reservation, hot skew, same-segment ordering and threshold ring.
The threshold input checks 8,390,784 physical slots including guards; its
updates reach all four paths (131,072 / 32 / 131,072 / 32). Both builds reject
an invalid packet header. All twenty child steps complete; maximum sampled
child-tree RSS is 229,720 KiB and service memory peak is 722,563,072 bytes.
Seven focused unit tests additionally cover malformed extents, corruption,
duplicate/absent updates, immutable baseline admission and input reuse.

The current runtime-closure preflight is the separate
`original-g-board-host-preflight-v3`, frozen at simulator `534ec1f`, service
invocation `e23f365e9a4648aba03f81a5b28397fe`. Its report SHA-256 is
`bee145c72883f4c0d9ec85ca0eccab207bfdebd1050d9a978d4645d7ae9cc701`.
All eight inputs pass in Release and UBSan, and both invalid-header checks
pass (21 child steps, sampled maximum 236668 KiB). The cgroup peak is
378617856 bytes. The direct Xilinx OpenCL link, resolved dependencies and
dynamic PCIe core are frozen. This remains a **host/model preflight**, not
an FPGA timing or correctness result. The intervening v2 service failed
before import because its detached worktree checkout had not finished; that
launch failure is retained and did not run an experiment.

The v3 report also pins imported Python modules from the development checkout.
Subsequent changes to three of those infrastructure files invalidated reuse:
the matched-G board waiter stopped before requesting a device. Its old PASS
is a historical host execution, not a currently valid board prerequisite.
Do not edit its pins or ignore the mismatch. Generate a new preflight with
both `PYTHONPATH` and `--root` pointing to the same immutable source snapshot.

Board input admission now accepts an explicitly reviewed report SHA-256;
omitting it retains the old reviewed digest, not automatic discovery. The
report schema, independent eight-case capture replay, runtime dependencies,
all source pins and negative checks remain mandatory. A new report's digest
must be recorded and supplied by its caller after review. The fixed author
baseline digest below cannot be overridden by this option. This avoids
embedding a new report's digest in a module that the report itself pins.

Six synthetic receipt tests cover explicit digests, both original/matched
prerequisites, changed source rejection and forwarding the same identities
through the board handoff; these do not program an FPGA:

```bash
python3 -m unittest discover -s tests -p test_grasu_preflight_identity.py
```

Reproduce without a board:

```bash
python3 -m spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board \
  --root /absolute/simulator-worktree \
  --baseline /absolute/grasu_host_final_v1 \
  --xrt /opt/xilinx/xrt \
  --output /absolute/fresh-original-g-host-preflight
```

The baseline report is frozen at SHA-256
`b548229594e31b4d78eefa2ec79502a97134fad35a274504c9089cadadd06048`.
The preflight is deliberately not a generic importer of arbitrary historical
results. A new baseline needs explicit review rather than a hash override.
The source-preserving link, strict routed timing and actual-board repetitions
remain open. The [parent package](../README.md#return-and-board-continuation)
now owns automatic return/admission and an explicit optional board continuation;
its implementation and synthetic tests are not a board pass. Do not manually
invoke the board entry on an unreviewed artifact just because self-tests pass.

## Independent Routed Gate

`hardware/topology.py` owns an additional pre-board check, separate from the
host oracle. `gates.inspect_routed` reads the extracted XRT metadata and
requires exactly nine chain-control CUs, all 46 declared HBM argument
bindings and eight exact two-endpoint AXIS pairs. Connected banks must be
enabled 512-MiB HBM regions. The full clock topology must remain 150-MHz
DATA, 500-MHz KERNEL and 450-MHz HBM; automatic downclock is rejected.
Exactly one final routed summary must have finite nonnegative setup, hold
and pulse-width slack, no failing endpoints and the explicit constraints-met
statement. Synthetic negative tests exercise missing/changed CUs, clocks,
bindings, stream endpoints and timing. They are not a routed-artifact pass.

This gate alone does not attest the remote service, source closure, host
oracle or board execution. Transport/admission must verify those separately
before invoking the board host; all performance/figure flags remain false.
