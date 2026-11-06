# Link Evidence Retention

## Failure And Scope

The exact `spine-cc-stream-link-fresh-20261106-v1.service` invocation
`fbb13007b3984adc92d0dcbcb5c7baaf` completed Vitis linking and packaging
on seele at 15:29 CST, November 6. The script subsequently exited 1 when
copying the raw skew report: Vitis had removed its temporary project.
The HLS Makefile's compile-only `VPP_FLAGS` contained `--save-temps`, but
`VPP_LINK_BASE_FLAGS` did not. The agent's previous recovery script therefore
repeated the evidence-loss failure. This is not a compiler OOM, correctness
failure or proof that skew constraints passed.

The image remains at
`/data/chuxiao/spine-cc-stream-admit-2315cae-route-v2/xclbin/spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.xclbin`,
SHA-256 `0939fc5b51133cf79954c266434c502f1ac8cd9f541a0200d5f331931e373d28`.
Ordinary timing reports show setup WNS +0.002 ns and hold WHS +0.009 ns.
The log proves the skew-report hook ran; it does **not** reveal the report's
slack. No routed checkpoint survives. Missing evidence is not a pass.

The build peaked at 259,455,295,488 bytes (241.64 GiB), below the explicit
320-GiB task limit; all saved cgroup memory events are zero. Both dependent
local services terminated without requesting a board execution:

| Service | Invocation |
| --- | --- |
| `spine-retention-cc-au-fresh-link-20261106-v2.service` | `e3007078573249d3b279543d2256b3ca` |
| `gr-retention-cc-fresh-link-matrix-20261106-v2.service` | `225e50b5f04441d4bcd0c040ff4721f4` |

[Immutable failure receipts](fresh_link_retention_failure_receipts.tar.gz)
include the execution JSON, build/Vivado logs, ordinary timing, terminal
service properties and failed collector/matrix reports. Archive SHA-256:
`4dbf94d27f4504d1aecd2ced4354307eff8d2f35398ae70129671d7a92bf9097`.

## Correction

The new [frozen link script](cc-stream-link-retained-20261106.sh) uses the
fresh root `/data/chuxiao/spine-cc-stream-admit-2315cae-route-v3`. It does not
overwrite either old image or receipt. The host, three XOs, source and CC
connectivity are copied and hash-checked. The existing 734-MiB synthesis
cache is copied, not modified in place. Cache reuse is an optimization, not
evidence of a completed or numerically equivalent new link.

The script explicitly passes `--save-temps` through **link** flags and
`--remote_ip_cache` through the existing Makefile API. The same Bash array
drives a dry run and the real invocation. The small `source_retention.link_retention`
module rejects a dry run unless it contains exactly one link, no XO
compilation, `--save-temps`, and the exact image/temp/cache paths.
`link-command.txt` and `link-command-validation.json` preserve that check.
After link success the script requires the raw skew report and routed DCP
to exist and copies both into durable `reports/` as well. These changes do
not alter numerical kernels, ABI, topology, 150-MHz target or tool jobs.

Focused regression tests cover the original error (compile-only retention),
missing/wrong/duplicate paths, missing or multiple links, accidental XO
recompilation and shell quoting/continuations. This preflight does not
substitute for the existing route, raw skew, correctness or paired-time gates.

## Replacement Status

The replacement has not yet been admitted at this documentation checkpoint.
It must use a fresh unit/invocation and the unchanged `320g-v1` supervisor:
320/304-GiB max/high, zero task swap, atomic full-budget admission and a
128-GiB live host reserve. No host cache-clearing or ZFS settings change is
required. Fresh local followers must identify that exact successful build,
then pass the AU correctness/replay gate before requesting the other seven
CC pairs. The frozen formal result remains **16/24 pairs; eight CC missing**.
