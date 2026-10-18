# Original GraSU Hardware Control

## Scope

This independent build preserves the author's five kernel/header files at
`e95da256be9e7f2361449323b6fe0abf98c1b152`. It is not the older integration
bitstream: that bitstream uses modified cache and memory interfaces. Nor is
this build a reproduction of the U250/200-MHz/8-slot published experiment.
The present control ports the unmodified 16-slot source to U55C at 150 MHz.

The source topology is four `bin_search`, one `dispatch`, two
`process_cache` and two `process_ddr` instances. All 46 AXI master interfaces
and eight 96-bit stream connections are retained. The cache capacity remains
131,072 segments per half, implemented by the author's URAM source. The
explicit four-HBM-bank and SLR mapping is a same-platform mapping decision,
not the author's original physical implementation. If this topology cannot
link or fit the platform, retain that failure; do not quietly compact ports
or shrink the cache and call the result original G.

## Ownership And Gates

`spine_cycle_sim/experiments/upstream_controls/grasu/hardware/` owns:

- `configuration.py`: pinned source hashes, topology, commands and budgets.
- `preparation.py`: clean-revision validation and relocatable source packet.
- `gates.py`: canonical exported ABI and HLS part/clock checks.
- `study.py`: tool/environment freezing, bounded compilation and linking.
- `__main__.py`: prepare/build CLI; neither command programs an FPGA.

The source packet is byte-exact and rejects altered, extra or symbolic files.
The runner requires a finite 40-GiB cgroup, at most 36-GiB memory.high, zero
swap, group OOM kill, and at least 160 GiB free disk. Atomic memory admission
reserves each peer's complete finite limit plus 32 GiB system and 8 GiB
background headroom. Other builds do not need to exit when those budgets fit.
Each kernel compile has a two-hour limit; linking has a twelve-hour limit.

Successful compilation checks original argument order, nine/zero/one/four
memory masters for search/dispatch/cache/DDR, `ap_ctrl_chain`, and 96-bit
streams. HLS must target the exact U55C part at 150 MHz. These checks do not
prove integrated RTL correctness or final routed timing. A completed link
reports `ORIGINAL_G_LINK_PASS_AWAITING_TIMING_CORRECTNESS_AND_BOARD`.
Board, publication-match and final-figure claim flags remain false.

## Reproduction

Prepare from a clean, pinned author checkout in the simulator worktree:

```bash
python3 -m spine_cycle_sim.experiments.upstream_controls.grasu.hardware prepare \
  --root /absolute/simulator-worktree \
  --upstream /absolute/clean-author-grasu \
  --packet /absolute/fresh-original-g-packet
```

Transfer that packet and a committed, frozen runner to the high-memory host.
Run the following in a bounded user service with `MemoryMax=40G`,
`MemoryHigh=36G`, `MemorySwapMax=0`, `OOMPolicy=kill`, finite task/runtime
limits and two Vivado synthesis/implementation jobs (set by the command).
Verify the resulting `memory.oom.group` is `1`; the remote systemd version
does not recognize the newer `MemoryOOMGroup` property:

```bash
python3 -m spine_cycle_sim.experiments.upstream_controls.grasu.hardware build \
  --packet /data/chuxiao/campaign/original-g-packet \
  --output /data/chuxiao/campaign/fresh-original-g-build \
  --environment-root /data/chuxiao/campaign/production-inputs-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /absolute/reviewed-u55c-platform/platform.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1
```

The environment root supplies the separately pinned GCC thread-compatibility
header. Only the host-tool compatibility define is passed; no GraSU geometry,
cache or compact-port define is injected. Outputs retain source/tool/runner
pins, exact commands, preflight, step logs, resource observations, HLS/ABI
checks and any failure. Existing output directories are never overwritten.

The eight focused tests cover topology, source/packet drift, ABI and clock
rejection, relocation and stopping before compilation on an invalid packet.
They are synthetic unit tests, not hardware evidence. After linking, strict
final timing, integrated correctness, original-state host bindings and a
matched update-only FPGA matrix remain required. Existing decomposed source
controls do not satisfy those board gates.

## Deployed Build And Host Prerequisite

The high-memory host `10.129.161.241:23333` runs the frozen `cb09a9d` runner
in `spine-original-g-route-20261018-v1.service`, invocation
`b204ce4f58414ae08ed0c760658f4a45`. The code-only archive SHA-256 is
`d7463bc132668076ee8bf1d2e6934c6b19b48b9a156f1c1ce9e7a5b4760b4fec`.
Inputs and output are respectively
`/data/chuxiao/baseline_hardware_validation_20261017/original-g-source-packet-v1`
and the sibling `original-g-source-route-v1`. At the 09:42 UTC checkpoint
on October 18 the service is waiting for an unbounded peer's budget to be
resolved; it has not compiled a kernel or produced FPGA evidence. Four
already-admitted bounded production links continue independently.

The [standalone board-host prerequisite](board_host/README.md) now compiles
the real-XRT Release binary and independently replays all eight author-host
inputs in Release and UBSan builds. These passes do not waive the route,
strict clock/timing, actual-board correctness or matched-performance gates.
