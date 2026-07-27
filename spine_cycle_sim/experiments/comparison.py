"""Execution and result contracts for the shared normalized comparison matrix."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from spine_cycle_sim.profiles import ArchitectureProfile, load_architecture_profile
from spine_cycle_sim.experiments.profile_capabilities import load_capability_catalog
from spine_cycle_sim.experiments.feasibility import load_normalized_hls_feasibility


SYSTEMS = ("spine", "grasu_regraph")

NORMALIZED_SPINE_PROFILE_ID = "spine_candidate10_normalized_v1"
NORMALIZED_SPINE_PARENT_ID = "spine_candidate10_one_pass_1e61fc0"
NORMALIZED_SPINE_MAINTENANCE = "candidate10_one_pass"
NORMALIZED_SPINE_AXI = "candidate10_gmem_1e61fc0"
NORMALIZED_CLOCK_MHZ = 150.0
NORMALIZED_HBM_CLOCK_MHZ = 450.0
NORMALIZED_HBM_BUDGET = 23

_CANDIDATE10_PROTECTED_PARAMETERS = (
    "maintenance_architecture",
    "axi_profile",
    "partitions",
    "hot_shards",
    "families",
    "levels",
    "level_ratio",
    "vertex_partition_size",
    "tile_vertices",
    "tiny_active_threshold",
    "split_compute_width",
    "graph_hbm_channels",
    "hbm_pseudo_channels_used",
    "sorted_edges_hbm_channel",
    "vertex_state_hbm_channel",
    "active_bins_hbm_channel",
    "active_out_hbm_channel",
    "metadata_hbm_channel",
    "result_hbm_channel",
    "active_bitmap_hbm_channel",
    "metadata_format_version",
    "result_layout_version",
    "classification_block_edges",
    "publication_distinct_word_window",
    "publication_source_prefetch_records",
    "publication_base_cycles",
    "publication_source_cycles",
    "publication_group_cycles",
    "publication_new_bit_cycles",
    "publication_prefetch_restart_cycles",
    "publication_empty_base_cycles",
    "publication_empty_group_cycles",
    "publication_full_window_rebate_cycles",
    "publication_next_window_overlap_cycles",
    "l0_writer_rtl_schedule",
    "l0_writer_base_residual_cycles",
    "l0_writer_single_record_cycles",
    "l0_writer_late_source_cycles",
    "l0_writer_packer_cycles",
    "l0_writer_page_tail_cycles",
    "zero_edge_control_min_cycles",
    "hbm16_input_base_bytes",
    "hbm16_dirty_bitmap_base_bytes",
    "hbm16_dirty_list_base_bytes",
    "hbm16_family_directory_base_bytes",
    "hbm16_dispatch_bucket_base_bytes",
    "hbm16_total_bytes",
)


@dataclass(frozen=True)
class RunInvocation:
    run_id: str
    system: str
    command: tuple[str, ...]
    out_dir: Path
    profile_path: Path | None = None
    profile_id: str | None = None
    profile_sha256: str | None = None
    expected_spine_maintenance: str | None = None
    expected_spine_axi: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_grasu_profile_paths(
    root: Path, profile_set: str = "v2"
) -> tuple[Path, ...]:
    profile_dir = root / "configs" / "architectures"
    if profile_set == "hls_v3":
        return (
            profile_dir
            / "grasu_regraph_candidate10_normalized_hls_weighted_v3.json",
            profile_dir
            / "grasu_regraph_candidate10_normalized_hls_pagerank_v3.json",
            profile_dir
            / "grasu_regraph_candidate10_normalized_hls_residual_pagerank_v3.json",
        )
    if profile_set == "k1_v4":
        return (
            profile_dir
            / "grasu_regraph_candidate10_k1_multipart_weighted_v4.json",
            profile_dir
            / "grasu_regraph_candidate10_k1_multipart_pagerank_v4.json",
            profile_dir
            / "grasu_regraph_candidate10_k1_multipart_residual_v4.json",
        )
    if profile_set != "v2":
        raise ValueError(f"unknown normalized GraSU profile set: {profile_set}")
    return (
        profile_dir / "grasu_regraph_candidate10_normalized_weighted_v2.json",
        profile_dir / "grasu_regraph_candidate10_normalized_pagerank_v2.json",
        profile_dir
        / "grasu_regraph_candidate10_normalized_residual_pagerank_v2.json",
    )


def normalized_grasu_capability_catalog_path(
    root: Path, profile_set: str = "v2"
) -> Path:
    filename = (
        "grasu_regraph_k1_multipart_capabilities_v4.json"
        if profile_set == "k1_v4"
        else "grasu_regraph_candidate10_hls_capabilities_v3.json"
        if profile_set == "hls_v3"
        else "grasu_regraph_candidate10_capabilities_v2.json"
        if profile_set == "v2"
        else None
    )
    if filename is None:
        raise ValueError(f"unknown normalized GraSU profile set: {profile_set}")
    return root / "configs" / "contracts" / filename


def normalized_profile_set(manifest: Mapping[str, object]) -> str:
    contract = manifest.get("comparison_contract")
    if not isinstance(contract, Mapping):
        raise ValueError("comparison manifest lacks its platform contract")
    profile_set = str(contract.get("grasu_profile_set", "v2"))
    if profile_set not in {"v2", "hls_v3", "k1_v4"}:
        raise ValueError(f"unsupported manifest GraSU profile set: {profile_set}")
    return profile_set


def _clock(profile: ArchitectureProfile, name: str) -> float:
    try:
        return profile.clock(name).achieved_mhz
    except KeyError as error:
        raise ValueError(
            f"normalized profile {profile.profile_id} lacks {name} clock"
        ) from error


def validate_normalized_profile_contract(
    spine_profile_path: Path,
    grasu_profile_paths: Sequence[Path],
) -> dict[str, object]:
    """Reject silent architecture drift before a normalized matrix starts."""

    spine_path = spine_profile_path.resolve()
    repository_root = spine_path.parents[2]
    spine = load_architecture_profile(spine_path)
    if spine.profile_id != NORMALIZED_SPINE_PROFILE_ID:
        raise ValueError(
            "normalized comparison requires explicit Candidate10-derived Spine "
            f"profile {NORMALIZED_SPINE_PROFILE_ID}, got {spine.profile_id}"
        )
    required_spine = {
        "comparison_role": "normalized",
        "native_parent_profile": NORMALIZED_SPINE_PARENT_ID,
        "maintenance_architecture": NORMALIZED_SPINE_MAINTENANCE,
        "axi_profile": NORMALIZED_SPINE_AXI,
        "normalization_policy": (
            "shared_platform_claim_only_no_microarchitecture_change"
        ),
        "hbm_pseudo_channels_budget": NORMALIZED_HBM_BUDGET,
    }
    for key, expected in required_spine.items():
        if spine.parameters.get(key) != expected:
            raise ValueError(
                f"normalized Spine profile has {key}={spine.parameters.get(key)!r}; "
                f"expected {expected!r}"
            )

    parent_path = spine_path.with_name(f"{NORMALIZED_SPINE_PARENT_ID}.json")
    parent = load_architecture_profile(parent_path)
    parent_digest = sha256_file(parent_path)
    if spine.parameters.get("native_parent_profile_sha256") != parent_digest:
        raise ValueError("normalized Spine native-parent SHA-256 is stale")
    if spine.source != parent.source:
        raise ValueError("normalized Spine source identity differs from its native parent")
    for key in _CANDIDATE10_PROTECTED_PARAMETERS:
        if key not in parent.parameters or spine.parameters.get(key) != parent.parameters[key]:
            raise ValueError(
                f"normalized Spine silently changes protected Candidate10 parameter {key}"
            )

    if _clock(spine, "data") != NORMALIZED_CLOCK_MHZ:
        raise ValueError("normalized Spine data clock is not 150 MHz")
    if _clock(spine, "hbm") != NORMALIZED_HBM_CLOCK_MHZ:
        raise ValueError("normalized Spine HBM clock is not 450 MHz")

    grasu_profiles = tuple(
        load_architecture_profile(path.resolve()) for path in grasu_profile_paths
    )
    if len(grasu_profiles) != 3 or len(
        {profile.profile_id for profile in grasu_profiles}
    ) != 3:
        raise ValueError("normalized comparison requires three distinct GraSU profiles")
    profile_ids = tuple(profile.profile_id for profile in grasu_profiles)
    v2_ids = tuple(
        path.stem for path in normalized_grasu_profile_paths(repository_root, "v2")
    )
    v3_ids = tuple(
        path.stem
        for path in normalized_grasu_profile_paths(repository_root, "hls_v3")
    )
    v4_ids = tuple(
        path.stem
        for path in normalized_grasu_profile_paths(repository_root, "k1_v4")
    )
    if profile_ids == v2_ids:
        profile_set = "v2"
        feasibility_path = (
            repository_root
            / "configs"
            / "contracts"
            / "candidate10_normalized_hls_feasibility_v1.json"
        )
    elif profile_ids == v3_ids:
        profile_set = "hls_v3"
        feasibility_path = (
            repository_root
            / "configs"
            / "contracts"
            / "candidate10_normalized_hls_feasibility_v2.json"
        )
    elif profile_ids == v4_ids:
        profile_set = "k1_v4"
        feasibility_path = (
            repository_root
            / "configs"
            / "contracts"
            / "candidate10_k1_multipart_hls_feasibility_v3.json"
        )
    else:
        raise ValueError("normalized comparison uses an unknown GraSU profile set")

    for profile in grasu_profiles:
        checks = {
            "architecture": profile.architecture == "grasu_regraph",
            "comparison_role": profile.parameters.get("comparison_role")
            == "normalized",
            "resource_reference_profile": profile.parameters.get(
                "resource_reference_profile"
            )
            == spine.profile_id,
            "hbm_budget": profile.parameters.get("hbm_pseudo_channels_budget")
            == NORMALIZED_HBM_BUDGET,
            "conversion_free": profile.parameters.get("conversion_cost_included")
            is False,
            "pma_native": profile.parameters.get("pma_native_compute") is True,
            "memory_backend": profile.memory.backend == spine.memory.backend,
            "memory_channels": profile.memory.channels == spine.memory.channels,
            "memory_capacity": profile.memory.channel_capacity_bytes
            == spine.memory.channel_capacity_bytes,
            "memory_width": profile.memory.data_width_bits
            == spine.memory.data_width_bits,
            "memory_burst": profile.memory.max_burst_bytes
            == spine.memory.max_burst_bytes,
            "kernel_clock": _clock(profile, "kernel") == NORMALIZED_CLOCK_MHZ,
            "hbm_clock": _clock(profile, "hbm") == NORMALIZED_HBM_CLOCK_MHZ,
        }
        failed = sorted(name for name, passed in checks.items() if not passed)
        if failed:
            raise ValueError(
                f"normalized GraSU profile {profile.profile_id} violates: "
                + ", ".join(failed)
            )

    if profile_set in {"hls_v3", "k1_v4"}:
        for profile in grasu_profiles:
            hls_checks = {
                "outstanding_16": profile.memory.max_outstanding_per_port == 16,
                "full_word_abi": profile.parameters.get("grasu_pma_edge_abi")
                == "regraph_weighted32_full_word_compare_dst19_weight12",
                "eight_lanes": profile.parameters.get("regraph_map_reduce_lanes")
                == 8,
                "hls_foundation": bool(
                    profile.parameters.get("hls_foundation_profile")
                ),
            }
            failed = sorted(name for name, passed in hls_checks.items() if not passed)
            if failed:
                raise ValueError(
                    f"HLS-derived profile {profile.profile_id} violates: "
                    + ", ".join(failed)
                )
        for profile in grasu_profiles[1:]:
            if profile.parameters.get("pagerank_degree_update_timing") is not True:
                raise ValueError(
                    f"HLS-derived PageRank profile omits degree RMW: {profile.profile_id}"
                )
        if profile_set == "k1_v4":
            for profile in grasu_profiles:
                k_checks = {
                    "compute_pipelines": profile.parameters.get(
                        "regraph_compute_pipelines"
                    )
                    == 1,
                    "partition_capacity": profile.parameters.get(
                        "regraph_destination_partitions"
                    )
                    == 16,
                    "finite_dispatch": profile.parameters.get(
                        "regraph_partition_execution"
                    )
                    == "finite_work_conserving_serial_k1",
                }
                failed = sorted(
                    name for name, passed in k_checks.items() if not passed
                )
                if failed:
                    raise ValueError(
                        f"K1 multi-partition profile {profile.profile_id} violates: "
                        + ", ".join(failed)
                    )

    catalog_path = normalized_grasu_capability_catalog_path(
        repository_root, profile_set
    )
    catalog = load_capability_catalog(catalog_path)
    required_algorithms = (
        (grasu_profiles[0].profile_id, ("weighted_sssp", "weighted_dynamic_sssp")),
        (grasu_profiles[1].profile_id, ("full_pagerank",)),
        (
            grasu_profiles[2].profile_id,
            ("thresholded_residual_pagerank",),
        ),
    )
    for profile_id, algorithms in required_algorithms:
        capability_profile = catalog.profile(profile_id)
        for algorithm in algorithms:
            capability = capability_profile.require(algorithm)
            expected_evidence_tier = (
                "synthesis_only" if profile_set == "k1_v4" else "simulation_only"
            )
            if (
                capability.implementation_status.value != "executable"
                or capability.evidence_tier != expected_evidence_tier
            ):
                raise ValueError(
                    f"normalized capability is not executable: {profile_id}/{algorithm}"
                )

    hls_feasibility = load_normalized_hls_feasibility(
        repository_root, feasibility_path
    )

    return {
        "claim_class": hls_feasibility["claim_gates"][
            "structural_exploratory"
        ]["label"],
        "grasu_profile_set": profile_set,
        "spine_profile_id": spine.profile_id,
        "spine_profile_sha256": spine.manifest_sha256,
        "native_parent_profile_id": parent.profile_id,
        "native_parent_profile_sha256": parent_digest,
        "grasu_profile_ids": [profile.profile_id for profile in grasu_profiles],
        "grasu_capability_catalog_id": catalog.catalog_id,
        "grasu_capability_catalog_sha256": sha256_file(catalog_path),
        "clock_mhz": NORMALIZED_CLOCK_MHZ,
        "hbm_clock_mhz": NORMALIZED_HBM_CLOCK_MHZ,
        "physical_hbm_channels": spine.memory.channels,
        "hbm_pseudo_channels_budget": NORMALIZED_HBM_BUDGET,
        "matching_hls_gate": hls_feasibility,
    }


def implementation_fingerprint(paths: Iterable[Path]) -> dict[str, object]:
    files: list[dict[str, str]] = []
    for path in sorted({item.resolve() for item in paths}, key=str):
        if not path.is_file():
            raise ValueError(f"comparison implementation input is missing: {path}")
        files.append({"path": str(path), "sha256": sha256_file(path)})
    digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return {"sha256": digest, "files": files}


def artifact_path(root: Path, artifact: Mapping[str, object]) -> Path:
    path = (root / str(artifact["path"])).resolve()
    if not path.is_file() or sha256_file(path) != artifact["sha256"]:
        raise ValueError(f"shared comparison artifact is missing or changed: {path}")
    return path


def select_runs(
    manifest: Mapping[str, object],
    *,
    roles: Sequence[str] = (),
    algorithms: Sequence[str] = (),
    run_ids: Sequence[str] = (),
    limit: int | None = None,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for raw_run in manifest["runs"]:  # type: ignore[index]
        run = dict(raw_run)
        if roles and run["role"] not in roles:
            continue
        if algorithms and run["algorithm"] not in algorithms:
            continue
        if run_ids and run["run_id"] not in run_ids:
            continue
        selected.append(run)
    if limit is not None:
        if limit <= 0:
            raise ValueError("run limit must be positive")
        selected = selected[:limit]
    if not selected:
        raise ValueError("shared comparison selection is empty")
    return selected


def _spine_scenario(run: Mapping[str, object]) -> str:
    algorithm = str(run["algorithm"])
    if algorithm == "weighted_sssp":
        return "weighted_sssp"
    if algorithm == "weighted_dynamic_sssp":
        scenario = str(run["scenario"])
        if scenario == "incremental_insert":
            return "dynamic_sssp"
        if scenario == "full_rebuild_increase":
            return "dynamic_sssp_increase"
        return "dynamic_sssp_delete"
    if algorithm == "full_pagerank":
        return "full_pagerank"
    if algorithm == "thresholded_residual_pagerank":
        return "residual_pagerank"
    raise ValueError(f"unsupported shared algorithm: {algorithm}")


def build_invocation(
    root: Path,
    run: Mapping[str, object],
    *,
    system: str,
    output_root: Path,
    python: str,
    sst: Path,
    lib_dir: Path,
    spine_profile: Path,
    grasu_profile_paths: Sequence[Path] | None = None,
    grasu_capability_catalog: Path | None = None,
) -> RunInvocation:
    if system not in SYSTEMS:
        raise ValueError(f"unsupported comparison system: {system}")
    run_id = str(run["run_id"])
    out_dir = (output_root / run_id / system).resolve()
    graph = artifact_path(root, run["graph"])  # type: ignore[arg-type]
    algorithm = str(run["algorithm"])
    selected_grasu_profiles = tuple(
        path.resolve()
        for path in (
            grasu_profile_paths
            if grasu_profile_paths is not None
            else normalized_grasu_profile_paths(root, "v2")
        )
    )
    if system == "spine":
        profile_path = spine_profile.resolve()
    elif algorithm in {"weighted_sssp", "weighted_dynamic_sssp"}:
        profile_path = selected_grasu_profiles[0]
    elif algorithm == "full_pagerank":
        profile_path = selected_grasu_profiles[1]
    else:
        profile_path = selected_grasu_profiles[2]
    profile = load_architecture_profile(profile_path)
    common = [
        python,
        "",
        "--out-dir",
        str(out_dir),
        "--sst",
        str(sst.resolve()),
        "--lib-dir",
        str(lib_dir.resolve()),
        "--no-build",
    ]
    if system == "spine":
        common[1] = str(root / "scripts" / "run_sst_spine_vertical.py")
        command = common + [
            "--scenario",
            _spine_scenario(run),
            "--validation-mode",
            "generic",
            "--profile",
            str(profile_path),
            "--workload",
            str(graph),
            "--source",
            str(run.get("source", 0)),
            "--max-cycles",
            "100000000",
            "--max-rounds",
            str(run.get("max_rounds", 256)),
        ]
        if algorithm == "weighted_dynamic_sssp":
            update = artifact_path(root, run["update"])  # type: ignore[arg-type]
            command.extend(("--update-workload", str(update)))
        elif algorithm == "full_pagerank":
            command.extend(
                (
                    "--pagerank-iterations",
                    str(run["iterations"]),
                    "--pagerank-damping",
                    str(run["damping"]),
                )
            )
        elif algorithm == "thresholded_residual_pagerank":
            command.extend(
                (
                    "--pagerank-damping",
                    str(run["damping"]),
                    "--pagerank-epsilon",
                    str(run["epsilon"]),
                    "--residual-max-iterations",
                    str(run["max_iterations"]),
                )
            )
    elif algorithm in {"weighted_sssp", "weighted_dynamic_sssp"}:
        update = artifact_path(root, run["update"])  # type: ignore[arg-type]
        hls_derived = profile.profile_id.endswith("_hls_weighted_v3")
        common[1] = str(
            root
            / "scripts"
            / (
                "run_sst_grasu_regraph_hls_weighted.py"
                if hls_derived
                else "run_sst_grasu_regraph.py"
            )
        )
        command = common + [
            "--profile",
            str(profile_path),
            "--workload",
            str(graph),
            "--update-workload",
            str(update),
            "--source",
            str(run.get("source", 0)),
            "--max-cycles",
            "100000000",
        ]
        if hls_derived:
            if grasu_capability_catalog is None:
                raise ValueError("HLS-derived invocation lacks capability catalog")
            command.extend(
                ("--capability-catalog", str(grasu_capability_catalog.resolve()))
            )
        else:
            command.extend(("--max-rounds", str(run.get("max_rounds", 256))))
    elif algorithm == "full_pagerank":
        hls_derived = profile.profile_id.endswith("_hls_pagerank_v3")
        common[1] = str(
            root
            / "scripts"
            / (
                "run_sst_grasu_regraph_hls_pagerank.py"
                if hls_derived
                else "run_sst_grasu_regraph_pagerank.py"
            )
        )
        command = common + [
            "--profile",
            str(profile_path),
            "--workload",
            str(graph),
            "--max-cycles",
            "100000000",
        ]
        if hls_derived:
            if grasu_capability_catalog is None:
                raise ValueError("HLS-derived invocation lacks capability catalog")
            update = artifact_path(root, run["update"])  # type: ignore[arg-type]
            command.extend(
                (
                    "--update-workload",
                    str(update),
                    "--capability-catalog",
                    str(grasu_capability_catalog.resolve()),
                )
            )
            if (
                int(profile.parameters["pagerank_iterations"])
                != int(run["iterations"])
                or abs(
                    float(profile.parameters["pagerank_damping"])
                    - float(run["damping"])
                )
                > 1.0e-9
            ):
                raise ValueError("HLS-derived PageRank run differs from its profile")
        else:
            command.extend(
                (
                    "--iterations",
                    str(run["iterations"]),
                    "--damping",
                    str(run["damping"]),
                )
            )
    else:
        hls_derived = profile.profile_id.endswith("_hls_residual_pagerank_v3")
        common[1] = str(
            root
            / "scripts"
            / (
                "run_sst_grasu_regraph_hls_residual_pagerank.py"
                if hls_derived
                else "run_sst_grasu_regraph_residual_pagerank.py"
            )
        )
        command = common + [
            "--profile",
            str(profile_path),
            "--workload",
            str(graph),
            "--max-cycles",
            "100000000",
        ]
        if hls_derived:
            if grasu_capability_catalog is None:
                raise ValueError("HLS-derived invocation lacks capability catalog")
            update = artifact_path(root, run["update"])  # type: ignore[arg-type]
            command.extend(
                (
                    "--update-workload",
                    str(update),
                    "--capability-catalog",
                    str(grasu_capability_catalog.resolve()),
                )
            )
            residual_parameters = (
                ("pagerank_damping", "damping"),
                ("pagerank_epsilon", "epsilon"),
                ("pagerank_residual_max_iterations", "max_iterations"),
            )
            if any(
                abs(
                    float(profile.parameters[profile_key])
                    - float(run[run_key])
                )
                > 1.0e-9
                for profile_key, run_key in residual_parameters
            ):
                raise ValueError("HLS-derived residual run differs from its profile")
        else:
            command.extend(
                (
                    "--damping",
                    str(run["damping"]),
                    "--epsilon",
                    str(run["epsilon"]),
                    "--max-iterations",
                    str(run["max_iterations"]),
                )
            )
    return RunInvocation(
        run_id,
        system,
        tuple(command),
        out_dir,
        profile_path=profile_path,
        profile_id=profile.profile_id,
        profile_sha256=profile.manifest_sha256,
        expected_spine_maintenance=(
            str(profile.parameters.get("maintenance_architecture", "shared_engine_serial"))
            if system == "spine"
            else None
        ),
        expected_spine_axi=(
            str(profile.parameters.get("axi_profile", "hls_split_9c08763"))
            if system == "spine"
            else None
        ),
    )


def expected_oracles(algorithm: str) -> tuple[str, str]:
    if algorithm in {"weighted_sssp", "weighted_dynamic_sssp"}:
        return "synchronous_frontier_uint32", "uint64_dijkstra"
    if algorithm == "full_pagerank":
        return "iterative_float32", "iterative_float64"
    if algorithm == "thresholded_residual_pagerank":
        return (
            "thresholded_residual_float32",
            "full_pagerank_float64_200_iterations",
        )
    raise ValueError(f"unsupported algorithm: {algorithm}")


def load_system_result(
    invocation: RunInvocation,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    if invocation.system == "spine":
        summary_path = invocation.out_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        result = dict(summary)
        dram = {
            "channels": summary.get("dram_channels"),
            "reads": summary.get("dram_reads"),
            "writes": summary.get("dram_writes"),
            "activates": summary.get("dram_activates"),
            "precharges": summary.get("dram_precharges"),
            "total_energy_pj": summary.get("dram_total_energy_pj"),
        }
        binding = dict(summary["sst_memory_binding"])
    else:
        manifest_path = invocation.out_dir / "manifest.json"
        child = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = dict(child["result"])
        child_profile_path = Path(str(child.get("profile", ""))).resolve()
        child_profile_sha256 = child.get("profile_sha256")
        child_profile_id: str | None = None
        if child_profile_path.is_file():
            child_profile_id = load_architecture_profile(child_profile_path).profile_id
        result["architecture_profile_path"] = str(child_profile_path)
        result["architecture_profile_sha256"] = child_profile_sha256
        result["architecture_profile_id"] = child_profile_id
        dram = dict(child["dram"])
        binding = dict(child["sst_memory_binding"])
    return result, dram, binding


def validate_system_result(
    run: Mapping[str, object],
    invocation: RunInvocation,
    result: Mapping[str, object],
    dram: Mapping[str, object],
    binding: Mapping[str, object],
    *,
    expected_clock_mhz: float = 150.0,
) -> list[str]:
    architecture_oracle, mathematical_oracle = expected_oracles(
        str(run["algorithm"])
    )
    expected_vertices = int(run["graph"]["vertices"])  # type: ignore[index]
    expected_edges = int(run["graph"]["records"])  # type: ignore[index]
    result_edges_key = (
        "input_edges" if invocation.system == "spine" else "initial_edges"
    )
    physical_channels = int(binding.get("physical_channels", -1))
    instantiated_channels = binding.get("instantiated_channels")
    reachable_channels = binding.get("reachable_channels")
    instantiated = (
        tuple(int(channel) for channel in instantiated_channels)
        if isinstance(instantiated_channels, list)
        else ()
    )
    reachable = (
        tuple(int(channel) for channel in reachable_channels)
        if isinstance(reachable_channels, list)
        else ()
    )
    arbitration_value = result.get("backend_arbitration")
    arbitration = (
        arbitration_value if isinstance(arbitration_value, Mapping) else {}
    )
    backend_requests = result.get("backend_requests")
    problems: list[str] = []
    checks = {
        "success": result.get("success") is True,
        "architecture_correctness": result.get(
            "architecture_correctness_mismatches"
        )
        == 0,
        "mathematical_correctness": result.get(
            "mathematical_correctness_mismatches"
        )
        == 0,
        "combined_correctness": result.get("correctness_mismatches") == 0,
        "architecture_oracle": result.get("architecture_oracle")
        == architecture_oracle,
        "mathematical_oracle": result.get("mathematical_oracle")
        == mathematical_oracle,
        "clock": abs(float(result.get("core_mhz", -1.0)) - expected_clock_mhz)
        < 1.0e-9,
        "profile_path": invocation.profile_path is not None
        and Path(str(result.get("architecture_profile_path", ""))).resolve()
        == invocation.profile_path,
        "profile_id": result.get("architecture_profile_id")
        == invocation.profile_id,
        "profile_sha256": result.get("architecture_profile_sha256")
        == invocation.profile_sha256,
        "vertices": result.get("vertices") == expected_vertices,
        "edges": result.get(result_edges_key) == expected_edges,
        "physical_hbm_channels": physical_channels == 32,
        "bound_dram_channels": dram.get("channels") == len(instantiated),
        "binding_nonempty": bool(instantiated),
        "binding_range": all(
            0 <= channel < physical_channels for channel in instantiated
        ),
        "binding_unique": tuple(sorted(set(instantiated))) == instantiated,
        "binding_reachability": bool(reachable)
        and set(reachable).issubset(instantiated),
        "binding_channel_numbers": binding.get("channel_numbers_preserved") is True,
        "binding_fail_closed": binding.get("unbound_request_policy") == "fatal",
        "dram_closure": int(dram.get("reads", -1))
        + int(dram.get("writes", -1))
        == backend_requests,
        "registered_arbitration_present": bool(arbitration),
        "registered_arbitration_policy": arbitration.get("policy")
        == "registered_round_robin_per_pseudo_channel",
        "registered_arbitration_ledger": arbitration.get("ledger_closed")
        is True,
        "registered_arbitration_requests": arbitration.get("unique_intents")
        == backend_requests
        and arbitration.get("grants") == backend_requests
        and arbitration.get("consumed_grants") == backend_requests,
        "registered_arbitration_drained": arbitration.get("pending_intents")
        == 0
        and arbitration.get("pending_grants") == 0,
    }
    if invocation.system == "spine":
        checks["spine_maintenance_architecture"] = (
            result.get("spine_maintenance_architecture")
            == invocation.expected_spine_maintenance
        )
        checks["spine_axi_profile"] = (
            result.get("spine_axi_profile") == invocation.expected_spine_axi
        )
        maintenance_start = int(result.get("maintenance_start_cycle", -1))
        maintenance_end = int(result.get("maintenance_end_cycle", -1))
        first_issue = int(result.get("maintenance_first_memory_issue_cycle", -1))
        last_completion = int(
            result.get("maintenance_last_memory_completion_cycle", -1)
        )
        launch_cycles = int(
            result.get("maintenance_launch_to_first_memory_issue_cycles", -1)
        )
        active_span_cycles = int(
            result.get("maintenance_memory_active_span_cycles", -1)
        )
        drain_cycles = int(
            result.get("maintenance_post_memory_drain_cycles", -1)
        )
        checks["spine_maintenance_memory_ledger"] = (
            result.get("maintenance_memory_ledger_closed") is True
        )
        checks["spine_maintenance_timing_ledger"] = (
            maintenance_start <= first_issue <= last_completion <= maintenance_end
            and launch_cycles == first_issue - maintenance_start
            and active_span_cycles == last_completion - first_issue
            and drain_cycles == maintenance_end - last_completion
            and launch_cycles + active_span_cycles + drain_cycles
            == maintenance_end - maintenance_start
        )
    if str(run["algorithm"]) == "weighted_dynamic_sssp":
        expected_updates = int(run["update"]["records"])  # type: ignore[index]
        checks["updates"] = (
            result.get("update_edges") == expected_updates
            if invocation.system == "spine"
            else result.get(
                "logical_updates"
                if invocation.profile_id
                in {
                    "grasu_regraph_candidate10_normalized_hls_weighted_v3",
                    "grasu_regraph_candidate10_k1_multipart_weighted_v4",
                }
                else "updates"
            )
            == expected_updates
        )
    for name, passed in checks.items():
        if not passed:
            problems.append(name)
    return problems


def result_row(
    run: Mapping[str, object],
    invocation: RunInvocation,
    result: Mapping[str, object],
    dram: Mapping[str, object],
    binding: Mapping[str, object],
    *,
    wall_seconds: float,
) -> dict[str, object]:
    cycles = int(result["cycles"])
    core_mhz = float(result["core_mhz"])
    arbitration = result["backend_arbitration"]
    if not isinstance(arbitration, Mapping):
        raise TypeError("validated backend arbitration must be an object")
    return {
        "run_id": invocation.run_id,
        "fixture_id": run["fixture_id"],
        "dataset_kind": run["dataset_kind"],
        "role": run["role"],
        "algorithm": run["algorithm"],
        "system": invocation.system,
        "claim_class": result.get("claim_class", "normalized_structural_simulation"),
        "architecture_profile_id": result["architecture_profile_id"],
        "architecture_profile_sha256": result["architecture_profile_sha256"],
        "cycles": cycles,
        "core_mhz": core_mhz,
        "simulated_ms": cycles / (core_mhz * 1000.0),
        "wall_seconds": wall_seconds,
        "vertices": result["vertices"],
        "input_edges": run["graph"]["records"],  # type: ignore[index]
        "updates": run.get("update", {}).get("records", 0),  # type: ignore[union-attr]
        "backend_requests": result["backend_requests"],
        "maintenance_launch_to_first_memory_issue_cycles": result.get(
            "maintenance_launch_to_first_memory_issue_cycles", ""
        ),
        "maintenance_memory_active_span_cycles": result.get(
            "maintenance_memory_active_span_cycles", ""
        ),
        "maintenance_post_memory_drain_cycles": result.get(
            "maintenance_post_memory_drain_cycles", ""
        ),
        "maintenance_memory_ledger_closed": result.get(
            "maintenance_memory_ledger_closed", ""
        ),
        "backend_arbitration_request_waits": arbitration["request_waits"],
        "backend_arbitration_contended_cycles": arbitration[
            "contended_cycles"
        ],
        "backend_arbitration_contention_losers": arbitration[
            "contention_losers"
        ],
        "backend_arbitration_capacity_blocked_cycles": arbitration[
            "capacity_blocked_cycles"
        ],
        "backend_arbitration_max_contenders": arbitration["max_contenders"],
        "dram_reads": dram["reads"],
        "dram_writes": dram["writes"],
        "dram_activates": dram.get("activates", 0),
        "dram_precharges": dram.get("precharges", 0),
        "dram_total_energy_pj": dram.get("total_energy_pj", 0.0),
        "physical_hbm_channels": binding["physical_channels"],
        "bound_dram_channels": len(binding["instantiated_channels"]),
        "instantiated_hbm_channels": ",".join(
            str(channel) for channel in binding["instantiated_channels"]
        ),
        "dram_energy_claim": binding["dram_energy_claim"],
        "architecture_correctness_mismatches": result[
            "architecture_correctness_mismatches"
        ],
        "mathematical_correctness_mismatches": result[
            "mathematical_correctness_mismatches"
        ],
    }


def pair_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    claim_label: str = "candidate10_derived_normalized_structural_execution_driven",
) -> list[dict[str, object]]:
    by_run: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in rows:
        by_run.setdefault(str(row["run_id"]), {})[str(row["system"])] = row
    paired: list[dict[str, object]] = []
    for run_id in sorted(by_run):
        systems = by_run[run_id]
        if set(systems) != set(SYSTEMS):
            continue
        spine = systems["spine"]
        grasu = systems["grasu_regraph"]
        if float(spine["core_mhz"]) != float(grasu["core_mhz"]):
            raise ValueError(f"normalized pair has mismatched clocks: {run_id}")
        paired.append(
            {
                "run_id": run_id,
                "fixture_id": spine["fixture_id"],
                "dataset_kind": spine["dataset_kind"],
                "role": spine["role"],
                "algorithm": spine["algorithm"],
                "spine_cycles": spine["cycles"],
                "grasu_regraph_cycles": grasu["cycles"],
                "spine_simulated_ms": spine["simulated_ms"],
                "grasu_regraph_simulated_ms": grasu["simulated_ms"],
                "spine_speedup_over_grasu": float(grasu["cycles"])
                / float(spine["cycles"]),
                "claim_label": claim_label,
            }
        )
    return paired
