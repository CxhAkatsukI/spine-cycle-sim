#!/usr/bin/env bash
set -euo pipefail
/data/chuxiao/validation/hls_simulator_alignment_20261024/packets/fullpr/compile_commands.sh
python3 /home/chuxiao/grasu-regraph-sim-aligned/scripts/check_xo_master_budget.py --xo /data/chuxiao/validation/hls_simulator_alignment_20261024/packets/fullpr/build/bin_search.hw.xo --expected-masters 2
python3 /home/chuxiao/grasu-regraph-sim-aligned/scripts/check_xo_master_budget.py --xo /data/chuxiao/validation/hls_simulator_alignment_20261024/packets/fullpr/build/kernelHBMWrapper.hw.xo --expected-masters 2
python3 /home/chuxiao/grasu-regraph-sim-aligned/scripts/check_xo_master_budget.py --xo /data/chuxiao/validation/hls_simulator_alignment_20261024/packets/fullpr/build/regraph_pagerank_source_prepare.hw.xo --expected-masters 4
python3 /home/chuxiao/grasu-regraph-sim-aligned/scripts/check_pipeline_master_budget.py --build-dir /data/chuxiao/validation/hls_simulator_alignment_20261024/packets/fullpr/build --compute-pipelines 4 --pipeline-mode sharded-k4 --platform-master-budget 32 --out /data/chuxiao/validation/hls_simulator_alignment_20261024/packets/fullpr/pipeline_master_budget.json
/data/chuxiao/validation/hls_simulator_alignment_20261024/packets/fullpr/link_command.sh
