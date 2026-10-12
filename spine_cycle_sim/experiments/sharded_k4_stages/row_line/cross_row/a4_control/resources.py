"""Source-bound resource audit, separate from immutable numerical evidence."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from .contract import BOUNDARY, DOC, profile
from .delivery import verify

DIRECTORY = DOC / "adapter_optimization/row_line/cross_row/a4_control"
INDEX_SHA = "1c90d2a3dd64d07a088ded17eedd3c210ca84a56cfd8680bdf983d51dcb269ec"
ORIGINAL_AXI = DOC.parent / "a4_results.json"
ORIGINAL_AXI_SHA = "da34da9d64fb8db7f061a93e3204c4074b15f393541302dc43166c53b150ca18"
SOURCES = (
    "cpp/tests/original_regraph/whole_graph/compute_wiring.hpp",
    "cpp/tests/original_regraph/memory_fixture.hpp",
    "cpp/tests/original_regraph/sssp/real_round.cpp",
    "cpp/tests/routed_regraph/round_execution.hpp",
    "cpp/src/routed_regraph/composition.cpp",
    "cpp/src/routed_regraph/resident_memory.cpp",
    "cpp/src/routed_regraph/transport.cpp",
    "cpp/src/grasu_regraph_runtime.cpp",
    "cpp/include/spine_sim/grasu_regraph.hpp",
    "cpp/include/spine_sim/routed_regraph.hpp",
    "cpp/include/spine_sim/axi.hpp",
    "configs/architectures/grasu_regraph_routed_sssp_compute_v3.json",
    "configs/architectures/grasu_regraph_cross_row_sssp_compute_v1.json",
)


def checked_json(root, relative, expected):
    path = root / relative
    if path.is_symlink() or sha256_file(path) != expected:
        raise ValueError(f"resource-audit evidence identity differs: {relative}")
    return json.loads(path.read_text())


def source_pins(root, index):
    pins = {item["path"]: item["sha256"] for item in index["files"]}
    result = []
    for relative in SOURCES:
        expected = pins["run/sources/" + relative]
        path = root / relative
        if path.is_symlink() or sha256_file(path) != expected:
            raise ValueError(f"audited resource source changed; review required: {relative}")
        result.append({"path": relative, "sha256": expected})
    return result


def original_physical_interfaces(evidence):
    # One synthesized Little instance is replicated four times in A4.
    counts = []
    for item, copies, reads, writes in zip(evidence["axi_interface_evidence"], (4, 1, 1),
                                         ([16], [16] * 4, [16]), ([0], [16] * 4, [0]), strict=True):
        p = item["parameters"]
        if (p["NUM_READ_OUTSTANDING"] != reads or p["NUM_WRITE_OUTSTANDING"] != writes
                or p["C_M_AXI_DATA_WIDTH"] != [512] * len(reads)
                or p["MAX_READ_BURST_LENGTH"] != [16] * len(reads)
                or p["MAX_WRITE_BURST_LENGTH"] != [16] * len(reads)):
            raise ValueError("original synthesized interface geometry differs")
        counts.append(copies * len(reads))
    return sum(counts)


def endpoints():
    """Reviewed bindings, valid only for the exact source pins above."""
    original, candidate = [], []
    for worker in range(4):
        for role, channel, direction, parents in (
                ("edge", worker * 2, "read", 2),
                ("source", worker * 2 + 1, "read", 2),
                ("state_write", worker * 2 + 1, "write", 2)):
            original.append({"name": f"{role}{worker}", "channel": channel,
                             "direction": direction, "parent_credits": parents,
                             "independent_read_write": False})
        candidate += [
            {"name": f"adapter{worker}", "channel": "runtime_PMA_row_channels_0_to_22",
             "direction": "read", "parent_credits": 16, "independent_read_write": False},
            {"name": f"source{worker}", "channel": 23 + worker % 2,
             "direction": "read_write" if worker < 2 else "read",
             "parent_credits": 16, "independent_read_write": True},
        ]
    original.append({"name": "old_state", "channel": 30, "direction": "read",
                     "parent_credits": 2, "independent_read_write": False})
    candidate.append({"name": "apply_state_status", "channel": 30, "direction": "read_write",
                      "parent_credits": 16, "independent_read_write": False})
    return {"original": original, "cross_row": candidate}


def audit(root, source_root=None):
    directory = root / DIRECTORY
    index = checked_json(root, DIRECTORY / "evidence/verification.json", INDEX_SHA)
    source_root = source_root if source_root is not None else root
    sources = source_pins(source_root, index)
    report = verify(directory / "evidence")
    axi = checked_json(root, ORIGINAL_AXI, ORIGINAL_AXI_SHA)
    selected = profile(source_root)
    memory, fixed = selected["memory"], selected["fixed_model"]
    sample = {row["arm"]: row for row in report["cases"]
              if (row["mode"], row["latency"], row["reverse"]) == ("warm_update", 64, 0)}
    a4, k4 = sample["original"]["paths"][0], sample["cross_row"]["counters"]
    if (a4["checked_words_per_replica"] != k4["checked_words_per_replica"]
            or a4["replicas"] != 4 or k4["replicas"] != 3
            or memory["physical_master_count"] != 9 or fixed["kernel_mhz"] != 150):
        raise ValueError("audited model geometry differs")
    differences = {
        "physical_interface_composition": "A4 splits each source-read/state-write pair into separate modeled masters; K4 shares two such pairs.",
        "source_state_banks": "A4: four banks 1/3/5/7; K4: four readers on two banks 23/24.",
        "parent_credit_capacity": "A4: two parent requests per endpoint; K4: sixteen per physical master, with shared clients where applicable.",
        "stream_capacity": "A4 test fixture: depth eight; K4: internal eight, external sixteen, adapter/gather/mux thirty-two.",
        "publication": "A4 publishes four replicas; K4 publishes primary plus two source replicas and status, sharing primary read/write/status.",
        "task_and_merge_schedule": "A4: four task paths per destination partition; K4: destination shards assigned modulo four, ordered gather mux and shared backend.",
    }
    return {
        "schema_version": 1, "version": "cross_row_A4_resource_audit_v1",
        "status": "audited_diagnostic_not_strict_resource_match",
        "basis_verification_sha256": INDEX_SHA, "original_axi_evidence_sha256": ORIGINAL_AXI_SHA,
        "sources": sources, "endpoint_bindings": endpoints(),
        "interface_counts": {"original_synthesized_physical": original_physical_interfaces(axi),
                             "original_modeled_endpoints": 13, "K4_modeled_physical": 9,
                             "K4_source_masters": 4, "K4_source_banks": 2},
        "common": {"algorithm": "weighted_SSSP", "frontends": 4, "rounds": 1,
                   "boundary": BOUNDARY, "clock_mhz": 150, "memory_backend": "MockMemoryBackend",
                   "backend_channels": 32, "backend_outstanding_per_channel": 32,
                   "backend_response_queue_depth": 32, "channel_issue_per_cycle": 1,
                   "axi_data_bytes": 64, "axi_max_burst_beats": 16, "axi_outstanding": 16,
                   "same_initial_state_batch_and_complete_oracle": True},
        "unmatched": differences,
        "publication_bytes_per_round": {"original": a4["write_bytes"], "cross_row": k4["write_bytes"]},
        "credit_interpretation": "A4's independent_read_write=false is per separate read-only/write-only endpoint, not a shared source-read/state-write credit pool. K4 source masters enable independent directions; Apply/status does not. Backend channel arbitration remains separate.",
        "admission": {"integrated_path_diagnostic": True, "strict_resource_match": False,
                      "isolated_adapter_overhead": False, "FPGA_timing": False,
                      "published_performance_match": False, "update_to_convergence": False},
        "limitations": ["This audits reviewed configuration/source bindings, not dynamic stalls or FPGA speed.",
                        "Original RTL interface evidence is synthesis evidence, not an original A4 routed measurement.",
                        "A later two-service HLS worktree topology is not substituted for the pinned four-master wrapper.",
                        "Three K4 published replicas do not mean three total BO allocations: source buffers are ping-ponged.",
                        "No numerical source, frozen result, model parameter or paper artifact is changed."],
    }


def require_claim(result, claim):
    if claim not in result["admission"] or result["admission"][claim] is not True:
        raise ValueError(f"resource audit does not admit claim: {claim}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-root", type=Path,
                        help="Explicit frozen source tree for a historical audit; live source drift remains rejected")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--output", type=Path)
    group.add_argument("--check", type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve(), args.source_root.resolve() if args.source_root else None)
    if args.check and not same_typed(json.loads(args.check.read_text()), result):
        raise ValueError("stored resource audit differs from current audited evidence")
    if args.output:
        if args.output.exists():
            raise FileExistsError("fresh resource-audit output required")
        atomic_write_json(args.output, result)
    print(json.dumps({"status": result["status"], "interface_counts": result["interface_counts"],
                      "admission": result["admission"]}, sort_keys=True))


if __name__ == "__main__":
    main()
