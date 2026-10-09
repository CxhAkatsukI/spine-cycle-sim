# Architecture and Contracts

This section explains what is being modeled. These records refer to specific
profiles and implementation milestones; they do not collectively certify that
every timing stage is FPGA-calibrated.

## Reading Order

1. [Paper architecture alignment](paper_architecture_alignment_20260803.md):
   the frozen alignment contract, target geometry, and artifact identities.
2. [Architecture/evidence crosswalk](spine_architecture_evidence_crosswalk.md):
   differences between the manuscript, evaluated models, and HLS artifacts.
   Its superseding section precedes an explicitly historical detailed audit.
3. [Fine-grained cycle-simulation contract](fine_grained_cycle_sim_contract_20260723.md):
   finite resources and execution-model responsibilities.
4. [Dynamic algorithm contract](dynamic_algorithm_contract_20260725.md) and
   [CC/residual execution contract](cc_residual_execution_contract_20260728.md):
   state, update, propagation, and completion semantics.

## Specialized Contracts

- [C++ algorithm policies](cpp_algorithm_policy_contract_20260725.md)
- [Spine dynamic PageRank](spine_dynamic_pagerank_contract_20260726.md)
- [GraSU PMA-native interface](grasu_regraph_pma_native_contract_20260725.md)
- [Payload-backed memory](payload_backed_memory_foundation_20260724.md)
- [Spine AXI interface profile](spine_axi_interface_profile_20260724.md)
- [Sparse HBM bindings](normalized_sparse_hbm_binding_20260725.md)

[design.md](design.md) is an early design overview, not the current handoff
authority. Machine-readable profiles and contracts remain under the repository's
`configs/`; a selected package's provenance decides which versions apply.

Continue with the [implementation guide](../implementation/README.md) or the
[current figure handoff](../evaluation_refresh_20260810/figure7_10_handoff_v1/README.md).
