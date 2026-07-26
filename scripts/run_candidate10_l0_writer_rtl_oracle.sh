#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DEFAULT_XO=/data/feiyang/spine-dynamic-graph-builds/pipeline_dirty_frontier_publication_1e61fc0_20260725/production/hls_v5_candidate_10/spine_partconv_rdmaint_kernel.hw.xo
XO=${CANDIDATE10_XO:-$DEFAULT_XO}
EXPECTED_XO_SHA256=${CANDIDATE10_XO_SHA256:-629e185724467cc14eec4ae14018ff0a89a94aa518ef77499ca6cc2363b28be5}
XVLOG=${XVLOG:-/data/yxx/tools/xilinx/Vivado/2024.1/bin/xvlog}
XELAB=${XELAB:-/data/yxx/tools/xilinx/Vivado/2024.1/bin/xelab}
XSIM=${XSIM:-/data/yxx/tools/xilinx/Vivado/2024.1/bin/xsim}
BUILD_DIR=${BUILD_DIR:-$(mktemp -d /data/tmp/chuxiao/candidate10_l0_writer_rtl_oracle.XXXXXX)}

if [[ ! -f "$XO" ]]; then
  echo "Candidate10 XO not found: $XO" >&2
  exit 2
fi
ACTUAL_XO_SHA256=$(sha256sum "$XO" | awk '{print $1}')
if [[ "$ACTUAL_XO_SHA256" != "$EXPECTED_XO_SHA256" ]]; then
  echo "Candidate10 XO hash mismatch: expected=$EXPECTED_XO_SHA256 actual=$ACTUAL_XO_SHA256" >&2
  exit 2
fi
for tool in "$XVLOG" "$XELAB" "$XSIM"; do
  if [[ ! -x "$tool" ]]; then
    echo "Xilinx simulator tool not executable: $tool" >&2
    exit 2
  fi
done

RTL_PREFIX=ip_repo/xilinx_com_hls_spine_partconv_rdmaint_kernel_1_0/hdl/verilog
mkdir -p "$BUILD_DIR/rtl" "$BUILD_DIR/xsim"
exec 9>"$BUILD_DIR/.oracle.lock"
if ! flock -n 9; then
  echo "Candidate10 L0-writer RTL oracle directory is already active: $BUILD_DIR" >&2
  exit 2
fi

cd "$BUILD_DIR/xsim"
if [[ ${CANDIDATE10_ORACLE_REUSE:-0} != 1 || \
      ! -d xsim.dir/candidate10_l0_writer_oracle ]]; then
  modules=(
    spine_partconv_rdmaint_kernel_partitioned_write_l0_family.v
    spine_partconv_rdmaint_kernel_partitioned_write_l0_family_Pipeline_PARTITIONED_WRITE_L0_EDGES.v
    spine_partconv_rdmaint_kernel_partitioned_clear_l0_reachable_index_area_with_base.v
    spine_partconv_rdmaint_kernel_partitioned_clear_l0_index_area_with_base.v
    spine_partconv_rdmaint_kernel_partitioned_clear_l0_reachable_index_area_with_base_Pipeline_PARTITIONED_CLEAR_L.v
    spine_partconv_rdmaint_kernel_partitioned_clear_l0_reachable_index_area_with_base_Pipeline_PARTITIONED_CLEAR_L_1.v
    spine_partconv_rdmaint_kernel_partitioned_clear_l0_index_area_with_base_Pipeline_PARTITIONED_CLEAR_L0_BITMAP.v
    spine_partconv_rdmaint_kernel_partitioned_clear_l0_index_area_with_base_Pipeline_PARTITIONED_CLEAR_L0_PAGE_BAS.v
    spine_partconv_rdmaint_kernel_flow_control_loop_pipe_sequential_init.v
    spine_partconv_rdmaint_kernel_sparsemux_9_2_64_1_1.v
    spine_partconv_rdmaint_kernel_mul_5ns_5ns_9_1_1.v
    spine_partconv_rdmaint_kernel_mul_5ns_21ns_25_1_1.v
    spine_partconv_rdmaint_kernel_mac_muladd_18ns_5ns_24ns_25_4_1.v
  )
  for module in "${modules[@]}"; do
    unzip -jo "$XO" "$RTL_PREFIX/$module" -d "$BUILD_DIR/rtl" >/dev/null
  done
  mapfile -t RTL_FILES < <(find "$BUILD_DIR/rtl" -maxdepth 1 -type f -name '*.v' | sort)
  "$XVLOG" --sv "${RTL_FILES[@]}" "$ROOT/scripts/rtl/candidate10_l0_writer_tb.sv"
  "$XELAB" -debug typical candidate10_l0_writer_tb -s candidate10_l0_writer_oracle
fi

args=()
for value in "$@"; do
  args+=(--testplusarg "$value")
done
"$XSIM" candidate10_l0_writer_oracle \
  --tclbatch "$ROOT/scripts/rtl/run_all.tcl" "${args[@]}"
echo "Candidate10 XO SHA256: $ACTUAL_XO_SHA256" >&2
echo "RTL oracle build directory: $BUILD_DIR" >&2
