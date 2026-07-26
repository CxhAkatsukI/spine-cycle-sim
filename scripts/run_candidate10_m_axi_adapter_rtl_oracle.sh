#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DEFAULT_XO=/data/feiyang/spine-dynamic-graph-builds/pipeline_dirty_frontier_publication_1e61fc0_20260725/production/hls_v5_candidate_10/spine_partconv_rdmaint_kernel.hw.xo
XO=${CANDIDATE10_XO:-$DEFAULT_XO}
EXPECTED_XO_SHA256=${CANDIDATE10_XO_SHA256:-629e185724467cc14eec4ae14018ff0a89a94aa518ef77499ca6cc2363b28be5}
XVLOG=${XVLOG:-/data/yxx/tools/xilinx/Vivado/2024.1/bin/xvlog}
XELAB=${XELAB:-/data/yxx/tools/xilinx/Vivado/2024.1/bin/xelab}
XSIM=${XSIM:-/data/yxx/tools/xilinx/Vivado/2024.1/bin/xsim}
BUILD_DIR=${BUILD_DIR:-$(mktemp -d /data/tmp/chuxiao/candidate10_m_axi_adapter_rtl_oracle.XXXXXX)}

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
MODULE=spine_partconv_rdmaint_kernel_gmem_p0_m_axi.v
mkdir -p "$BUILD_DIR/rtl" "$BUILD_DIR/xsim"
exec 9>"$BUILD_DIR/.oracle.lock"
if ! flock -n 9; then
  echo "Candidate10 m_axi adapter oracle directory is active: $BUILD_DIR" >&2
  exit 2
fi

cd "$BUILD_DIR/xsim"
if [[ ${CANDIDATE10_ORACLE_REUSE:-0} != 1 || \
      ! -d xsim.dir/candidate10_m_axi_adapter_oracle ]]; then
  unzip -jo "$XO" "$RTL_PREFIX/$MODULE" -d "$BUILD_DIR/rtl" >/dev/null
  "$XVLOG" --sv "$BUILD_DIR/rtl/$MODULE" \
    "$ROOT/scripts/rtl/candidate10_m_axi_adapter_tb.sv"
  "$XELAB" -debug typical candidate10_m_axi_adapter_tb \
    -s candidate10_m_axi_adapter_oracle
fi

args=()
for value in "$@"; do
  args+=(--testplusarg "$value")
done
"$XSIM" candidate10_m_axi_adapter_oracle \
  --tclbatch "$ROOT/scripts/rtl/run_all.tcl" "${args[@]}"
echo "Candidate10 XO SHA256: $ACTUAL_XO_SHA256" >&2
echo "RTL oracle build directory: $BUILD_DIR" >&2
