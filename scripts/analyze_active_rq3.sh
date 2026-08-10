#!/usr/bin/env bash
set -euo pipefail

campaign_root="${SPINE_CAMPAIGN_ROOT:-/data/tmp/chuxiao/large_graph_campaign_v1}"
output_dir="${SPINE_RQ3_OUTPUT_DIR:-${campaign_root}/rq3_live}"

result_roots=()
while IFS= read -r root; do
  result_roots+=("${root}")
done < <(
  find "${campaign_root}" -path '*/runs/*/case_result.json' -type f -printf '%h\n' \
    | sed 's#/runs/[^/]*$##' \
    | sort -u
)

command=(
  python3 scripts/analyze_rq3_realized_work.py
  --out-dir "${output_dir}"
  --calibration-dataset-id sx_askubuntu
  --preferred-plugin-sha256 7563b028e61e792e7043a582682dd26d0e3d8cc3e2407021f144519d0ef57bf6
  --preferred-plugin-sha256 87472a89dd6ac8446b6abe784d046fea685c5aae244b3986b00d4ea1cdb93f3b
  --preferred-plugin-sha256 b642d0fec915eae99c63ee337daf4f529a89427df288b182be968a4e64bb093a
  --preferred-plugin-sha256 76d9f30f5ee59bba8eee4d7fa7afd3697cc4cf96d266833653eef5955a32ac13
  --preferred-plugin-sha256 65489ede127dc900e72603c3e6b0be89f1b362a6bf0ff6ef510b4de3f27b5254
  --preferred-plugin-sha256 96b4375f8549016ac8be36d85b04b4b5730df0af477dcc5909903845a8f56919
  --preferred-plugin-sha256 c2a60d5250f5594dae98114bd32a96910fe08d11a299eadc6d0b2d1fa56161c6
  --preferred-plugin-sha256 eee35f39c118538da5565e497d29b989e5bb492c1368839d424a984c32e2aae9
  --preferred-plugin-sha256 88d44610461b876ec6617b705e338ed866f4ca18c41e1925bee4f8a26fcc3854
  --preferred-plugin-sha256 1cc810e3dbfcea9c55aff94cecfc601d762a732f8491d9f17caf8fcbb9e57527
)
for root in "${result_roots[@]}"; do
  command+=(--result-root "${root}")
done

"${command[@]}"
