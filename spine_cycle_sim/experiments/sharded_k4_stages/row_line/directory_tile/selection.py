"""Select portable evidence without compiler caches or duplicated state matrices."""

from pathlib import Path

from ..delivery import raw_files
from ..continuous_directory.study import ROOT
from .recheck import read


def selected(model, hls, regression, basis, legacy_basis, study):
    files = []
    for run, prefix, directories in (
        (model, "model", ("raw", "inputs", "states")),
        (hls, "hls", ("reference", "candidate", "functional")),
        (regression, "regression", ("legacy-after",)),
        (legacy_basis, "legacy_basis", ("cases", "campaign")),
    ):
        for directory in directories:
            if (run / directory).exists():
                files += raw_files(run / directory, prefix + "/" + directory)
        for path in sorted(run.iterdir()):
            if path.is_file() and path.suffix in {".json", ".txt", ".gz"}:
                files.append((path, prefix + "/" + path.name))
    for pin in read(model / "results.json")["build_files"]:
        path = Path(pin["path"])
        files.append((path, "model/build/" + path.relative_to(model / "build").as_posix()))
    for path in sorted((hls / "production").rglob("*")):
        relative = path.relative_to(hls / "production")
        if path.is_symlink():
            raise ValueError("symlinked production evidence")
        if path.is_file() and (path.suffix in {".xml", ".rpt"} or
                ("build" not in relative.parts and path.suffix in {".xo", ".json", ".txt", ".log"})):
            files.append((path, "hls/production/" + relative.as_posix()))
    reference = next(Path(pin["path"]) for pin in read(hls / "manifest.json")["pins"]
                     if Path(pin["path"]).suffix == ".xo")
    files.append((reference, "reference.xo"))
    for name in ("results.json", "manifest.json"):
        files.append((basis / name, "basis/" + name))
    for path in sorted((basis / "raw").glob("*.stdout.txt")):
        if path.stem.endswith(("original.stdout", "cross_row.stdout")):
            files.append((path, "basis/raw/" + path.name))
    files += [(regression / "plugin/libspine_cycle.so", "regression/plugin/libspine_cycle.so"),
              (regression / "core/Testing/Temporary/LastTest.log", "regression/core/Testing/Temporary/LastTest.log"),
              (regression / "core/CMakeCache.txt", "regression/core/CMakeCache.txt"),
              (ROOT / "configs/experiments/grasu_component_refactor_v1.json", "regression/contract.json")]
    # Intermediate/failed checkpoints retain raw timing, commands and frozen
    # sources, but only the final admitted matrix duplicates full state buffers.
    retained = ("model-v1", "model-packet-v1", "model-bank-v1", "model-bank-beats-v1",
                "model-bank-beats-v2", "model-bank-beats-v3", "hls-bank-v1", "verification-v2", "verification-v4")
    for name in retained:
        run = study / name
        if not run.is_dir():
            raise ValueError("missing negative/intermediate checkpoint: " + name)
        for path in sorted(run.iterdir()):
            if path.is_file() and path.suffix in {".json", ".txt", ".gz"}:
                files.append((path, "development/" + name + "/" + path.name))
        if (run / "raw").is_dir():
            files += raw_files(run / "raw", "development/" + name + "/raw")
    for name in ("pre-edit", "pre-beat-stream"):
        files += raw_files(study / name, "development/" + name)
    for path in sorted(Path(__file__).parent.glob("*.py")):
        files.append((path, "review_code/" + path.name))
    files.append((Path(__file__).parent.parent / "continuous_directory/archive_parts.py",
                  "review_code/transport/archive_parts.py"))
    files.append((study / "failed_transport.json", "development/failed_transport.json"))
    files.append((ROOT / "tests/test_sharded_k4_directory_tile.py", "review_code/tests/test_sharded_k4_directory_tile.py"))
    files.append((ROOT / "tests/test_sharded_k4_directory_tile_delivery.py",
                  "review_code/tests/test_sharded_k4_directory_tile_delivery.py"))
    unique = {}
    for path, name in files:
        if path.is_symlink() or (name in unique and unique[name] != path):
            raise ValueError("conflicting or symlinked archive path")
        unique[name] = path
    return [(path, name) for name, path in sorted(unique.items())]
