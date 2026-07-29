"""Streaming, auditable materialization for publication-scale graph workloads."""

from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from typing import Any, Iterator, Mapping, TextIO
import zipfile


KEY_WIDTH = 10
WEIGHT_SEED = 20_260_729
DEFAULT_BATCH_SIZES = (1, 8, 64, 512, 4_096)
DEFAULT_PAGERANK_SCALES = (64_000, 256_000, 1_000_000, 4_000_000)
SPINE_MAX_VERTICES = 16_777_216
HASH_MODULUS = 2_147_483_647


@dataclass(frozen=True)
class PublicationSourceSpec:
    dataset_id: str
    source_path: Path
    source_encoding: str
    archive_member: str | None = None
    paper_base_events: int | None = None
    semantic_projection: str = "directed"
    declared_vertices: int | None = None
    index_base: int = 0
    swap_endpoints: bool = False
    expected_source_sha256: str | None = None
    expected_unique_edges: int | None = None


@dataclass(frozen=True)
class SliceMetadata:
    path: Path
    case_id: str
    vertices: int
    records: int
    sha256: str
    size_bytes: int
    unique_sources: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    temporary.replace(path)


def canonical_edge_weight(source: int, destination: int, seed: int = WEIGHT_SEED) -> int:
    """Return the frozen positive uint16 weight without platform hash state."""

    return 1 + ((source * 131 + destination * 17 + seed * 29) % 64)


def edge_hash_bucket(source: int, destination: int, seed: int = WEIGHT_SEED) -> int:
    return (
        source * 1_000_003 + destination * 9_176 + seed * 53
    ) % HASH_MODULUS


def read_slice_metadata_streaming(path: Path) -> SliceMetadata:
    case_id = path.stem
    vertices: int | None = None
    records = 0
    unique_sources = 0
    previous_source: int | None = None
    digest = hashlib.sha256()
    with path.open("rb") as raw_stream:
        for raw_line in raw_stream:
            digest.update(raw_line)
            line = raw_line.decode("ascii").strip()
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
                raise ValueError(f"{path}: expected four edge fields")
            source = int(fields[0])
            if source != previous_source:
                unique_sources += 1
                previous_source = source
            records += 1
    if vertices is None or vertices <= 0:
        raise ValueError(f"{path}: missing positive vertices metadata")
    return SliceMetadata(
        path=path.resolve(),
        case_id=case_id,
        vertices=vertices,
        records=records,
        sha256=digest.hexdigest(),
        size_bytes=path.stat().st_size,
        unique_sources=unique_sources,
    )


def publication_source_spec(
    contract: Mapping[str, Any], dataset_id: str, dataset_root: Path
) -> PublicationSourceSpec:
    dataset = next(
        (item for item in contract["datasets"] if item["dataset_id"] == dataset_id),
        None,
    )
    if dataset is None:
        raise KeyError(f"dataset is absent from publication contract: {dataset_id}")
    source = dataset["source"]
    encoding = str(source["encoding"])
    temporal = encoding in {
        "gzip_temporal_src_dst_timestamp",
        "zip_edge_list",
    }
    return PublicationSourceSpec(
        dataset_id=dataset_id,
        source_path=(dataset_root / source["relative_path"]).resolve(),
        source_encoding=encoding,
        archive_member=source.get("archive_member"),
        paper_base_events=(int(dataset["paper_base_edges"]) if temporal else None),
        semantic_projection=str(source.get("semantic_projection", "directed")),
        index_base=1 if encoding in {"tar_matrix_market", "zip_edge_list"} else 0,
        expected_source_sha256=str(source["sha256"]),
    )


def r19_source_spec(path: Path, contract: Mapping[str, Any]) -> PublicationSourceSpec:
    endpoint = contract["synthetic_endpoint"]
    source = endpoint.get("source", {})
    return PublicationSourceSpec(
        dataset_id=str(endpoint["dataset_id"]),
        source_path=path.resolve(),
        source_encoding="plain_rmat_dst_src",
        declared_vertices=int(endpoint["vertices"]),
        index_base=1,
        swap_endpoints=True,
        expected_source_sha256=source.get("sha256"),
        expected_unique_edges=int(endpoint["expected_unique_directed_edges"]),
    )


