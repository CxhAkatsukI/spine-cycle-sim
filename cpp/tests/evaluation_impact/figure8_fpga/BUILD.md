# Portable Host Build Notes

These are host-only builds. Do not run either positional CLI without the board
runner's admission, exclusive lease and identity checks. `--help` is board-free.

## Repaired Build

The repaired host build is
`/data/chuxiao/checks/fig8-fpga-persistent-20261107-v9/build`.
It uses the same compiler flags and frozen images, but the current fixed-layout,
L10 bootstrap, bounded-arena and physical-schedule headers. The external
production host's maintenance-only active-buffer, direct-residency and sparse
scratch initialization and compact CPU-staging patches are pinned by SHA-256.
Scratch, owner and graph arenas use explicitly allocated, aligned host backing,
without zeroing or uploading the complete backing store. Required scratch
prefixes are initialized separately; metadata is uploaded once after descriptor
patching. Device capacities and all
required initialization are unchanged. No FPGA kernel changes
or routing are part of this repair.
Both hosts and their exact dependency sets are indexed in `build.json` and
`*/non_system_dependencies.sha256`; G's binary is unchanged from the earlier
repair builds. Never rebuild over these receipts.

From the simulator repository root, a fresh host-only rebuild and archive use:

```sh
module=spine_cycle_sim.experiments.evaluation_impact.figure8_fpga
python3 -m "$module.rebuild" --previous-build /path/to/retained/build --output /new/build
python3 -m "$module.sources" --build-root /new/build --output /new/host-sources.tar.gz
```

The CPU-only `test_spine_persistent_layout.cpp` uses the Spine compile/link
flags below and `xcl2.o`, without board execution. It checks sparse relocated
graph oracles, metadata, all 2048 occupancy masks, L10 bootstrap and vertex-bound
arena sizing. Run it with a 4 GiB address-space limit. The schedule tests also
run through `tests/test_figure8_fpga_schedule.py` without XRT headers.

## Historical V1 Receipts

Build root: `/data/chuxiao/checks/fig8-fpga-persistent-20261107-v1/build`.
Spine's `spine/build_commands.txt` records the executed `-O3 -DNDEBUG` compile
and link commands with g++ 15.2.0 (Debian 15.2.0-14); `spine/spine_persistent.d`
and `spine/xcl2.d` record separate translation units. The source manifest is
`spine/non_system_dependencies.sha256`, with 11 unique normalized files.
The compiled `spine/spine_persistent.host` SHA-256 is
`a86e63421e8f6846095844f61ec7cac5b905916c39b062080762941379815479`.
G's command and dependency receipt are `gr/build.command.txt` and
`gr/gr_persistent.d`, also covering 11 unique source files.

## Source Archive

Include this directory's wrapper sources, headers, pin manifests and guides.
Use the dependency files, not just Git revision labels, to collect the actual
production inputs. Normalize `..` and deduplicate aliases before hashing.
Preserve the following relative trees, because production quoted includes and
Spine's `../../src` include rely on their layout:

- Spine: `tests/test_integration/{host_partitioned_algorithms_smoke.cpp,host_maintenance_backing.hpp,host_update_setup_once.hpp,host_split.hpp,host_resident_benchmark.hpp,xcl2.cpp,xcl2.hpp}`, `tests/test_integration/stubs/CL/cl_ext_xilinx.h`, and `src/spine_paper_architecture_contract.hpp`.
- G: `tools/{sharded_k4_native_host.cpp,weighted_pma_native_host.cpp,sharded_cache_runtime.hpp,sharded_active_min_fixture.hpp}` and `include/{sharded_event_trace.hpp,weighted_pma_graph.hpp,weighted_pma_runtime_plan.hpp,weighted_pma_metadata_plan.hpp,weighted_pma_update_reference.hpp}`.

The checked-in pin manifests hash those external files, not the local wrappers.
Archive local wrapper hashes too; Spine's existing non-system manifest already
includes all local header dependencies. Preserve original absolute-path receipts and
add a relative-path archive manifest; explicitly map old roots to new roots.
Verify hashes before and after relocation. Rebuild to emit fresh dependency
files and confirm no old checkout is silently included.

`-MMD` is a non-system dependency receipt, not a toolchain archive. Provision
C++17 g++, OpenCL C++ headers (`CL/opencl.hpp`, `CL/cl2.hpp`), XRT headers and
libraries separately. The original commands also include Vitis/Vitis HLS 2024.1
headers. Keep compiler/XRT versions and resolved library identities with the
portable receipt. In particular, preserve Spine's pinned extension stub include
precedence. Do not substitute a vendor header unnoticed.

## Relocatable Commands

Set these paths to the extracted roots. The defaults below reproduce the
current source locations; use a fresh output directory, not frozen receipts.
The two source-include macros remove the wrappers' absolute-path defaults.

