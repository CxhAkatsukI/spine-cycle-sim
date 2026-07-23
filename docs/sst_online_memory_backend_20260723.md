# Online SST-HBM vertical slice

Date: 2026-07-23

## Scope

This vertical slice connects the new C++ cycle core to an online SST memory
path:

`execution-driven source -> finite FIFO -> AXI master -> StandardMem ->`
`MemController -> DRAMSim3 HBM2 -> AXI response -> finite FIFO -> sink`

The C++ source decides each request from live state. SST does not replay a
precomputed memory trace. SST supplies clocked memory completion events; the
adapter samples each completion at a core edge and the C++ AXI state machine
continues from that response. MockMemory remains a deterministic unit-test
double and is not the formal experiment backend.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_sst_memory_smoke.py \
  --out-dir results/sst_memory_smoke_20260723
```

The script builds `build/sst/libspine_cycle.so` and runs equal-size sequential
read, cross-row read, and mixed read/write cases. For every case it requires:

- source requests completed without failure;
- AXI beat count equals backend request count;
- AXI byte count equals input byte count;
- aggregate DRAMSim3 completed reads/writes equal backend request count;
- the configured number of DRAMSim3 channel instances produced statistics.

It also requires the cross-row case to produce more ACT commands, fewer row
hits, and more core cycles than the sequential case.

To instantiate the normalized 16-channel topology:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_sst_memory_smoke.py \
  --channels 16 \
  --out-dir results/sst_memory_smoke_16ch_20260723
```

## Initial evidence

The first direct one-channel probes established that the memory model changes
architectural timing rather than merely accepting API calls:

| case | requests | core cycles | ACT | PRE | read row hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| sequential 64-byte read | 64 | 74 | 2 | 0 | 62 |
| 128-KiB-stride read | 64 | 438 | 64 | 63 | 0 |
| 4-KiB-stride 50%-write mix | 64 | 78 | 39 | 32 | 0 |

The 16-channel instantiation completed 256 source requests and 256 AXI/backend/
DRAM requests in 266 core cycles with zero failed requests. These are
integration sanity results, not Spine performance claims.

## Remaining gaps

- The current SST component is a synthetic request source, not yet the Spine or
  GraSU+ReGraph architecture model.
- AXI data payload values are not modeled; only addresses, operation type,
  bytes, completion, ordering, and timing are represented.
- One `MemController + DRAMSim3` instance represents each independent HBM
  channel. The U55C crossbar and vendor controller details still require an
  explicit normalized profile and hardware microbench validation.
- The adapter samples responses at core clock edges. Internal FPGA CDC logic is
  outside scope and must be represented by an explicit configurable bridge
  delay if hardware evidence shows additional cycles.
- DRAMSim3 energy is memory-only activity evidence. It is not total accelerator
  energy and cannot replace CACTI/logic synthesis evidence.
