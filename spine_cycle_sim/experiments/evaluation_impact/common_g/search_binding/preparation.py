"""Freeze the search network and the production sources defining its ABI."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..study import ROOT
from ..search_pipeline.preparation import SOURCE

COUNTS = (0, 1, 63, 64, 65, 127, 128, 129, 257)
KEYS = ("generation", "updates", "same_key", "alias", "stalled")
MATRIX = tuple((generation, count, key, alias, stalled)
               for generation in range(2) for count in COUNTS for key in range(2)
               for alias in range(3) for stalled in range(2))


def prepare(output: Path, integration: Path):
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    shutil.copytree(ROOT / SOURCE, source / SOURCE)
    runner = source / "runner"
    shutil.copytree(Path(__file__).parent, runner, ignore=shutil.ignore_patterns("__pycache__"))
    for relative in ("spine_cycle_sim/experiments/campaign_runtime.py",
                     "spine_cycle_sim/experiments/upstream_controls/execution.py"):
        shutil.copy2(ROOT / relative, runner / Path(relative).name)
    production = source / "production"
    production.mkdir()
    pins = []
    for path in (integration / "repos/GraSU/GraSU/GraSU_kernels/src/kernel_bin_search.cpp",
                 integration / "tools/sharded_k4_native_host.cpp"):
        frozen = production / path.name
        shutil.copy2(path, frozen)
        pins.append({"original_path": str(path.resolve()), "path": str(frozen),
                     "sha256": sha256_file(frozen)})
    pinned = {entry["path"] for entry in pins}
    pins.extend({"path": str(path), "sha256": sha256_file(path)}
                for path in sorted(source.rglob("*")) if path.is_file() and str(path) not in pinned)
    return pins


def command(source: Path, include: Path, compiler: str, binary: Path):
    return [compiler, "-std=c++14", "-O2", "-pthread", "-Wno-unknown-pragmas",
            "-MMD", "-MF", str(binary.with_suffix(".d")), "-MT", "probe",
            "-D_GTHREAD_USE_COND_INIT_FUNC", "-DSEARCH_PIPELINE_SOURCE_TOP",
            "-I" + str(include), "-I" + str(include / "etc"),
            str(source / SOURCE / "hls/search_binding/control.cpp"), "-o", str(binary)]
