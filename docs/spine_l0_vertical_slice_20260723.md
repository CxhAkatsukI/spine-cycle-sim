# Spine stable-profile L0 maintenance vertical slice

Date: 2026-07-23  
Branch: `codex/fine-grained-cycle-sim`

## Evidence identity

This slice follows the routed stable profile `spine_shared_engine_9c08763`.
The exact accepted source archive is:

```text
/data/feiyang/spine-dynamic-graph-builds/
  merged_directory_shared_engine_9c08763/acceptance_bundle/
  candidate/source/repository-9c08763.tar.gz
```

Its SHA-256 is
`a7a06ce22dd051cd764d84e83ad9a35238ba4928b4040f6bcbaa2884111593aa`.
The accepted xclbin and its hash remain pinned in the architecture profile.

The test workload is the committed, file-backed
`tests/data/amazon_top1_exact.slice`: ten real `amazon-2008.mtx` edge records,
one active source, and 735,323 vertices.

## Implemented path

`SpineL0Maintenance` is a C++ cycle component. It owns live maintenance state
and sends requests through independent fixed-channel AXI masters:

- graph family 0..15 -> HBM[0]..HBM[15];
- sorted edges and persistent dirty state -> HBM[16];
- level metadata -> HBM[20];
- maintenance result -> HBM[21].

The target-0, hot-disabled path executes the stable HLS control structure:

1. dirty-frontier preflight scans the sorted batch;
2. dirty directory/frontier update scans it again and performs persistent
   directory, bitmap, and list read-modify-write operations;
3. target selection reads occupancy metadata;
4. the shared L0 writer pre-counts each of 16 cold families, scanning the full
   batch once per family;
5. each nonempty family scans once more, coalesces `(src,dst)` differentials,
   and writes bitmap, page-base, row-offset, row-mask, and edge payload areas;
6. all 16 staged family metadata records are committed, followed by the result
   record.

For the one-family Amazon fixture this is exactly `2 + 16 + 1 = 19` sorted
batch scans, or 190 edge visits and 3,040 sorted-edge bytes. The resulting
logical L0 contains the ten input payloads in cold family 0 and no payload in
the other 15 families.

Every external memory task traverses finite request/response FIFOs, an AXI
master, and a memory backend. The test uses deterministic MockMemory; the same
port contract is accepted by the online SST-HBM backend.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
cmake -S . -B build/cycle-core -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/cycle-core
build/cycle-core/cpp/spine_cycle_core_tests
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
git diff --check
```

The focused C++ result is `PASS spine_l0_real_slice` and checks:

| counter | expected |
| --- | ---: |
| sorted scan passes | 19 |
| sorted edge visits | 190 |
| sorted read bytes | 3,040 |
| active cold families | 1 |
| persisted rows / edges | 1 / 10 |
| dirty persistent read / write bytes | 48 / 48 |
| graph layout write bytes | 288 |
| metadata read / write bytes | 416 / 1,104 |
| result write bytes | 384 |

## Claims boundary

This is structural and functional evidence, not a calibrated latency claim.
The first implementation waits for each high-level memory task before issuing
the next task. AXI bursts and beat-level HBM timing are real, but the HLS can
overlap loop processing, prefetch, and requests to independent ports. That
overlap must be represented before comparing predicted cycles with hardware.

Not yet implemented in this component:

- hot-enabled family maintenance;
- target levels above L0 and sparse carry merge;
- exact metadata cache/packing and all compiler-generated AXI burst boundaries;
- reader, depth-32 cross-SLR AXIS, tiny/full compute, and convergence;
- online SST execution of this architecture component rather than the generic
  memory probe.

Those omissions are exposed in the document and architecture SVG; they are not
replaced by fitted constants.
