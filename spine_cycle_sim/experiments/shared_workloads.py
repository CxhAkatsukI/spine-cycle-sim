"""Frozen workloads for normalized Spine versus GraSU/ReGraph comparisons."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
from typing import Iterable, Iterator, Mapping, Sequence


MAX_NORMALIZED_VERTICES = 65_536
DEFAULT_REAL_SOURCES: tuple[tuple[str, str], ...] = (
    ("amazon_2008", "amazon-2008.mtx"),
    ("web_google", "web-Google.mtx"),
    ("soc_flickr_und", "soc-flickr-und.mtx"),
)


@dataclass(frozen=True, order=True)
class SliceRecord:
    src: int
    dst: int
    weight: int = 1
    diff: int = 1


@dataclass(frozen=True)
class SliceGraph:
    case_id: str
    vertices: int
    records: tuple[SliceRecord, ...]


@dataclass(frozen=True)
class SyntheticFixture:
    fixture_id: str
    role: str
    family: str
    graph: SliceGraph
    dynamic_update: SliceGraph | None = None
    dynamic_path: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slice_text(graph: SliceGraph) -> str:
    lines = [
        "# spine_real_slice_version=1",
        f"# case={graph.case_id}",
        f"# vertices={graph.vertices}",
        "# columns=src dst weight diff",
    ]
    lines.extend(
        f"{edge.src} {edge.dst} {edge.weight} {edge.diff}"
        for edge in graph.records
    )
    return "\n".join(lines) + "\n"


def write_slice(path: Path, graph: SliceGraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_slice_text(graph), encoding="ascii")


def load_slice(path: Path) -> SliceGraph:
    case_id = path.stem
    vertices: int | None = None
    records: list[SliceRecord] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="ascii").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            metadata = line[1:].strip()
            if metadata.startswith("case="):
                case_id = metadata.split("=", 1)[1].strip()
            elif metadata.startswith("vertices="):
                vertices = int(metadata.split("=", 1)[1])
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(f"{path}:{line_number}: expected four edge fields")
        records.append(SliceRecord(*(int(field) for field in fields)))
    if vertices is None:
        raise ValueError(f"{path}: missing vertices metadata")
    return SliceGraph(case_id, vertices, tuple(records))


def _edge(src: int, dst: int, salt: int = 0) -> SliceRecord:
    weight = 1 + ((src * 131 + dst * 17 + salt * 29) % 31)
    return SliceRecord(src, dst, weight, 1)


def _graph(case_id: str, vertices: int, edges: Iterable[SliceRecord]) -> SliceGraph:
    return SliceGraph(case_id, vertices, tuple(sorted(set(edges))))


def _chain(case_id: str, vertices: int, salt: int) -> SliceGraph:
    return _graph(
        case_id,
        vertices,
        (_edge(vertex, vertex + 1, salt) for vertex in range(vertices - 1)),
    )


def _star(case_id: str, edge_count: int, salt: int) -> SliceGraph:
    return _graph(
        case_id,
        edge_count + 1,
        (_edge(0, destination, salt) for destination in range(1, edge_count + 1)),
    )


def _source_window(case_id: str, edge_count: int, salt: int) -> SliceGraph:
    vertices = 2 * edge_count + 1
    return _graph(
        case_id,
        vertices,
        (
            _edge(source, edge_count + 1 + ((source * 17) % edge_count), salt)
            for source in range(edge_count)
        ),
    )


def _spread(case_id: str) -> SliceGraph:
    vertices = 256
    edges = {_edge(vertex, (vertex + 1) % vertices, 5) for vertex in range(vertices)}
    rng = random.Random(20260725)
    while len(edges) < 512:
        src = rng.randrange(vertices)
        dst = rng.randrange(vertices)
        if src != dst:
            edges.add(_edge(src, dst, 5))
    return _graph(case_id, vertices, edges)


def _dynamic_fixture(
    fixture_id: str,
    role: str,
    family: str,
    edges: Sequence[tuple[int, int, int]],
    updates: Sequence[tuple[int, int, int, int]],
    dynamic_path: str,
    vertices: int,
) -> SyntheticFixture:
    graph = _graph(
        fixture_id,
        vertices,
        (SliceRecord(src, dst, weight, 1) for src, dst, weight in edges),
    )
    update = SliceGraph(
        f"{fixture_id}_update",
        vertices,
        tuple(SliceRecord(*record) for record in updates),
    )
    return SyntheticFixture(
        fixture_id, role, family, graph, update, dynamic_path
    )


def synthetic_fixtures() -> tuple[SyntheticFixture, ...]:
    diamond = _graph(
        "syn_weighted_diamond_v8",
        8,
        (
            SliceRecord(0, 1, 7),
            SliceRecord(0, 2, 2),
            SliceRecord(1, 3, 2),
            SliceRecord(2, 3, 9),
            SliceRecord(2, 4, 3),
            SliceRecord(3, 5, 1),
            SliceRecord(4, 5, 4),
            SliceRecord(5, 6, 2),
            SliceRecord(6, 7, 1),
        ),
    )
    hot_destination = _graph(
        "syn_hot_destination_e256",
        258,
        tuple(_edge(0, vertex, 3) for vertex in range(1, 129))
        + tuple(_edge(vertex, 257, 3) for vertex in range(1, 129)),
    )
    bank_fanin = _graph(
        "syn_gather_bank_fanin_e1024",
        33_281,
        tuple(_edge(0, vertex, 9) for vertex in range(1, 513))
        + tuple(_edge(vertex, 512 + vertex * 64, 9) for vertex in range(1, 513)),
    )
    cycle = _graph(
        "syn_pagerank_cycle_v32",
        32,
        tuple(_edge(vertex, (vertex + 1) % 32, 11) for vertex in range(32))
        + tuple(_edge(vertex, (vertex + 7) % 32, 11) for vertex in range(32)),
    )
    dangling = _graph(
        "syn_pagerank_dangling_v33",
        33,
        tuple(_edge(vertex, vertex + 1, 13) for vertex in range(31))
        + tuple(_edge(vertex, 32, 13) for vertex in range(0, 31, 3)),
    )
    tree = _graph(
        "syn_residual_frontier_tree_v127",
        127,
        (
            _edge(parent, child, 17)
            for parent in range(63)
            for child in (2 * parent + 1, 2 * parent + 2)
        ),
    )
    skew = _graph(
        "syn_residual_skew_hub_v257",
        257,
        tuple(_edge(0, vertex, 19) for vertex in range(1, 257))
        + tuple(_edge(vertex, 0, 19) for vertex in range(1, 257)),
    )
    fixtures = [
        SyntheticFixture("syn_chain_v64", "calibration", "chain", _chain("syn_chain_v64", 64, 1)),
        SyntheticFixture(diamond.case_id, "holdout", "weighted_diamond", diamond),
        SyntheticFixture(
            "syn_hot_source_e256",
            "calibration",
            "hot_source",
            _star("syn_hot_source_e256", 256, 2),
        ),
        SyntheticFixture(hot_destination.case_id, "holdout", "hot_destination", hot_destination),
        SyntheticFixture("syn_spread_e512", "calibration", "spread", _spread("syn_spread_e512")),
        SyntheticFixture(
            "syn_tiny_threshold_e4095",
            "calibration",
            "tiny_threshold",
            _star("syn_tiny_threshold_e4095", 4095, 6),
        ),
        SyntheticFixture(
            "syn_tiny_threshold_e4096",
            "holdout",
            "tiny_threshold",
            _star("syn_tiny_threshold_e4096", 4096, 7),
        ),
        SyntheticFixture(
            "syn_tiny_threshold_e4097",
            "holdout",
            "tiny_threshold",
            _star("syn_tiny_threshold_e4097", 4097, 8),
        ),
        SyntheticFixture(
            "syn_source_window_e4095",
            "calibration",
            "source_window",
            _source_window("syn_source_window_e4095", 4095, 9),
        ),
        SyntheticFixture(
            "syn_source_window_e4096",
            "holdout",
            "source_window",
            _source_window("syn_source_window_e4096", 4096, 10),
        ),
        SyntheticFixture(
            "syn_source_window_e4097",
            "holdout",
            "source_window",
            _source_window("syn_source_window_e4097", 4097, 11),
        ),
        SyntheticFixture(bank_fanin.case_id, "calibration", "gather_bank_fanin", bank_fanin),
        _dynamic_fixture(
            "syn_dynamic_shortcut_insert", "calibration", "dynamic_insert",
            ((0, 1, 8), (0, 2, 30), (1, 2, 8), (2, 3, 3), (3, 4, 2)),
            ((0, 2, 4, 1),), "incremental_insert", 8,
        ),
        _dynamic_fixture(
            "syn_dynamic_delete_fallback", "holdout", "dynamic_delete",
            ((0, 1, 1), (0, 2, 4), (2, 1, 4), (1, 3, 2), (2, 3, 9)),
            ((0, 1, 1, -1),), "full_rebuild_delete", 8,
        ),
        _dynamic_fixture(
            "syn_dynamic_increase_fallback", "calibration", "dynamic_increase",
            ((0, 1, 1), (0, 2, 3), (2, 1, 2), (1, 3, 2), (2, 3, 8)),
            ((0, 1, 1, -1), (0, 1, 9, 1)), "full_rebuild_increase", 8,
        ),
        _dynamic_fixture(
            "syn_dynamic_mixed_update", "holdout", "dynamic_mixed",
            ((0, 1, 6), (0, 2, 12), (1, 3, 3), (2, 3, 2), (3, 4, 2), (4, 5, 1)),
            ((0, 1, 6, -1), (0, 1, 2, 1), (2, 3, 2, -1), (1, 4, 5, 1)),
            "full_rebuild_mixed", 8,
        ),
        SyntheticFixture(cycle.case_id, "calibration", "pagerank_cycle", cycle),
        SyntheticFixture(dangling.case_id, "holdout", "pagerank_dangling", dangling),
        SyntheticFixture(tree.case_id, "calibration", "residual_frontier", tree),
        SyntheticFixture(skew.case_id, "holdout", "residual_skew", skew),
    ]
    return tuple(fixtures)


def _iter_matrix_market_edges(path: Path) -> Iterator[tuple[int, int]]:
    dimensions_seen = False
    with path.open("r", encoding="ascii", errors="strict") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line or line.startswith("%") or line.startswith("#"):
                continue
            fields = line.split()
            if not dimensions_seen:
                if len(fields) != 3:
                    raise ValueError(f"{path}:{line_number}: missing MatrixMarket dimensions")
                rows, columns, _ = (int(field) for field in fields)
                if rows <= 0 or columns <= 0:
                    raise ValueError(f"{path}:{line_number}: invalid MatrixMarket dimensions")
                dimensions_seen = True
                continue
            if len(fields) < 2:
                raise ValueError(f"{path}:{line_number}: malformed edge")
            src, dst = int(fields[0]), int(fields[1])
            if src <= 0 or dst <= 0:
                raise ValueError(f"{path}:{line_number}: expected one-based vertex IDs")
            yield src, dst
    if not dimensions_seen:
        raise ValueError(f"{path}: no MatrixMarket dimensions")


def _matrix_dimensions(path: Path) -> tuple[int, int, int]:
    with path.open("r", encoding="ascii", errors="strict") as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line or line.startswith("%") or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) != 3:
                raise ValueError(f"{path}: malformed MatrixMarket dimensions")
            return tuple(int(field) for field in fields)  # type: ignore[return-value]
    raise ValueError(f"{path}: no MatrixMarket dimensions")


def extract_compact_real_slice(
    dataset_id: str,
    source_path: Path,
    *,
    source_count: int = 128,
    edge_limit: int = 4096,
) -> tuple[SliceGraph, list[tuple[int, int, str]], dict[str, object]]:
    degrees: dict[int, int] = {}
    observed_edges = 0
    for src, _ in _iter_matrix_market_edges(source_path):
        degrees[src] = degrees.get(src, 0) + 1
        observed_edges += 1
    selected_sources = sorted(degrees, key=lambda vertex: (-degrees[vertex], vertex))[
        :source_count
    ]
    selected = set(selected_sources)
    destinations: dict[int, set[int]] = {src: set() for src in selected_sources}
    for src, dst in _iter_matrix_market_edges(source_path):
        if src in selected and src != dst:
            destinations[src].add(dst)

    ordered_destinations = {
        src: sorted(values) for src, values in destinations.items()
    }
    selected_edges: list[tuple[int, int]] = []
    offset = 0
    while len(selected_edges) < edge_limit:
        added = False
        for src in selected_sources:
            values = ordered_destinations[src]
            if offset < len(values):
                selected_edges.append((src, values[offset]))
                added = True
                if len(selected_edges) == edge_limit:
                    break
        if not added:
            break
        offset += 1
    if not selected_edges:
        raise ValueError(f"{source_path}: selected real slice is empty")

    original_vertices = set(selected_sources)
    original_vertices.update(dst for _, dst in selected_edges)
    mapping_order = selected_sources + sorted(original_vertices - selected)
    mapping = {original: local for local, original in enumerate(mapping_order)}
    graph = _graph(
        f"real_{dataset_id}_compact",
        len(mapping_order),
        (
            _edge(mapping[src], mapping[dst], 101)
            for src, dst in selected_edges
        ),
    )
    source_vertices = set(selected_sources)
    destination_vertices = {dst for _, dst in selected_edges}
    mapping_rows = [
        (
            mapping[original],
            original,
            (
                "source_and_destination"
                if original in source_vertices and original in destination_vertices
                else "selected_source"
                if original in source_vertices
                else "destination"
            ),
        )
        for original in mapping_order
    ]
    rows, columns, declared_edges = _matrix_dimensions(source_path)
    provenance: dict[str, object] = {
        "raw_path_hint": str(source_path),
        "raw_sha256": sha256_file(source_path),
        "matrix_rows": rows,
        "matrix_columns": columns,
        "matrix_declared_edges": declared_edges,
        "matrix_observed_edges": observed_edges,
        "extraction_algorithm": "top_out_degree_128_round_robin_dst_sorted_v1",
        "selected_source_count": len(selected_sources),
        "selected_edge_limit": edge_limit,
        "selected_edges": len(graph.records),
        "compact_vertices": graph.vertices,
        "sssp_source_original_id": selected_sources[0],
        "sssp_source_local_id": 0,
    }
    return graph, mapping_rows, provenance


def _write_mapping(path: Path, rows: Sequence[tuple[int, int, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("local_id", "original_id", "role"))
        writer.writerows(rows)


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _artifact(path: Path, root: Path) -> dict[str, object]:
    graph = load_slice(path)
    return {
        "path": _relative(path, root),
        "sha256": sha256_file(path),
        "case_id": graph.case_id,
        "vertices": graph.vertices,
        "records": len(graph.records),
    }


def _empty_update(case_id: str, vertices: int) -> SliceGraph:
    return SliceGraph(f"{case_id}_empty_update", vertices, ())


def _run_cases(fixture: Mapping[str, object]) -> list[dict[str, object]]:
    fixture_id = str(fixture["fixture_id"])
    common = {
        "fixture_id": fixture_id,
        "dataset_kind": fixture["dataset_kind"],
        "role": fixture["role"],
        "graph": fixture["graph"],
        "source": 0,
    }
    runs = [
        {
            **common,
            "run_id": f"{fixture_id}__weighted_sssp",
            "algorithm": "weighted_sssp",
            "scenario": "weighted_sssp",
            "max_rounds": 256,
            "update": fixture["empty_update"],
        },
        {
            **common,
            "run_id": f"{fixture_id}__full_pagerank",
            "algorithm": "full_pagerank",
            "scenario": "full_pagerank",
            "iterations": 3,
            "damping": 0.85,
        },
        {
            **common,
            "run_id": f"{fixture_id}__residual_pagerank",
            "algorithm": "thresholded_residual_pagerank",
            "scenario": "residual_pagerank",
            "damping": 0.85,
            "epsilon": 1.0e-6,
            "max_iterations": 256,
        },
    ]
    if "dynamic_update" in fixture:
        runs.append(
            {
                **common,
                "run_id": f"{fixture_id}__dynamic_weighted_sssp",
                "algorithm": "weighted_dynamic_sssp",
                "scenario": fixture["dynamic_path"],
                "max_rounds": 256,
                "update": fixture["dynamic_update"],
            }
        )
    return runs


def build_shared_comparison_corpus(
    root: Path,
    *,
    source_root: Path,
    output_dir: Path,
    manifest_path: Path,
) -> dict[str, object]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    fixtures: list[dict[str, object]] = []
    for spec in synthetic_fixtures():
        graph_path = output_dir / f"{spec.fixture_id}.slice"
        empty_path = output_dir / f"{spec.fixture_id}.empty.slice"
        write_slice(graph_path, spec.graph)
        write_slice(empty_path, _empty_update(spec.fixture_id, spec.graph.vertices))
        fixture: dict[str, object] = {
            "fixture_id": spec.fixture_id,
            "dataset_kind": "synthetic",
            "role": spec.role,
            "family": spec.family,
            "graph": _artifact(graph_path, root),
            "empty_update": _artifact(empty_path, root),
        }
        if spec.dynamic_update is not None:
            update_path = output_dir / f"{spec.fixture_id}.update.slice"
            write_slice(update_path, spec.dynamic_update)
            fixture["dynamic_update"] = _artifact(update_path, root)
            fixture["dynamic_path"] = spec.dynamic_path
        fixtures.append(fixture)

    real_sources: list[dict[str, object]] = []
    for dataset_id, filename in DEFAULT_REAL_SOURCES:
        source_path = source_root / filename
        graph, mapping_rows, provenance = extract_compact_real_slice(
            dataset_id, source_path
        )
        graph_path = output_dir / f"real_{dataset_id}_compact.slice"
        empty_path = output_dir / f"real_{dataset_id}_compact.empty.slice"
        mapping_path = output_dir / f"real_{dataset_id}_compact.map.csv"
        write_slice(graph_path, graph)
        write_slice(empty_path, _empty_update(graph.case_id, graph.vertices))
        _write_mapping(mapping_path, mapping_rows)
        fixture = {
            "fixture_id": graph.case_id,
            "dataset_kind": "real_compact_slice",
            "role": "validation",
            "family": "real_top_out_degree",
            "dataset_id": dataset_id,
            "graph": _artifact(graph_path, root),
            "empty_update": _artifact(empty_path, root),
            "mapping": {
                "path": _relative(mapping_path, root),
                "sha256": sha256_file(mapping_path),
                "rows": len(mapping_rows),
            },
        }
        fixtures.append(fixture)
        real_sources.append({"dataset_id": dataset_id, **provenance})

    profile_paths = (
        "configs/architectures/spine_shared_engine_9c08763.json",
        "configs/architectures/spine_latest_afb8199.json",
        "configs/architectures/grasu_regraph_normalized_weighted_spine23.json",
        "configs/architectures/grasu_regraph_normalized_pagerank_spine23.json",
        "configs/architectures/grasu_regraph_normalized_residual_pagerank_spine23.json",
    )
    profiles = [
        {"path": path, "sha256": sha256_file(root / path)} for path in profile_paths
    ]
    runs = [run for fixture in fixtures for run in _run_cases(fixture)]
    manifest: dict[str, object] = {
        "schema_version": 1,
        "matrix_id": "shared_comparison_workloads_20260725",
        "claim_class": "normalized_execution_driven_shared_workload_contract",
        "comparison_contract": {
            "graph_and_updates_identical": True,
            "algorithm_parameters_identical": True,
            "memory_backend": "SST memHierarchy plus DRAMSim3 HBM2",
            "hbm_channels": 32,
            "normalized_clock_mhz": 150.0,
            "native_spine_clock_mhz": 141.0,
            "clock_claim_rule": (
                "report cycles plus separately labeled normalized and native time; "
                "never silently mix clocks in one speedup"
            ),
            "conversion_cost": (
                "zero only for normalized PMA-native ReGraph; native GraSU plus "
                "ReGraph must report conversion separately"
            ),
            "weighted_sssp": (
                "uint32 saturating distances, uint16 positive weights, source 0, "
                "max 256 rounds"
            ),
            "full_pagerank": (
                "float32 architecture oracle plus independent float64 mathematical "
                "oracle, damping 0.85, exactly 3 iterations"
            ),
            "thresholded_residual_pagerank": (
                "float32 architecture oracle plus independent float64 mathematical "
                "oracle, damping 0.85, epsilon 1e-6, max 256 iterations"
            ),
        },
        "split_policy": {
            "calibration": "mechanism parameters may be fitted only from these synthetic fixtures",
            "holdout": "frozen before fitting and forbidden from parameter selection",
            "validation": (
                "real compact slices; forbidden from fitting and used for "
                "external-shape validation"
            ),
        },
        "limits": {
            "normalized_vertices": MAX_NORMALIZED_VERTICES,
            "reason": (
                "current normalized weighted GraSU/ReGraph ABI is one 19-bit "
                "destination partition; this corpus deliberately stays in one "
                "65536-vertex compute partition"
            ),
            "not_claimed": "multi-partition weighted SSSP or residual PageRank scalability",
        },
        "profiles": profiles,
        "real_sources": real_sources,
        "fixtures": fixtures,
        "runs": runs,
        "counts": {
            "synthetic_fixtures": sum(
                fixture["dataset_kind"] == "synthetic" for fixture in fixtures
            ),
            "real_datasets": len(real_sources),
            "fixtures": len(fixtures),
            "run_cases": len(runs),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    validate_shared_comparison_manifest(root, manifest_path)
    return manifest


def _resolve_artifact(root: Path, artifact: Mapping[str, object]) -> Path:
    path = root / str(artifact["path"])
    if not path.is_file():
        raise ValueError(f"missing workload artifact: {path}")
    if sha256_file(path) != artifact["sha256"]:
        raise ValueError(f"workload artifact hash mismatch: {path}")
    return path


def _materialize_update(
    graph: SliceGraph, update: SliceGraph
) -> dict[tuple[int, int, int], int]:
    counts: dict[tuple[int, int, int], int] = {}
    for record in graph.records + update.records:
        key = (record.src, record.dst, record.weight)
        counts[key] = counts.get(key, 0) + record.diff
        if counts[key] < 0:
            raise ValueError(f"update deletes a missing edge instance: {key}")
    if not any(count > 0 for count in counts.values()):
        raise ValueError("update produces an empty graph")
    return counts


def validate_shared_comparison_manifest(root: Path, manifest_path: Path) -> dict[str, object]:
    root = root.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported shared workload manifest schema")
    fixtures = manifest.get("fixtures")
    runs = manifest.get("runs")
    if not isinstance(fixtures, list) or not isinstance(runs, list):
        raise ValueError("manifest fixtures and runs must be lists")
    synthetic = [item for item in fixtures if item["dataset_kind"] == "synthetic"]
    real = [item for item in fixtures if item["dataset_kind"] == "real_compact_slice"]
    if len(synthetic) < 20 or len({item["dataset_id"] for item in real}) < 3:
        raise ValueError(
            "shared matrix requires at least 20 synthetic fixtures and 3 real datasets"
        )
    fixture_ids = [str(item["fixture_id"]) for item in fixtures]
    if len(fixture_ids) != len(set(fixture_ids)):
        raise ValueError("fixture IDs are not unique")

    graph_hashes: set[str] = set()
    roles: dict[str, set[str]] = {"calibration": set(), "holdout": set(), "validation": set()}
    for fixture in fixtures:
        graph_path = _resolve_artifact(root, fixture["graph"])
        empty_path = _resolve_artifact(root, fixture["empty_update"])
        graph = load_slice(graph_path)
        empty = load_slice(empty_path)
        if not graph.records or empty.records or graph.vertices != empty.vertices:
            raise ValueError(f"invalid graph/empty-update pair for {fixture['fixture_id']}")
        if graph.vertices > MAX_NORMALIZED_VERTICES:
            raise ValueError(
                "fixture exceeds normalized one-partition limit: "
                f"{fixture['fixture_id']}"
            )
        if any(
            edge.src < 0
            or edge.dst < 0
            or edge.src >= graph.vertices
            or edge.dst >= graph.vertices
            or not 1 <= edge.weight <= 65_535
            or edge.diff != 1
            for edge in graph.records
        ):
            raise ValueError(f"invalid graph record in {fixture['fixture_id']}")
        graph_hash = str(fixture["graph"]["sha256"])
        if graph_hash in graph_hashes:
            raise ValueError("fixture graphs must have disjoint content hashes")
        graph_hashes.add(graph_hash)
        role = str(fixture["role"])
        if role not in roles:
            raise ValueError(f"unknown fixture role: {role}")
        roles[role].add(graph_hash)
        if "dynamic_update" in fixture:
            update_path = _resolve_artifact(root, fixture["dynamic_update"])
            update = load_slice(update_path)
            if update.vertices != graph.vertices or not update.records:
                raise ValueError(f"invalid dynamic update for {fixture['fixture_id']}")
            _materialize_update(graph, update)
        if "mapping" in fixture:
            mapping_path = _resolve_artifact(root, fixture["mapping"])
            with mapping_path.open("r", encoding="ascii", newline="") as stream:
                mapping_rows = list(csv.DictReader(stream))
            if len(mapping_rows) != graph.vertices:
                raise ValueError(f"mapping size mismatch for {fixture['fixture_id']}")
    if roles["calibration"] & roles["holdout"]:
        raise ValueError("calibration and holdout graph hashes overlap")
    if (roles["calibration"] | roles["holdout"]) & roles["validation"]:
        raise ValueError("synthetic and real validation graph hashes overlap")

    run_ids = [str(run["run_id"]) for run in runs]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("run IDs are not unique")
    fixture_lookup = {str(item["fixture_id"]): item for item in fixtures}
    required_algorithms = {
        "weighted_sssp",
        "full_pagerank",
        "thresholded_residual_pagerank",
    }
    for fixture_id in fixture_lookup:
        algorithms = {
            str(run["algorithm"])
            for run in runs
            if run["fixture_id"] == fixture_id
        }
        if not required_algorithms <= algorithms:
            raise ValueError(f"fixture lacks the three shared algorithms: {fixture_id}")
    for run in runs:
        fixture_id = str(run["fixture_id"])
        if fixture_id not in fixture_lookup:
            raise ValueError(f"run references an unknown fixture: {fixture_id}")
        fixture = fixture_lookup[fixture_id]
        if run["graph"] != fixture["graph"]:
            raise ValueError(f"run graph differs from its frozen fixture: {run['run_id']}")
        if int(run.get("source", -1)) != 0:
            raise ValueError(f"shared run does not use source zero: {run['run_id']}")
        if run["algorithm"] == "weighted_sssp" and run.get("update") != fixture["empty_update"]:
            raise ValueError(f"static SSSP run has a non-frozen update: {run['run_id']}")
        if (
            run["algorithm"] == "weighted_dynamic_sssp"
            and run.get("update") != fixture.get("dynamic_update")
        ):
            raise ValueError(f"dynamic SSSP run has a non-frozen update: {run['run_id']}")
    dynamic_paths = {
        str(run["scenario"])
        for run in runs
        if run["algorithm"] == "weighted_dynamic_sssp"
    }
    expected_dynamic = {
        "incremental_insert",
        "full_rebuild_delete",
        "full_rebuild_increase",
        "full_rebuild_mixed",
    }
    if dynamic_paths != expected_dynamic:
        raise ValueError("dynamic SSSP paths are incomplete")
    expected_counts = {
        "synthetic_fixtures": len(synthetic),
        "real_datasets": len({item["dataset_id"] for item in real}),
        "fixtures": len(fixtures),
        "run_cases": len(runs),
    }
    if manifest.get("counts") != expected_counts:
        raise ValueError("manifest counts do not match its frozen contents")
    for profile in manifest.get("profiles", []):
        _resolve_artifact(root, profile)
    return manifest