@contextmanager
def _source_lines(spec: PublicationSourceSpec) -> Iterator[TextIO]:
    if spec.source_encoding == "gzip_temporal_src_dst_timestamp":
        with gzip.open(spec.source_path, "rt", encoding="ascii", errors="strict") as stream:
            yield stream
        return
    if spec.source_encoding == "zip_edge_list":
        if spec.archive_member is None:
            raise ValueError("ZIP source requires an archive member")
        with zipfile.ZipFile(spec.source_path) as archive:
            with archive.open(spec.archive_member) as raw:
                with io.TextIOWrapper(raw, encoding="ascii", errors="strict") as stream:
                    yield stream
        return
    if spec.source_encoding == "tar_matrix_market":
        if spec.archive_member is None:
            raise ValueError("tar Matrix Market source requires an archive member")
        with tarfile.open(spec.source_path, "r:gz") as archive:
            extracted = archive.extractfile(spec.archive_member)
            if extracted is None:
                raise ValueError(
                    f"archive member is not a regular file: {spec.archive_member}"
                )
            with extracted:
                with io.TextIOWrapper(
                    extracted, encoding="ascii", errors="strict"
                ) as stream:
                    yield stream
        return
    if spec.source_encoding == "plain_rmat_dst_src":
        with spec.source_path.open("r", encoding="ascii", errors="strict") as stream:
            yield stream
        return
    raise ValueError(f"unsupported source encoding: {spec.source_encoding}")


def _write_key(stream: TextIO, source: int, destination: int) -> None:
    stream.write(f"{source:0{KEY_WIDTH}d} {destination:0{KEY_WIDTH}d}\n")


def _progress(
    path: Path | None,
    *,
    dataset_id: str,
    phase: str,
    completed: int | None = None,
    total: int | None = None,
    **fields: Any,
) -> None:
    if path is None:
        return
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "dataset_id": dataset_id,
        "phase": phase,
        "host_epoch_seconds": time.time(),
    }
    if completed is not None:
        payload["completed"] = completed
    if total is not None:
        payload["total"] = total
    payload.update(fields)
    atomic_write_json(path, payload)


def _normalize_source(
    spec: PublicationSourceSpec,
    *,
    base_raw: Path,
    post_base_raw: Path,
    progress_path: Path | None,
) -> dict[str, Any]:
    base_raw.parent.mkdir(parents=True, exist_ok=True)
    matrix_dimensions: tuple[int, int, int] | None = None
    raw_records = 0
    base_input_records = 0
    post_input_records = 0
    emitted_base_records = 0
    emitted_post_records = 0
    self_loops_removed = 0
    max_vertex = -1
    reciprocal = spec.semantic_projection in {
        "matrix_market_symmetric",
        "reciprocal_to_paper_edge_count",
    }
    matrix_dimensions_pending = spec.source_encoding == "tar_matrix_market"

    with (
        base_raw.open("w", encoding="ascii", buffering=8 * 1024 * 1024) as base,
        post_base_raw.open("w", encoding="ascii", buffering=8 * 1024 * 1024) as post,
        _source_lines(spec) as source,
    ):
        for line_number, raw_line in enumerate(source, start=1):
            line = raw_line.strip()
            if not line or line.startswith(("#", "%")):
                continue
            fields = line.replace(",", " ").split()
            if matrix_dimensions_pending:
                if len(fields) < 3:
                    raise ValueError(
                        f"{spec.source_path}:{line_number}: invalid Matrix Market dimensions"
                    )
                matrix_dimensions = tuple(int(value) for value in fields[:3])
                matrix_dimensions_pending = False
                continue
            if len(fields) < 2:
                raise ValueError(
                    f"{spec.source_path}:{line_number}: expected at least two fields"
                )
            first, second = int(fields[0]), int(fields[1])
            source_id, destination_id = (
                (second, first) if spec.swap_endpoints else (first, second)
            )
            source_id -= spec.index_base
            destination_id -= spec.index_base
            if source_id < 0 or destination_id < 0:
                raise ValueError(
                    f"{spec.source_path}:{line_number}: vertex below declared index base"
                )
            raw_records += 1
            is_base = (
                spec.paper_base_events is None
                or raw_records <= spec.paper_base_events
            )
            if is_base:
                base_input_records += 1
                target = base
            else:
                post_input_records += 1
                target = post
            max_vertex = max(max_vertex, source_id, destination_id)
            if source_id == destination_id:
                self_loops_removed += 1
                continue
            _write_key(target, source_id, destination_id)
            if is_base:
                emitted_base_records += 1
            else:
                emitted_post_records += 1
            if reciprocal:
                _write_key(target, destination_id, source_id)
                if is_base:
                    emitted_base_records += 1
                else:
                    emitted_post_records += 1
            if raw_records % 1_000_000 == 0:
                _progress(
                    progress_path,
                    dataset_id=spec.dataset_id,
                    phase="normalize",
                    completed=raw_records,
                    raw_records=raw_records,
                    emitted_base_records=emitted_base_records,
                    emitted_post_records=emitted_post_records,
                )

    vertices = spec.declared_vertices
    if matrix_dimensions is not None:
        if matrix_dimensions[0] != matrix_dimensions[1]:
            raise ValueError("publication graph Matrix Market input must be square")
        vertices = matrix_dimensions[0]
    if vertices is None:
        vertices = max_vertex + 1
    if vertices <= max_vertex:
        raise ValueError("declared vertex count does not cover normalized IDs")
    return {
        "raw_records": raw_records,
        "base_input_records": base_input_records,
        "post_input_records": post_input_records,
        "emitted_base_records_before_dedup": emitted_base_records,
        "emitted_post_records_before_dedup": emitted_post_records,
        "self_loops_removed": self_loops_removed,
        "max_normalized_vertex_id": max_vertex,
        "vertices": vertices,
        "matrix_dimensions": list(matrix_dimensions) if matrix_dimensions else None,
        "source_projection_reciprocal": reciprocal,
    }


