"""Freeze unchanged production hosts and the complete 24-input matrix."""

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

DATASETS = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
ALGORITHMS = ("weighted_sssp", "connected_components", "residual_pagerank")
DEFINES = {"weighted_sssp": [], "connected_components": ["GRASU_REGRAPH_CONNECTED_COMPONENTS=1"],
           "residual_pagerank": ["GRASU_REGRAPH_RESIDUAL_PAGERANK=1"],
           "full_pagerank": ["GRASU_REGRAPH_FULL_PAGERANK=1"]}
PREFIXES = {"weighted_sssp": "WEIGHTED_PMA_NATIVE_SHARDED",
            "connected_components": "CC_PMA_NATIVE_SHARDED",
            "residual_pagerank": "RESIDUAL_PR_PMA_NATIVE_SHARDED"}


def identity(path):
    path = path.absolute()
    before = stamp(path)
    digest = sha256_file(path)
    if stamp(path) != before:
        raise ValueError("file changed while hashing")
    return {"path": str(path), "sha256": digest, **before}


def stamp(path):
    state = path.stat()
    return {"resolved_path": str(path.resolve()), "stat": {
        key: getattr(state, key) for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}}


def unchanged(pins, *, full=False):
    # Hash small files even on polls: some filesystems coarsen ctime. Full hashes
    # at admission/completion cover large inputs without rereading GB per poll.
    if any((identity(Path(pin["path"])) != pin if full or pin["stat"]["st_size"] <= 1024**2 else
            stamp(Path(pin["path"])) != {key: pin[key] for key in ("resolved_path", "stat")}) for pin in pins):
        raise ValueError("frozen host, tool, input or runner changed")


def matrix(manifest):
    contents = json.loads(manifest.read_text())
    rows = contents.get("records", [])
    if contents.get("status") != "pass" or contents.get("batch_size") != 8:
        raise ValueError("admitted insertion/u8 workload manifest required")
    keys = [(row["dataset"], row["algorithm"]) for row in rows]
    if len(keys) != 24 or set(keys) != {(d, a) for d in DATASETS for a in ALGORITHMS}:
        raise ValueError("exact eight-graph/three-algorithm matrix required")
    for row in rows:
        for field in ("vertices", "initial_edges", "updates", "source"):
            if type(row.get(field)) is not int or row[field] < 0:
                raise ValueError("integer workload dimensions required")
        if (not 0 <= row["source"] < row["vertices"] or row["vertices"] > 255 * 65536 or
                row["updates"] != (16 if row["algorithm"] == "connected_components" else 8)):
            raise ValueError("workload exceeds declared source, partition or batch contract")
        path = Path(row["graph"])
        pin = identity(path)
        if path.is_symlink() or not path.is_file() or pin["sha256"] != row["sha256"]:
            raise ValueError("regular frozen graph with matching SHA-256 required")
        with path.open() as stream:
            header = [int(value) for value in stream.readline().split()]
        if header != [row["vertices"], row["initial_edges"], row["updates"]]:
            raise ValueError("graph header differs from frozen workload dimensions")
        row["input_identity"] = pin
    lookup = dict(zip(keys, rows, strict=True))
    return [lookup[d, a] for d in DATASETS for a in ALGORITHMS]


def freeze(integration, manifest, output):
    rows = matrix(manifest)
    frozen = freeze_sources(integration, output)
    return {**frozen, "rows": rows, "pins": [identity(manifest),
            *[row["input_identity"] for row in rows], *frozen["pins"]]}


def freeze_sources(integration, output, *, extra_tools=()):
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=integration).strip():
        raise ValueError("clean production host worktree required")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=integration, text=True).strip()
    pins = []
    source = output / "source"
    paths = sorted((integration / "include").rglob("*.h"))
    paths += sorted((integration / "include").rglob("*.hpp"))
    paths += [integration / "tools" / name for name in (
        "weighted_pma_native_host.cpp", "sharded_k4_native_host.cpp", "sharded_k4_pagerank_native_host.cpp",
        *extra_tools)]
    for original in paths:
        if original.is_symlink() or not original.is_file():
            raise ValueError("regular production host source required")
        before = identity(original)
        copied = source / original.relative_to(integration)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, copied)
        if identity(copied)["sha256"] != before["sha256"]:
            raise ValueError("host source changed while copying")
        pins += [before, identity(copied)]
    unchanged(pins)
    return {"revision": revision, "source": str(source), "pins": pins}


def smokes(output):
    rows = []
    for algorithm in ALGORITHMS:
        cc = algorithm == "connected_components"
        original = Path(__file__).parent / "fixtures" / ("cc.graph" if cc else "directed.graph")
        copied = output / (algorithm + ".smoke.graph")
        shutil.copy2(original, copied)
        rows.append({"dataset": "SMOKE", "algorithm": algorithm, "vertices": 327681,
                     "initial_edges": 6 if cc else 3, "updates": 2 if cc else 1,
                     "source": 0, "graph": str(copied)})
    return rows


def compile_command(compiler, source, algorithm, binary, xrt, hls):
    name = ("sharded_k4_pagerank_native_host.cpp" if algorithm in ("residual_pagerank", "full_pagerank")
            else "sharded_k4_native_host.cpp")
    return [str(compiler), "-std=c++17", "-O2", "-g0", "-Wall", "-Wextra", "-Werror", "-fdiagnostics-format=json",
            "-D_GLIBCXX_ASSERTIONS", "-DGRASU_MAX_CACHE_SEGMENT=131072",
            "-DGRASU_REGRAPH_HOST_ROW_LINE_READ=1", *["-D" + flag for flag in DEFINES[algorithm]],
            "-MD", "-MF", str(binary.with_suffix(".d")), "-MT", "probe",
            *["-I" + str(path) for path in (xrt / "include", hls / "include", hls / "include/etc", source / "include")],
            str(source / "tools" / name), "-L" + str(xrt / "lib"),
            "-Wl,-rpath," + str(xrt / "lib"), "-lxilinxopencl", "-lpthread", "-o", str(binary)]


def prepare_command(binary, row, result):
    command = [str(binary), "--prepare-only", str(row["graph"]), str(result)]
    return command if row["algorithm"] == "residual_pagerank" else [*command, str(row["source"]), "256"]
