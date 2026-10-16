# Production-Source Experimental G Route

## Decision

At the 2026-10-16 09:02 UTC checkpoint, `g-production-route-v1` is
`QUEUED_WAITING_FOR_SAFE_MEMORY`, with `route_started=false`. Its production
component, connected-state, reused-XO and storage checks pass. **It is not a
completed route, integrated RTL check, board measurement or baseline admission.**
The two older 40-GiB routes continue concurrently; they were not stopped or
modified. This candidate starts when full memory budgets fit, without waiting
for all other FPGA tools to exit.

## Frozen Identity

| Owner | Frozen source |
| --- | --- |
| Production validation and candidate gates | Integration commit `7b3763ecc774b6699b785fa829b389a66b16d339`, `/home/chuxiao/grasu-regraph-production-route` |
| Shared packet, memory supervisor and watchdog | Simulator commit `1006b7f0d1d3152daab63af8afb4bcc498f96477`, `/home/chuxiao/spine-cycle-sim/spine-cycle-sim-production-route` |
| Raw attempt | `/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-production-route-v1` |
| Service | `spine-g-production-route-20261016-v1.service` |
| Invocation | `194a3f0af5c74d408ac4aa494a435970` |

There are eleven frozen XOs and 22 CUs at 150 MHz. Only the following XOs
replace the adapter-route basis:

| Kernel | Fresh production component export | SHA-256 |
| --- | --- | --- |
| Four `bin_search` CUs | `g-production-rtl-v2/search/candidate.xo` | `e17f8394e1bbffc5ca5e7ca69b19c51ed0acafcd64c726341249287c4bf6a6ff` |
| Two `process_cache` CUs | `g-production-rtl-v2/cache-token/candidate.xo` | `2a2b3947f39387937207e2f6b77dbffd10e0d3931a2e76ffc6bd4022dda01b1b` |

The nine other XOs, HBM mappings, AXIS connections and algorithms are unchanged.
Both cache halves retain 131072 segments. Moving only `lksg_stream_4` from
SLR0 to SLR1 follows the same-export platform URAM screen, giving 320/128/320
URAM across SLRs. This is not proof that placement, routing or timing will pass.

The [older diagnostic route](../hardware/README.md) uses different, older
search/cache exports. Its conditional G/GR board queues do not validate this
production-source artifact. Never merge their identities or relabel its result.

## Checks And Retained Failure

The production-owned `validation/grasu_complete/routing/` package separates
upstream reuse, candidate gates, preparation and its thin CLI. It replays
component Verilog/ABI evidence, the connected eighteen-transaction full-state
check and the same-export storage ledger. All eleven owned core files,
provenance and upstream configuration must match; the two different host-only
test fixtures retain separate identities and are excluded from synthesis.

The first read-only input review wrongly compared the finite host fixture as
an owned core and stopped before packet creation. Its v1 systemd journal is
retained. Corrected v2 reviews all thirteen owned/configuration members and
2308 pins, passes in 1.149 s with a 24.7-MiB cgroup peak, and reports zero
memory events. This is input review time, not FPGA performance.

Reused dispatch/cold XOs are checked against original compile commands, flags,
150-MHz target, original/current source hashes and embedded XO source. One
physical limitation is explicit: the connected CPU fixture uses shared-port
pragmas, while the reused cold XO has four AXI masters. CPU operations match;
actual BO aliasing/coherence still needs device validation.

Preparation freezes 2485 pins, including imported validation/experiment code
and Python. Its separate 1-GiB preparation service passes with a 29.4-MiB
peak and zero memory events. Imported code runs from the two frozen worktrees;
do not edit any path pinned by the active packet or its inherited evidence.

Forty production tests pass, including rejection of changed sources, compile
flags, XOs, storage screens and runner copies. Twelve simulator packet/supervisor
tests pass, including old-packet equivalence and concurrent admission. Fifteen
organization tests, document/catalog checks and both whitespace checks pass.
These regression results are not hardware measurements.

## Memory And Monitoring

The route has a 40-GiB hard cap, 36-GiB high watermark, zero swap, group OOM
kill, two synthesis/implementation jobs and a 12-hour link deadline. The
service has a 37-hour lifetime, including the 24-hour memory queue. The shared
atomic lease requires eight consecutive safe two-second samples before tools
start; live process-tree and available-memory guards remain active afterward.

With two 40-GiB peers, the requirement is
`40 own + 80 peers + 24 reserve + 8 background = 152 GiB`.
The checkpoint has 117509357568 available bytes versus 163208757248 required.
This is why the new link is queued; neither memory rejection nor queueing is
a hardware failure. Unknown or unbounded peer compilers also prevent admission.

```bash
systemctl --user show spine-g-production-route-20261016-v1.service \
  -p ActiveState -p SubState -p MemoryCurrent -p MemoryMax -p InvocationID
jq '{status,route_started,available_bytes,required_bytes,queue_seconds}' \
  /data/chuxiao/experiments/baseline_hardware_validation_20261015/g-production-route-v1/execution.json
journalctl --user -u spine-g-production-route-20261016-v1.service -n 20 --no-pager
```

Preparation records are `preparation_admission.json` and
`preparation_memory_events.json`. `manifest.json` owns immutable source/input
pins but receives one additional preflight-result pin before tools start.
The [production board queue](../production_board/README.md) freezes the original
pin prefix and all other fields, allowing only this verified trailing pin;
the older diagnostic queue cannot accept this manifest transition. `execution.json` is
live state. Terminal `summary.json`, resource logs and `cgroup_events.json`
remain authoritative even when the attempt fails. Never overwrite a failed run.

## Remaining Acceptance

A successful link still needs exact artifact/topology review and strict routed
timing. Integrated finite-stream RTL, same-address device metadata refresh,
complete resident-state checks, actual PMA-to-R handoff and separated G/R/host
windows remain open. The new production board qualifier declares those initial
state/handoff matrices without claiming they have run. Only then can same-platform controls and the fixed Spine
matrix support new figures. No figure or paper value is replaced by this queue.
See the [production source guide](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/7b3763ecc774b6699b785fa829b389a66b16d339/validation/README.md#production-source-experimental-route)
for reproduction arguments; use fresh output paths and mandatory containment.