def _wait_process(
    process: subprocess.Popen[bytes],
    *,
    spec: PublicationSourceSpec,
    phase: str,
    progress_path: Path | None,
) -> None:
    last_progress = 0.0
    while True:
        try:
            process.wait(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            now = time.monotonic()
            if now - last_progress >= 2.0:
                _progress(
                    progress_path,
                    dataset_id=spec.dataset_id,
                    phase=phase,
                    process_pid=process.pid,
                )
                last_progress = now
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, process.args)


def _sort_unique(
    input_path: Path,
    output_path: Path,
    *,
    temp_dir: Path,
    parallel: int,
    memory: str,
    spec: PublicationSourceSpec,
    phase: str,
    progress_path: Path | None,
) -> None:
    temporary = output_path.with_name(f".{output_path.name}.partial")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    process = subprocess.Popen(
        [
            "sort",
            "--unique",
            f"--parallel={parallel}",
            f"--buffer-size={memory}",
            f"--temporary-directory={temp_dir}",
            str(input_path),
            "--output",
            str(temporary),
        ],
        env=environment,
    )
    _wait_process(
        process,
        spec=spec,
        phase=phase,
        progress_path=progress_path,
    )
    temporary.replace(output_path)


def _line_count(path: Path) -> int:
    completed = subprocess.run(
        ["wc", "-l", str(path)], check=True, text=True, stdout=subprocess.PIPE
    )
    return int(completed.stdout.split()[0])


