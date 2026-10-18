"""Freeze the real production host implementation without rebuilding its graph."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity

CPP = Path("cpp/tests/evaluation_impact/common_g")


def freeze(root, integration, output):
    groups = {
        "matched_original": sorted((root / CPP / "matched_original").glob("*.?pp")),
        "continuous_board": sorted((root / CPP / "continuous_board").glob("*.?pp")),
        "host_prepared": [root / CPP / "complete_pipeline/host_prepared/input.hpp"],
        "original_g_board": [root / "cpp/tests/publication_sources/grasu_board/model.hpp"],
        "host": [integration / "include" / name for name in
                 ("weighted_pma_graph.hpp", "weighted_pma_runtime_plan.hpp", "weighted_pma_update_reference.hpp")],
    }
    pins = []
    for group, paths in groups.items():
        if not paths:
            raise ValueError("missing matched-G source group: " + group)
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise ValueError("regular matched-G source required")
            before = identity(path)
            target = output / group / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError("matched-G source destination already exists")
            shutil.copy2(path, target)
            pin = identity(target)
            if pin["sha256"] != before["sha256"] or identity(path) != before:
                raise ValueError("matched-G source changed while freezing")
            pins.append({"original": str(path), **pin})
    return pins


def command(source, xrt, compiler, binary, *, sanitizer=False):
    argv = [compiler, "-std=c++20", "-O1" if sanitizer else "-O3", "-DNDEBUG", "-g0",
            "-Wall", "-Wextra", "-Werror", "-D_GLIBCXX_ASSERTIONS", "-MD", "-MT", "probe",
            "-MF", str(binary.with_suffix(".d")), "-I" + str(source)]
    if sanitizer:
        argv += ["-DMATCHED_G_MODEL_ONLY", "-fsanitize=undefined", "-fno-sanitize-recover=all"]
    else:
        argv += ["-isystem", str(xrt / "include")]
    argv += [str(source / "matched_original/control.cpp"), "-o", str(binary)]
    if not sanitizer:
        argv += ["-L" + str(xrt / "lib"), "-Wl,-rpath," + str(xrt / "lib"), "-lxilinxopencl", "-pthread"]
    return argv
