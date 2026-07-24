# Spine vertex payload path

Date: 2026-07-24  
Branch: `codex/fine-grained-cycle-sim`

## Change

Spine compute no longer treats vertex-state AXI reads as timing-only probes.

- Source-value lookup decodes the returned 32-bit vertex word.
- Tiny-tile gather decodes one returned word per input edge, including
  duplicate destinations.
- Full-tile load decodes the complete returned tile into the tile working set.
- Sparse and full-tile stores carry the updated 32-bit values as write data.
- Active-output, bitmap, and result writes carry explicit payloads rather than
  relying on AXI's transitional zero-fill behavior.

The external `values()` vector remains an architectural result mirror. It is
updated from HBM responses and relax results; it is no longer the source of a
gathered value.

The backend supports fill regions, allowing an excluded host-initialization
step to represent a large vertex array initialized to uint32 infinity without
allocating four sparse-map entries per byte. Runtime writes still override
that initial image only when the memory backend completes them.

## Anti-bypass test

`spine_compute_hbm_payload` deliberately creates inconsistent state before a
tiny relaxation:

- compute mirror for vertex 1: uint32 infinity;
- HBM payload for vertex 1: 7;
- incoming proposal: 10.

The accepted result remains 7 and emits no active vertex. A container-backed
implementation would incorrectly accept 10. The test also requires every
compute-side AXI port to report zero implicit write bytes.

## Online SST evidence

The real Amazon full-tile slice still completes in 355,100 cycles with zero
correctness mismatch. Its payload ledger now closes:

| vertex-state traffic | requested bytes | consumed/supplied payload bytes |
| --- | ---: | ---: |
| reads | 320,848 | 320,848 |
| writes | 303,192 | 303,192 |

The run contains 11 tiny tiles and one 49,982-edge full tile. All 35,548
backend requests close against 18,773 DRAM reads plus 16,775 writes. A compact
frozen summary is in
`docs/evidence/sst_spine_vertex_payload_20260724_summary.json`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_full_compute \
  --out-dir results/sst_spine_full_compute_vertex_payload_acceptance_20260724 \
  --no-build
```

## Claim boundary

This closes the vertex-state payload bypass. The emitted graph-edge payload
path is closed in `docs/spine_graph_edge_payload_path_20260724.md`. The
maintenance sorted input, graph-level CSR/index metadata decisions, and carry
merge still use logical containers and are the next payload migration target.
