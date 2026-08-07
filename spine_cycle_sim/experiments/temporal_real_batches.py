"""Reproducible compact workloads from GraSU's timestamped real graphs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import csv
import gzip
import json
from pathlib import Path
from typing import Iterator, TextIO
import zipfile

from .real_small_batches import apply_explicit_weighted_updates
from .shared_workloads import SliceGraph, SliceRecord, load_slice, sha256_file, write_slice


BASE_EDGE_COUNT = 8_192
INSERT_POOL_COUNT = 4_096
TEMPORAL_BATCH_SIZES = (1, 8, 64, 512, 4_096)
TEMPORAL_SCENARIOS = ("insert", "delete", "mixed", "weight_change")


@dataclass(frozen=True)
class TemporalSourceSpec:
    dataset_id: str
    abbreviation: str
    relative_path: str
    compression: str
    archive_member: str | None
    sha256: str
    paper_vertices: int
    paper_edges: int
    paper_base_edges: int


GRASU_TEMPORAL_SOURCES = (
    TemporalSourceSpec(
        "sx_askubuntu",
        "AU",
        "sx-askubuntu/sx-askubuntu.txt.gz",
        "gzip",
        None,
        "54af4be03bf77030e8894e445679c4e20614f0b82d68fc8cb49431f70e07a0f6",
        160_000,
        960_000,
        590_000,
    ),
    TemporalSourceSpec(
        "sx_superuser",
        "SU",
        "sx-superuser/sx-superuser.txt.gz",
        "gzip",
        None,
        "35367fa1357d28ba92b06f75a2616cdf983e0c5b70b9560f36440e39648cc928",
        190_000,
        1_440_000,
        920_000,
    ),
    TemporalSourceSpec(
        "wiki_talk_temporal",
        "WK",
        "wiki-talk-temporal/wiki-talk-temporal.txt.gz",
        "gzip",
        None,
        "2053b1f5bb3c46320f8e4da91aa6d7d79ec8d78e2c8cc99cede609c0c375f33e",
        1_140_000,
        7_830_000,
        3_310_000,
    ),
    TemporalSourceSpec(
        "sx_stackoverflow",
        "SO",
        "sx-stackoverflow/snap_sx-stackoverflow.txt.gz",
        "gzip",
        None,
        "fc04264de1652bbf91c10eb8ec2465df082fc0aec2012e5f4a8edc6400f0d7a3",
        2_600_000,
        63_500_000,
        36_230_000,
    ),
    TemporalSourceSpec(
        "soc_bitcoin",
        "BC",
        "soc-bitcoin/soc-bitcoin.zip",
        "zip",
        "soc-bitcoin.edges",
        "c12caba90fb002e64bc25451d931a73832989c8564bf1f4ce6a890287094f0e8",
        24_580_000,
        122_950_000,
        60_490_000,
    ),
)


@contextmanager
def _source_lines(path: Path, spec: TemporalSourceSpec) -> Iterator[TextIO]:
    if spec.compression == "gzip":
        with gzip.open(path, "rt", encoding="ascii", errors="strict") as stream:
            yield stream
        return
    if spec.compression == "zip" and spec.archive_member is not None:
        with zipfile.ZipFile(path) as archive:
            with archive.open(spec.archive_member) as raw_stream:
                import io

                with io.TextIOWrapper(raw_stream, encoding="ascii", errors="strict") as stream:
                    yield stream
        return
    raise ValueError(f"unsupported temporal source encoding: {spec.compression}")


def iter_temporal_events(
    path: Path, spec: TemporalSourceSpec
) -> Iterator[tuple[int, int, int]]:
    with _source_lines(path, spec) as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line or line.startswith(("#", "%")):
                continue
            fields = line.replace(",", " ").split()
            if len(fields) < 3:
                raise ValueError(f"{path}:{line_number}: expected src dst timestamp")
            source, destination, timestamp = (int(field) for field in fields[:3])
            if source < 0 or destination < 0:
                raise ValueError(f"{path}:{line_number}: negative vertex ID")
            yield source, destination, timestamp


def _weight(source: int, destination: int) -> int:
    return 1 + ((source * 131 + destination * 17 + 257) % 31)


def extract_temporal_compact_slice(
    source_path: Path,
    spec: TemporalSourceSpec,
    *,
    base_edges: int = BASE_EDGE_COUNT,
    insert_pool_edges: int = INSERT_POOL_COUNT,
) -> tuple[
    SliceGraph,
    tuple[tuple[int, int], ...],
    tuple[tuple[int, int, int], ...],
    dict[str, object],
]:
    """Take unique edges in source-file order and compact the observed IDs."""

    if base_edges <= 0 or insert_pool_edges <= 0:
        raise ValueError("temporal slice edge counts must be positive")
    target = base_edges + insert_pool_edges
    mapping: dict[int, int] = {}
    selected: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    scanned_events = 0
    timestamps: list[int] = []
    for external_source, external_destination, timestamp in iter_temporal_events(
        source_path, spec
    ):
        scanned_events += 1
        if external_source == external_destination:
            continue
        external_key = (external_source, external_destination)
        if external_key in seen:
            continue
        seen.add(external_key)
        for vertex in external_key:
            if vertex not in mapping:
                mapping[vertex] = len(mapping)
        selected.append((mapping[external_source], mapping[external_destination], timestamp))
        timestamps.append(timestamp)
        if len(selected) == target:
            break
    if len(selected) != target:
        raise ValueError(
            f"{source_path}: found {len(selected)} unique edges, need {target}"
        )

    base = selected[:base_edges]
    insert_pool = tuple(selected[base_edges:])
    graph = SliceGraph(
        f"grasu_{spec.dataset_id}_file_order_e{base_edges}",
        len(mapping),
        tuple(
            sorted(
                SliceRecord(source, destination, _weight(source, destination), 1)
                for source, destination, _timestamp in base
            )
        ),
    )
    local_to_external = tuple(
        external for external, _local in sorted(mapping.items(), key=lambda item: item[1])
    )
    provenance = {
        "extraction_policy": "unique_nonself_edges_in_source_file_order_compact_ids_v1",
        "scanned_events": scanned_events,
        "selected_unique_edges": len(selected),
        "base_edges": base_edges,
        "insert_pool_edges": insert_pool_edges,
        "compact_vertices": graph.vertices,
        "selected_timestamp_min": min(timestamps),
        "selected_timestamp_max": max(timestamps),
        "timestamp_order_reconstructed": False,
    }
    return graph, local_to_external, insert_pool, provenance


def _spread(records: tuple[SliceRecord, ...], count: int) -> tuple[SliceRecord, ...]:
    if count <= 0 or count > len(records):
        raise ValueError("spread selection is outside the record population")
    if count == len(records):
        return records
    indices = [(index * len(records)) // count for index in range(count)]
    return tuple(records[index] for index in indices)


def _sorted_update_stream(records: tuple[SliceRecord, ...]) -> tuple[SliceRecord, ...]:
    return tuple(
        sorted(
            records,
            key=lambda edge: (
                edge.src,
                edge.dst,
                0 if edge.diff < 0 else 1,
                edge.weight,
            ),
        )
    )


def build_temporal_update(
    graph: SliceGraph,
    insert_pool: tuple[tuple[int, int, int], ...],
    *,
    scenario: str,
    batch_size: int,
) -> tuple[SliceGraph, int]:
    if scenario not in TEMPORAL_SCENARIOS:
        raise ValueError(f"unsupported temporal scenario: {scenario}")
    if batch_size not in TEMPORAL_BATCH_SIZES:
        raise ValueError(f"unsupported temporal batch size: {batch_size}")
    if scenario == "mixed" and batch_size < 2:
        raise ValueError("mixed updates require at least two user mutations")

    base_records = tuple(sorted(graph.records))
    insertion_records = tuple(
        SliceRecord(source, destination, _weight(source, destination), 1)
        for source, destination, _timestamp in insert_pool
    )
    if scenario == "insert":
        records = _spread(insertion_records, batch_size)
        physical_records = batch_size
    elif scenario == "delete":
        records = tuple(
            SliceRecord(edge.src, edge.dst, edge.weight, -1)
            for edge in _spread(base_records, batch_size)
        )
        physical_records = batch_size
    elif scenario == "mixed":
        delete_count = batch_size // 2
        insert_count = batch_size - delete_count
        deletions = tuple(
            SliceRecord(edge.src, edge.dst, edge.weight, -1)
            for edge in _spread(base_records, delete_count)
        )
        insertions = _spread(insertion_records, insert_count)
        records = tuple(sorted(deletions + insertions))
        physical_records = batch_size
    else:
        changes: list[SliceRecord] = []
        for edge in _spread(base_records, batch_size):
            new_weight = edge.weight % 31 + 1
            changes.append(SliceRecord(edge.src, edge.dst, edge.weight, -1))
            changes.append(SliceRecord(edge.src, edge.dst, new_weight, 1))
        records = tuple(changes)
        physical_records = 2 * batch_size

    records = _sorted_update_stream(records)

    update = SliceGraph(
        f"{graph.case_id}_{scenario}_u{batch_size}", graph.vertices, records
    )
    return update, physical_records


def _artifact(path: Path, root: Path) -> dict[str, object]:
    graph = load_slice(path)
    return {
        "path": str(path.resolve().relative_to(root.resolve())),
        "sha256": sha256_file(path),
        "case_id": graph.case_id,
        "vertices": graph.vertices,
        "records": len(graph.records),
    }


def build_temporal_real_manifest(
    root: Path,
    *,
    source_root: Path,
    output_dir: Path,
    manifest_path: Path,
) -> dict[str, object]:
    root = root.resolve()
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets: list[dict[str, object]] = []
    runs: list[dict[str, object]] = []
    for spec in GRASU_TEMPORAL_SOURCES:
        source_path = source_root / spec.relative_path
        if sha256_file(source_path) != spec.sha256:
            raise ValueError(f"source hash mismatch for {spec.dataset_id}")
        graph, mapping, insert_pool, provenance = extract_temporal_compact_slice(
            source_path, spec
        )
        graph_path = output_dir / f"{spec.dataset_id}_base_e{BASE_EDGE_COUNT}.slice"
        mapping_path = output_dir / f"{spec.dataset_id}_mapping.csv"
        write_slice(graph_path, graph)
        with mapping_path.open("w", encoding="ascii", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("local_id", "external_id"))
            writer.writerows(enumerate(mapping))
        graph_artifact = _artifact(graph_path, root)
        dataset = {
            "dataset_id": spec.dataset_id,
            "abbreviation": spec.abbreviation,
            "source_path_hint": str(source_path),
            "source_sha256": spec.sha256,
            "source_encoding": spec.compression,
            "archive_member": spec.archive_member,
            "paper_vertices": spec.paper_vertices,
            "paper_edges": spec.paper_edges,
            "paper_base_edges": spec.paper_base_edges,
            "graph": graph_artifact,
            "mapping_path": str(mapping_path.relative_to(root)),
            "mapping_sha256": sha256_file(mapping_path),
            "provenance": provenance,
        }
        datasets.append(dataset)
        for batch_size in TEMPORAL_BATCH_SIZES:
            for scenario in TEMPORAL_SCENARIOS:
                if scenario == "mixed" and batch_size < 2:
                    continue
                update, physical_records = build_temporal_update(
                    graph,
                    insert_pool,
                    scenario=scenario,
                    batch_size=batch_size,
                )
                update_path = output_dir / (
                    f"{spec.dataset_id}_{scenario}_u{batch_size}.slice"
                )
                write_slice(update_path, update)
                final_graph = apply_explicit_weighted_updates(graph, update)
                runs.append(
                    {
                        "run_id": f"grasu_{spec.abbreviation.lower()}_{scenario}_u{batch_size}",
                        "dataset_id": spec.dataset_id,
                        "dataset_abbreviation": spec.abbreviation,
                        "dataset_kind": "grasu_temporal_real_compact_file_order_slice",
                        "input_scope": "real_compact_slice",
                        "batch_size": batch_size,
                        "update_pattern": scenario,
                        "scenario": scenario,
                        "user_mutations": batch_size,
                        "physical_records": physical_records,
                        "final_edges": len(final_graph.records),
                        "graph": graph_artifact,
                        "update": _artifact(update_path, root),
                    }
                )
    manifest = {
        "schema_version": 1,
        "matrix_id": "candidate10_grasu_temporal_compact_batches_v1_20260727",
        "input_scope": "real_compact_slice",
        "claim_class": "paper_source_real_topology_compact_file_order_slice",
        "contract": {
            "datasets": len(GRASU_TEMPORAL_SOURCES),
            "base_edges_per_dataset": BASE_EDGE_COUNT,
            "insert_pool_edges_per_dataset": INSERT_POOL_COUNT,
            "batch_sizes": list(TEMPORAL_BATCH_SIZES),
            "scenarios": list(TEMPORAL_SCENARIOS),
            "mixed_batch_one_omitted": True,
            "graph_and_update_bytes_identical_across_architectures": True,
            "performance_parameters_frozen_before_execution": True,
        },
        "datasets": datasets,
        "runs": runs,
        "limitations": [
            "Inputs are compact slices, not complete GraSU datasets.",
            "Edges preserve source-file order; global timestamp order is not reconstructed.",
            "Compact vertex IDs alter original partition occupancy.",
            "Delete, mixed, and weight-change batches are derived from real topology; only insert candidates come directly from later source-file events.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def validate_temporal_real_manifest(root: Path, manifest_path: Path) -> dict[str, object]:
    root = root.resolve()
    manifest = json.loads(manifest_path.resolve().read_text(encoding="utf-8"))
    if manifest.get("matrix_id") != "candidate10_grasu_temporal_compact_batches_v1_20260727":
        raise ValueError("unexpected temporal real matrix identity")
    datasets = manifest.get("datasets", [])
    runs = manifest.get("runs", [])
    if len(datasets) != len(GRASU_TEMPORAL_SOURCES):
        raise ValueError("temporal manifest dataset coverage is incomplete")
    expected_runs = len(GRASU_TEMPORAL_SOURCES) * (
        len(TEMPORAL_BATCH_SIZES) * len(TEMPORAL_SCENARIOS) - 1
    )
    if len(runs) != expected_runs:
        raise ValueError("temporal manifest run coverage is incomplete")
    seen: set[tuple[str, str, int]] = set()
    for dataset in datasets:
        graph_path = root / dataset["graph"]["path"]
        mapping_path = root / dataset["mapping_path"]
        if sha256_file(graph_path) != dataset["graph"]["sha256"]:
            raise ValueError(f"graph hash mismatch for {dataset['dataset_id']}")
        if sha256_file(mapping_path) != dataset["mapping_sha256"]:
            raise ValueError(f"mapping hash mismatch for {dataset['dataset_id']}")
    for run in runs:
        key = (run["dataset_id"], run["scenario"], int(run["batch_size"]))
        if key in seen:
            raise ValueError(f"duplicate temporal run: {key}")
        seen.add(key)
        graph_path = root / run["graph"]["path"]
        update_path = root / run["update"]["path"]
        if sha256_file(graph_path) != run["graph"]["sha256"]:
            raise ValueError(f"graph hash mismatch for {run['run_id']}")
        if sha256_file(update_path) != run["update"]["sha256"]:
            raise ValueError(f"update hash mismatch for {run['run_id']}")
        graph = load_slice(graph_path)
        update = load_slice(update_path)
        if update.vertices != graph.vertices:
            raise ValueError(f"vertex count mismatch for {run['run_id']}")
        if len(update.records) != int(run["physical_records"]):
            raise ValueError(f"physical record mismatch for {run['run_id']}")
        final_graph = apply_explicit_weighted_updates(graph, update)
        if len(final_graph.records) != int(run["final_edges"]):
            raise ValueError(f"final edge mismatch for {run['run_id']}")
    return manifest
