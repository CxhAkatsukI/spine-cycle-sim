#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
sst_core_prefix=${SPINE_SST_CORE_PREFIX:-/data/feiyang/sst}
idle_install_prefix=${SPINE_IDLE_SST_INSTALL_PREFIX:?set SPINE_IDLE_SST_INSTALL_PREFIX}
idle_dramsim3_src=${SPINE_IDLE_DRAMSIM3_SRC:?set SPINE_IDLE_DRAMSIM3_SRC}
spine_element_dir=${SPINE_CYCLE_ELEMENT_DIR:-${repo_root}/build/sst}

export LD_LIBRARY_PATH="${idle_dramsim3_src}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
exec "${sst_core_prefix}/bin/sst" \
  --lib-path="${idle_install_prefix}/lib/sst-elements-library:${spine_element_dir}" \
  "$@"