```bash
ROOT=/data/chuxiao/worktrees/spine-impact-crossover-20261106
SPINE=/data/chuxiao/worktrees/spine-hls-fig8-native
GR=/data/chuxiao/worktrees/grasu-regraph-fig8-g-once
HOSTS="$ROOT/cpp/tests/evaluation_impact/figure8_fpga"
OUT=/path/to/fresh-build
XRT=/opt/xilinx/xrt
VITIS=/data/yxx/tools/xilinx/Vitis/2024.1
HLS=/data/yxx/tools/xilinx/Vitis_HLS/2024.1
mkdir -p "$OUT/spine" "$OUT/gr"

spine_flags=(
  -std=c++17 -O3 -DNDEBUG -Wall -g0
  "-I$SPINE/tests/test_integration" "-I$SPINE/tests/test_integration/stubs"
  "-I$SPINE/src" "-I$VITIS/include" "-I$XRT/include" "-I$HLS/include"
  -DMAX_N=16777216 -DVS_PARTITION_SIZE=1048576 -DMAX_SORT_N=131072
  -DEDGE_BUF_CHUNK_SIZE=33554432 -DSPINE_ALGORITHM_KIND=0
  -DSPINE_RESIDUAL_SPARSE_APPLY=0 -DSPINE_ENFORCE_PAPER_ALIGNMENT_CONTRACT=1
  -DCL_DEVICE_HALF_FP_CONFIG=0x1033
  "-DSPINE_SETUP_ONCE_HOST_SOURCE=\"$SPINE/tests/test_integration/host_partitioned_algorithms_smoke.cpp\""
)
prlimit --as=4294967296 timeout 180 g++ "${spine_flags[@]}" \
  -MMD -MF "$OUT/spine/spine_persistent.d" -MT "$OUT/spine/spine_persistent.o" \
  -c "$HOSTS/spine_persistent.cpp" -o "$OUT/spine/spine_persistent.o"
prlimit --as=4294967296 timeout 180 g++ "${spine_flags[@]}" \
  -MMD -MF "$OUT/spine/xcl2.d" -MT "$OUT/spine/xcl2.o" \
  -c "$SPINE/tests/test_integration/xcl2.cpp" -o "$OUT/spine/xcl2.o"
prlimit --as=4294967296 timeout 60 g++ \
  "$OUT/spine/spine_persistent.o" "$OUT/spine/xcl2.o" \
  -o "$OUT/spine/spine_persistent.host" \
  "-L$XRT/lib" "-Wl,-rpath,$XRT/lib" \
  -lxilinxopencl -lxrt_coreutil -lstdc++ -lrt -pthread

prlimit --as=4294967296 timeout 180 g++ \
  -std=c++17 -O3 -DNDEBUG -Wall -Wextra -Werror \
  -MMD -MF "$OUT/gr/gr_persistent.d" \
  -DGRASU_MAX_CACHE_SEGMENT=131072 \
  -DGRASU_REGRAPH_HOST_ROW_LINE_READ=1 -DGRASU_REGRAPH_PREFETCH_COMPACT=1 \
  "-DGRASU_PERSISTENT_HOST_SOURCE=\"$GR/tools/sharded_k4_native_host.cpp\"" \
  "-I$XRT/include" "-I$HLS/include" "-I$HLS/include/etc" \
  "-I$GR/include" "-I$GR/tools" "$HOSTS/gr_persistent.cpp" \
  "-L$XRT/lib" "-Wl,-rpath,$XRT/lib" -lxilinxopencl -lpthread \
  -o "$OUT/gr/gr_persistent"

timeout 10 "$OUT/spine/spine_persistent.host" --help
timeout 10 "$OUT/gr/gr_persistent" --help
```

Keep one `-MF` per translation unit; compiling both Spine units in one command
with a single `-MF` loses a dependency receipt. These commands only build and
print help. Compilation/help do not test persistent hardware correctness.

## Image And ABI Pins

The existing Spine image is
`/data/feiyang/spine-hls-repair-builds/baseline-20261008-clean345f3df-v1/hw/xclbin/spine_partitioned_split_e2e.hw.xclbin`,
SHA-256 `2000ded183adffce4880792a3edcefa82eb462c460777fd536602397a77cf5dd`,
UUID `2993e806-2fcc-87e2-2147-9c7dab11f03b`.
Its build uses the Spine capacity/algorithm/alignment definitions above,
including **MAX_SORT_N=131072**, not 65536. Do not change these to bypass
host admission without matching the kernel ABI.

The campaign's G image path is
`/data/chuxiao/checks/source-retention-repair-20261104/seele-return-v1-sssp-banked-source-bursts-final/returned/route/candidate.hw.xclbin`,
SHA-256 `2c01a79c3229ef6af7dcb45661a173c05de9b78d973517b11e5923d63a273784`.
Keep `GRASU_MAX_CACHE_SEGMENT=131072` and the production sharded-K4 ABI.

Images and native input traces are not compiler dependencies: archive their
hashes separately, together with binary/source hashes, commands and toolchain
identity. The runner must separately record actual device/BDF, image identity,
clocks, lease/admission, metadata policy, output records and final oracle. No
board access, reset, programming or correctness run is part of these notes.
