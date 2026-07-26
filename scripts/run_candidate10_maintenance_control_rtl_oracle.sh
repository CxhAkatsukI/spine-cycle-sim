#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
XVLOG=${XVLOG:-/data/yxx/tools/xilinx/Vivado/2024.1/bin/xvlog}
XELAB=${XELAB:-/data/yxx/tools/xilinx/Vivado/2024.1/bin/xelab}
XSIM=${XSIM:-/data/yxx/tools/xilinx/Vivado/2024.1/bin/xsim}
BUILD_DIR=${BUILD_DIR:?BUILD_DIR must name the prepared oracle directory}

for tool in "$XVLOG" "$XELAB" "$XSIM"; do
  if [[ ! -x "$tool" ]]; then
    echo "Xilinx simulator tool not executable: $tool" >&2
    exit 2
  fi
done
if [[ ! -d "$BUILD_DIR/rtl" ]]; then
  echo "Prepared RTL directory not found: $BUILD_DIR/rtl" >&2
  exit 2
fi

mkdir -p "$BUILD_DIR/xsim"
exec 9>"$BUILD_DIR/.oracle.lock"
if ! flock -n 9; then
  echo "Candidate10 maintenance-control oracle is active: $BUILD_DIR" >&2
  exit 2
fi

cd "$BUILD_DIR/xsim"
if [[ ${CANDIDATE10_ORACLE_REUSE:-0} != 1 || \
      ! -d xsim.dir/candidate10_maintenance_control_oracle ]]; then
  mapfile -t RTL_FILES < <(
    find "$BUILD_DIR/rtl" -maxdepth 1 -type f -name '*.v' | sort
  )
  if [[ ${#RTL_FILES[@]} -eq 0 ]]; then
    echo "No prepared Candidate10 RTL files found" >&2
    exit 2
  fi
  "$XVLOG" --sv "${RTL_FILES[@]}" \
    "$ROOT/scripts/rtl/candidate10_maintenance_control_tb.sv"
  "$XELAB" -debug typical candidate10_maintenance_control_tb \
    -s candidate10_maintenance_control_oracle
fi

args=()
for value in "$@"; do
  args+=(--testplusarg "$value")
done
"$XSIM" candidate10_maintenance_control_oracle \
  --tclbatch "$ROOT/scripts/rtl/run_all.tcl" "${args[@]}"
echo "RTL oracle build directory: $BUILD_DIR" >&2