def _unique_source_count(path: Path) -> int:
    program = "BEGIN{n=0;p=\"\"} $1!=p{n++;p=$1} END{print n}"
    completed = subprocess.run(
        ["awk", program, str(path)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return int(completed.stdout.strip() or 0)


def _decorate_slice(
    key_path: Path,
    output_path: Path,
    *,
    case_id: str,
    vertices: int,
    seed: int,
) -> SliceMetadata:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.partial")
    program = (
        "{s=$1+0;d=$2+0;w=1+((s*131+d*17+seed*29)%64);"
        'printf "%d %d %d 1\\n",s,d,w}'
    )
    with temporary.open("wb") as output:
        output.write(
            (
                "# spine_real_slice_version=1\n"
                f"# case={case_id}\n"
                f"# vertices={vertices}\n"
                "# columns=src dst weight diff\n"
                "# weight_policy=edge_hash_positive_uint16_v1\n"
                f"# weight_seed={seed}\n"
            ).encode("ascii")
        )
        output.flush()
        subprocess.run(
            ["awk", "-v", f"seed={seed}", program, str(key_path)],
            check=True,
            stdout=output,
        )
    temporary.replace(output_path)
    return SliceMetadata(
        path=output_path.resolve(),
        case_id=case_id,
        vertices=vertices,
        records=_line_count(key_path),
        sha256=sha256_file(output_path),
        size_bytes=output_path.stat().st_size,
        unique_sources=_unique_source_count(key_path),
    )


def _artifact(
    metadata: SliceMetadata,
    *,
    role: str,
    source_cohorts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    artifact = {
        "role": role,
        "path": str(metadata.path),
        "case_id": metadata.case_id,
        "vertices": metadata.vertices,
        "records": metadata.records,
        "unique_sources": metadata.unique_sources,
        "zero_outdegree_vertices": metadata.vertices - metadata.unique_sources,
        "size_bytes": metadata.size_bytes,
        "sha256": metadata.sha256,
    }
    if source_cohorts is not None:
        artifact["source_cohorts"] = dict(source_cohorts)
    return artifact


def _source_cohorts(key_path: Path, *, seed: int) -> dict[str, int]:
    degree_histogram: Counter[int] = Counter()
    representative: dict[int, int] = {}
    high_source = -1
    high_degree = -1
    random_source = -1
    random_rank = (1 << 64) - 1
    sources = 0

    def record(source: int, degree: int) -> None:
        nonlocal high_source, high_degree, random_source, random_rank, sources
        sources += 1
        degree_histogram[degree] += 1
        representative.setdefault(degree, source)
        if degree > high_degree or (degree == high_degree and source < high_source):
            high_source = source
            high_degree = degree
        rank = _splitmix64(seed + source)
        if rank < random_rank or (rank == random_rank and source < random_source):
            random_source = source
            random_rank = rank

    degrees = key_path.with_name(f".{key_path.name}.source_degrees")
    program = (
        'NR==1{source=$1;degree=1;next}'
        '$1==source{degree++;next}'
        '{print source,degree;source=$1;degree=1}'
        'END{if(NR>0)print source,degree}'
    )
    try:
        with degrees.open("wb") as output:
            subprocess.run(["awk", program, str(key_path)], check=True, stdout=output)
        with degrees.open("r", encoding="ascii") as stream:
            for line in stream:
                source_text, degree_text = line.split()
                record(int(source_text), int(degree_text))
    finally:
        degrees.unlink(missing_ok=True)
    if sources == 0:
        raise ValueError("cannot choose a reachable source from an empty graph")

    median_rank = (sources - 1) // 2
    cumulative = 0
    median_source = -1
    for degree in sorted(degree_histogram):
        cumulative += degree_histogram[degree]
        if cumulative > median_rank:
            median_source = representative[degree]
            break
    return {
        "default": high_source,
        "high_degree": high_source,
        "median_degree": median_source,
        "random_reachable": random_source,
    }


def _make_reciprocal_raw(input_keys: Path, output_raw: Path) -> None:
    program = (
        '{print $0;if($1!=$2){printf "%010d %010d\\n",$2+0,$1+0}}'
    )
    with output_raw.open("wb") as output:
        subprocess.run(["awk", program, str(input_keys)], check=True, stdout=output)


def _make_sink_free_keys(input_keys: Path, output_path: Path, vertices: int) -> None:
    temporary = output_path.with_name(f".{output_path.name}.partial")
    program = (
        'BEGIN{next_source=0}'
        '{s=$1+0;while(next_source<s){printf "%010d %010d\\n",'
        'next_source,next_source;next_source++}print $0;'
        'if(next_source==s){next_source++}}'
        'END{while(next_source<vertices){printf "%010d %010d\\n",'
        'next_source,next_source;next_source++}}'
    )
    with temporary.open("wb") as output:
        subprocess.run(
            ["awk", "-v", f"vertices={vertices}", program, str(input_keys)],
            check=True,
            stdout=output,
        )
    temporary.replace(output_path)


def _filter_deletable_sink_free_edges(
    sink_free_keys: Path, output_path: Path
) -> None:
    """Keep edges whose source retains at least one edge after one deletion."""

    temporary = output_path.with_name(f".{output_path.name}.partial")
    program = (
        'NR==1{source=$1;first=$0;count=1;next}'
        '$1!=source{source=$1;first=$0;count=1;next}'
        '{if(count==1){print first}count++}'
    )
    with temporary.open("wb") as output:
        subprocess.run(["awk", program, str(sink_free_keys)], check=True, stdout=output)
    temporary.replace(output_path)


def _head_keys(input_path: Path, output_path: Path, count: int) -> int:
    temporary = output_path.with_name(f".{output_path.name}.partial")
    with temporary.open("wb") as output:
        subprocess.run(
            ["head", "-n", str(max(0, count)), str(input_path)],
            check=True,
            stdout=output,
        )
    temporary.replace(output_path)
    return _line_count(output_path)


def _select_hash_partition(
    input_path: Path,
    output_path: Path,
    *,
    population: int,
    target: int,
    seed: int,
    temp_dir: Path | None = None,
    parallel: int = 1,
    memory: str = "256M",
) -> int:
    """Select the exact lowest edge-hash ranks, independent of input order."""

    target = min(target, population)
    if target <= 0:
        output_path.write_text("", encoding="ascii")
        return 0
    if target == population:
        return _head_keys(input_path, output_path, target)
    if parallel <= 0:
        raise ValueError("hash selection sort parallelism must be positive")

    scratch = temp_dir or output_path.parent
    scratch.mkdir(parents=True, exist_ok=True)
    prefix = f".{output_path.name}.hash"
    candidates = output_path.with_name(f"{prefix}.candidates")
    ranked = output_path.with_name(f"{prefix}.ranked")
    selected_ranked = output_path.with_name(f"{prefix}.selected")
    selected_edges = output_path.with_name(f"{prefix}.edges")
    temporary = output_path.with_name(f".{output_path.name}.partial")
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    threshold = max(
        1,
        min(
            HASH_MODULUS,
            math.ceil(target * HASH_MODULUS * 1.25 / population),
        ),
    )
    try:
        while True:
            program = (
                "{s=$1+0;d=$2+0;"
                "h=(s*1000003+d*9176+seed*53)%mod;"
                'if(h<threshold){printf "%010d %s\\n",h,$0}}'
            )
            with candidates.open("wb") as output:
                subprocess.run(
                    [
                        "awk",
                        "-v",
                        f"seed={seed}",
                        "-v",
                        f"mod={HASH_MODULUS}",
                        "-v",
                        f"threshold={threshold}",
                        program,
                        str(input_path),
                    ],
                    check=True,
                    stdout=output,
                )
            candidate_count = _line_count(candidates)
            if candidate_count >= target:
                break
            if threshold == HASH_MODULUS:
                raise ValueError(
                    f"hash selection expected {population} records but found "
                    f"only {candidate_count}"
                )
            threshold = min(HASH_MODULUS, threshold * 2)

        subprocess.run(
            [
                "sort",
                f"--parallel={parallel}",
                f"--buffer-size={memory}",
                f"--temporary-directory={scratch}",
                str(candidates),
                "--output",
                str(ranked),
            ],
            check=True,
            env=environment,
        )
        _head_keys(ranked, selected_ranked, target)
        with selected_edges.open("wb") as output:
            subprocess.run(
                ["cut", "--delimiter= ", "--fields=2-", str(selected_ranked)],
                check=True,
                stdout=output,
            )
        subprocess.run(
            [
                "sort",
                "--unique",
                f"--parallel={parallel}",
                f"--buffer-size={memory}",
                f"--temporary-directory={scratch}",
                str(selected_edges),
                "--output",
                str(temporary),
            ],
            check=True,
            env=environment,
        )
        selected = _line_count(temporary)
        if selected != target:
            raise ValueError(
                f"hash selection emitted {selected} unique edges; expected {target}"
            )
        temporary.replace(output_path)
        return selected
    finally:
        for path in (candidates, ranked, selected_ranked, selected_edges, temporary):
            path.unlink(missing_ok=True)


def _splitmix64(value: int) -> int:
    mask = (1 << 64) - 1
    value = (value + 0x9E3779B97F4A7C15) & mask
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & mask
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & mask
    return value ^ (value >> 31)


def _generate_static_insert_candidates(
    path: Path, *, vertices: int, seed: int, requested: int
) -> None:
    if vertices < 2:
        raise ValueError("cannot derive insertions for a graph with fewer than two vertices")
    candidates: set[tuple[int, int]] = set()
    count = max(65_536, requested * 64)
    for index in range(count):
        source = _splitmix64(seed + 2 * index) % vertices
        destination = _splitmix64(seed + 2 * index + 1) % vertices
        if source != destination:
            candidates.add((source, destination))
    with path.open("w", encoding="ascii") as output:
        for source, destination in sorted(candidates):
            _write_key(output, source, destination)


def _set_difference(left: Path, right: Path, output_path: Path) -> None:
    temporary = output_path.with_name(f".{output_path.name}.partial")
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    with temporary.open("wb") as output:
        subprocess.run(
            ["comm", "-23", str(left), str(right)],
            check=True,
            env=environment,
            stdout=output,
        )
    temporary.replace(output_path)


def _load_user_edges(path: Path, limit: int) -> list[tuple[int, int]]:
    selected: list[tuple[int, int]] = []
    seen_undirected: set[tuple[int, int]] = set()
    with path.open("r", encoding="ascii") as stream:
        for line in stream:
            source, destination = (int(value) for value in line.split())
            key = (min(source, destination), max(source, destination))
            if key in seen_undirected:
                continue
            seen_undirected.add(key)
            selected.append((source, destination))
            if len(selected) == limit:
                break
    return selected


def _write_update_slice(
    path: Path,
    *,
    case_id: str,
    vertices: int,
    records: list[tuple[int, int, int, int]],
) -> SliceMetadata:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        records,
        key=lambda item: (item[0], item[1], 0 if item[3] < 0 else 1, item[2]),
    )
    temporary = path.with_name(f".{path.name}.partial")
    with temporary.open("w", encoding="ascii") as output:
        output.write("# spine_real_slice_version=1\n")
        output.write(f"# case={case_id}\n")
        output.write(f"# vertices={vertices}\n")
        output.write("# columns=src dst weight diff\n")
        for source, destination, weight, difference in ordered:
            output.write(f"{source} {destination} {weight} {difference}\n")
    temporary.replace(path)
    return read_slice_metadata_streaming(path)


def _update_records(
    edges: list[tuple[int, int]], *, scenario: str, reciprocal: bool
) -> list[tuple[int, int, int, int]]:
    records: list[tuple[int, int, int, int]] = []
    for source, destination in edges:
        orientations = [(source, destination)]
        if reciprocal:
            orientations.append((destination, source))
        for oriented_source, oriented_destination in orientations:
            old_weight = canonical_edge_weight(oriented_source, oriented_destination)
            if scenario == "insert":
                records.append((oriented_source, oriented_destination, old_weight, 1))
            elif scenario == "delete":
                records.append((oriented_source, oriented_destination, old_weight, -1))
            elif scenario == "weight_change":
                records.append((oriented_source, oriented_destination, old_weight, -1))
                records.append(
                    (
                        oriented_source,
                        oriented_destination,
                        old_weight % 64 + 1,
                        1,
                    )
                )
            else:
                raise ValueError(f"unsupported update scenario: {scenario}")
    return records


def _derive_projection_updates(
    *,
    output_dir: Path,
    vertices: int,
    projection: str,
    graph_keys: Path,
    delete_keys: Path,
    post_base_keys: Path | None,
    batch_sizes: tuple[int, ...],
    seed: int,
    reciprocal: bool,
) -> list[dict[str, Any]]:
    maximum = max(batch_sizes)
    work = output_dir / ".work"
    prefix = projection.replace("/", "_")
    delete_population = _line_count(delete_keys)
    delete_selected = work / f"{prefix}.delete_selected.keys"
    _select_hash_partition(
        delete_keys,
        delete_selected,
        population=delete_population,
        target=min(delete_population, maximum * 16),
        seed=seed + 101,
    )
    delete_edges = _load_user_edges(delete_selected, maximum)

    candidate_keys = work / f"{prefix}.insert_candidates.keys"
    if post_base_keys is not None and post_base_keys.is_file():
        _set_difference(post_base_keys, graph_keys, candidate_keys)
    else:
        generated = work / f"{prefix}.generated_insert_candidates.keys"
        _generate_static_insert_candidates(
            generated, vertices=vertices, seed=seed + 211, requested=maximum
        )
        _set_difference(generated, graph_keys, candidate_keys)
    candidate_count = _line_count(candidate_keys)
    insert_selected = work / f"{prefix}.insert_selected.keys"
    _select_hash_partition(
        candidate_keys,
        insert_selected,
        population=candidate_count,
        target=min(candidate_count, maximum * 16),
        seed=seed + 307,
    )
    insert_edges = _load_user_edges(insert_selected, maximum)
    if max(len(delete_edges), len(insert_edges)) < min(batch_sizes):
        raise ValueError(
            f"no valid update mutations are available for {projection}"
        )

    artifacts: list[dict[str, Any]] = []
    for batch_size in batch_sizes:
        for scenario, edges in (
            ("insert", insert_edges[:batch_size]),
            ("delete", delete_edges[:batch_size]),
            ("weight_change", delete_edges[:batch_size]),
        ):
            if len(edges) < batch_size:
                continue
            records = _update_records(
                edges, scenario=scenario, reciprocal=reciprocal
            )
            case_id = f"{output_dir.name}_{projection}_{scenario}_u{batch_size}"
            metadata = _write_update_slice(
                output_dir
                / "updates"
                / projection
                / f"{scenario}_u{batch_size}.slice",
                case_id=case_id,
                vertices=vertices,
                records=records,
            )
            artifacts.append(
                {
                    **_artifact(metadata, role="dynamic_update"),
                    "projection": projection,
                    "scenario": scenario,
                    "user_mutations": batch_size,
                    "physical_records": len(records),
                }
            )
        if batch_size >= 2:
            delete_count = batch_size // 2
            insert_count = batch_size - delete_count
            if (
                len(delete_edges) < delete_count
                or len(insert_edges) < insert_count
            ):
                continue
            records = _update_records(
                delete_edges[:delete_count],
                scenario="delete",
                reciprocal=reciprocal,
            ) + _update_records(
                insert_edges[:insert_count],
                scenario="insert",
                reciprocal=reciprocal,
            )
            metadata = _write_update_slice(
                output_dir
                / "updates"
                / projection
                / f"mixed_u{batch_size}.slice",
                case_id=f"{output_dir.name}_{projection}_mixed_u{batch_size}",
                vertices=vertices,
                records=records,
            )
            artifacts.append(
                {
                    **_artifact(metadata, role="dynamic_update"),
                    "projection": projection,
                    "scenario": "mixed",
                    "user_mutations": batch_size,
                    "physical_records": len(records),
                }
            )
    return artifacts


def _derive_updates(
    *,
    output_dir: Path,
    vertices: int,
    base_keys: Path,
    reciprocal_keys: Path,
    post_base_keys: Path | None,
    batch_sizes: tuple[int, ...],
    seed: int,
) -> list[dict[str, Any]]:
    directed = _derive_projection_updates(
        output_dir=output_dir,
        vertices=vertices,
        projection="directed",
        graph_keys=base_keys,
        delete_keys=base_keys,
        post_base_keys=post_base_keys,
        batch_sizes=batch_sizes,
        seed=seed,
        reciprocal=False,
    )
    reciprocal = _derive_projection_updates(
        output_dir=output_dir,
        vertices=vertices,
        projection="reciprocal",
        graph_keys=reciprocal_keys,
        delete_keys=base_keys,
        post_base_keys=post_base_keys,
        batch_sizes=batch_sizes,
        seed=seed,
        reciprocal=True,
    )
    return directed + reciprocal


def materialize_publication_workload(
    spec: PublicationSourceSpec,
    output_dir: Path,
    *,
    sort_parallel: int = 8,
    sort_memory: str = "4G",
    batch_sizes: tuple[int, ...] = DEFAULT_BATCH_SIZES,
    pagerank_scales: tuple[int, ...] = DEFAULT_PAGERANK_SCALES,
    progress_path: Path | None = None,
    keep_intermediates: bool = False,
    seed: int = WEIGHT_SEED,
) -> dict[str, Any]:
    """Materialize one source without retaining the full graph in Python memory."""

    if sort_parallel <= 0 or not batch_sizes or not pagerank_scales:
        raise ValueError("materialization parallelism and workload scales must be positive")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work = output_dir / ".work"
    work.mkdir(parents=True, exist_ok=True)
    base_raw = work / "base.raw.keys"
    post_raw = work / "post_base.raw.keys"
    base_keys = work / "base.keys"
    post_keys = work / "post_base.keys"
    reciprocal_raw = work / "reciprocal.raw.keys"
    reciprocal_keys = work / "reciprocal.keys"
    residual_keys = work / "residual_sink_free.keys"
    residual_deletable_keys = work / "residual_sink_free_deletable.keys"

    source_size = spec.source_path.stat().st_size
    source_sha256 = sha256_file(spec.source_path)
    if (
        spec.expected_source_sha256 is not None
        and source_sha256 != spec.expected_source_sha256
    ):
        raise ValueError(f"source SHA-256 mismatch for {spec.dataset_id}")
    _progress(
        progress_path,
        dataset_id=spec.dataset_id,
        phase="normalize",
        completed=0,
        source_size_bytes=source_size,
    )
    normalization = _normalize_source(
        spec,
        base_raw=base_raw,
        post_base_raw=post_raw,
        progress_path=progress_path,
    )
    temp_dir = work / "sort_tmp"
    _sort_unique(
        base_raw,
        base_keys,
        temp_dir=temp_dir,
        parallel=sort_parallel,
        memory=sort_memory,
        spec=spec,
        phase="sort_base",
        progress_path=progress_path,
    )
    base_edges = _line_count(base_keys)
    if spec.expected_unique_edges is not None and base_edges != spec.expected_unique_edges:
        raise ValueError(
            f"{spec.dataset_id}: expected {spec.expected_unique_edges} unique edges, "
            f"materialized {base_edges}"
        )
    if normalization["post_input_records"] > 0:
        _sort_unique(
            post_raw,
            post_keys,
            temp_dir=temp_dir,
            parallel=sort_parallel,
            memory=sort_memory,
            spec=spec,
            phase="sort_post_base",
            progress_path=progress_path,
        )
        effective_post_keys: Path | None = post_keys
    else:
        effective_post_keys = None

    vertices = int(normalization["vertices"])
    directed_source_cohorts = _source_cohorts(base_keys, seed=seed + 503)
    directed_metadata = _decorate_slice(
        base_keys,
        output_dir / "graphs" / "directed_weighted.slice",
        case_id=f"{spec.dataset_id}_directed_full",
        vertices=vertices,
        seed=seed,
    )
    source_is_reciprocal = bool(normalization["source_projection_reciprocal"])
    if source_is_reciprocal:
        reciprocal_keys = base_keys
        reciprocal_metadata = directed_metadata
    else:
        _make_reciprocal_raw(base_keys, reciprocal_raw)
        _sort_unique(
            reciprocal_raw,
            reciprocal_keys,
            temp_dir=temp_dir,
            parallel=sort_parallel,
            memory=sort_memory,
            spec=spec,
            phase="sort_reciprocal",
            progress_path=progress_path,
        )
        reciprocal_metadata = _decorate_slice(
            reciprocal_keys,
            output_dir / "graphs" / "reciprocal_weighted.slice",
            case_id=f"{spec.dataset_id}_reciprocal_full",
            vertices=vertices,
            seed=seed,
        )

    _progress(
        progress_path,
        dataset_id=spec.dataset_id,
        phase="derive_residual_sink_free_graph",
    )
    _make_sink_free_keys(base_keys, residual_keys, vertices)
    _filter_deletable_sink_free_edges(residual_keys, residual_deletable_keys)
    residual_metadata = _decorate_slice(
        residual_keys,
        output_dir / "graphs" / "residual_sink_free_weighted.slice",
        case_id=f"{spec.dataset_id}_residual_sink_free_full",
        vertices=vertices,
        seed=seed,
    )
    if residual_metadata.unique_sources != vertices:
        raise ValueError("residual sink completion failed to cover every vertex")

    _progress(
        progress_path,
        dataset_id=spec.dataset_id,
        phase="derive_pagerank_slices",
        completed=0,
        total=len(pagerank_scales),
    )
    pagerank_artifacts: list[dict[str, Any]] = []
    pagerank_update_artifacts: list[dict[str, Any]] = []
    for index, requested in enumerate(pagerank_scales, start=1):
        actual = min(requested, base_edges)
        selected = work / f"pagerank_{requested}.keys"
        _select_hash_partition(
            base_keys,
            selected,
            population=base_edges,
            target=actual,
            seed=seed + 401,
            temp_dir=temp_dir,
            parallel=sort_parallel,
            memory=sort_memory,
        )
        metadata = _decorate_slice(
            selected,
            output_dir / "pagerank" / f"hash_e{requested}.slice",
            case_id=f"{spec.dataset_id}_full_pagerank_hash_e{requested}",
            vertices=vertices,
            seed=seed,
        )
        pagerank_artifacts.append(
            {
                **_artifact(metadata, role="full_pagerank_hash_slice"),
                "requested_edges": requested,
                "actual_edges": actual,
                "selection_policy": "exact_min_edge_hash_preserving_original_vertex_ids_v2",
            }
        )
        pagerank_update_artifacts.extend(
            _derive_projection_updates(
                output_dir=output_dir,
                vertices=vertices,
                projection=f"full_pagerank_e{requested}",
                graph_keys=selected,
                delete_keys=selected,
                post_base_keys=effective_post_keys,
                batch_sizes=batch_sizes,
                seed=seed,
                reciprocal=False,
            )
        )
        _progress(
            progress_path,
            dataset_id=spec.dataset_id,
            phase="derive_pagerank_slices",
            completed=index,
            total=len(pagerank_scales),
        )

    _progress(
        progress_path,
        dataset_id=spec.dataset_id,
        phase="derive_updates",
    )
    update_artifacts = _derive_updates(
        output_dir=output_dir,
        vertices=vertices,
        base_keys=base_keys,
        reciprocal_keys=reciprocal_keys,
        post_base_keys=effective_post_keys,
        batch_sizes=batch_sizes,
        seed=seed,
    )
    residual_update_artifacts = _derive_projection_updates(
        output_dir=output_dir,
        vertices=vertices,
        projection="residual_sink_free",
        graph_keys=residual_keys,
        delete_keys=residual_deletable_keys,
        post_base_keys=effective_post_keys,
        batch_sizes=batch_sizes,
        seed=seed,
        reciprocal=False,
    )
    manifest = {
        "schema_version": 1,
        "status": "pass",
        "dataset_id": spec.dataset_id,
        "generated_at_epoch_seconds": time.time(),
        "source": {
            "path": str(spec.source_path),
            "size_bytes": source_size,
            "sha256": source_sha256,
            "encoding": spec.source_encoding,
            "archive_member": spec.archive_member,
            "index_normalization": f"subtract_declared_base_{spec.index_base}",
            "endpoint_swap": spec.swap_endpoints,
            "semantic_projection": spec.semantic_projection,
            "paper_base_events": spec.paper_base_events,
        },
        "normalization": normalization,
        "weight_policy": {
            "id": "edge_hash_positive_uint16_v1",
            "formula": "1 + ((src*131 + dst*17 + seed*29) mod 64)",
            "seed": seed,
            "minimum": 1,
            "maximum": 64,
        },
        "capacity": {
            "spine_max_vertices": SPINE_MAX_VERTICES,
            "vertices": vertices,
            "spine_full_graph_admitted": vertices <= SPINE_MAX_VERTICES,
        },
        "graphs": {
            "directed": _artifact(
                directed_metadata,
                role="directed_weighted_full",
                source_cohorts=directed_source_cohorts,
            ),
            "reciprocal": _artifact(
                reciprocal_metadata, role="reciprocal_weighted_full"
            ),
            "residual_sink_free": {
                **_artifact(
                    residual_metadata,
                    role="directed_weighted_sink_completed_for_residual_pagerank",
                ),
                "projection": "add_self_loop_to_each_zero_outdegree_vertex_v1",
                "self_loops_added": residual_metadata.records - base_edges,
                "sink_vertices_after_projection": 0,
            },
            "same_artifact": source_is_reciprocal,
        },
        "full_pagerank_slices": pagerank_artifacts,
        "updates": (
            update_artifacts
            + residual_update_artifacts
            + pagerank_update_artifacts
        ),
        "materializer": {
            "sort_parallel": sort_parallel,
            "sort_memory": sort_memory,
            "key_width": KEY_WIDTH,
            "batch_sizes": list(batch_sizes),
            "pagerank_scales": list(pagerank_scales),
            "intermediates_retained": keep_intermediates,
        },
    }
    manifest_path = output_dir / "materialization_manifest.json"
    atomic_write_json(manifest_path, manifest)
    if not keep_intermediates:
        shutil.rmtree(work, ignore_errors=True)
    _progress(
        progress_path,
        dataset_id=spec.dataset_id,
        phase="complete",
        completed=1,
        total=1,
        status="pass",
        manifest_path=str(manifest_path),
    )
    return manifest
