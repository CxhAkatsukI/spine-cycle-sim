"""Compile and compare independent UBSan executables for component gates."""

from __future__ import annotations

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


def sanitize_cases(root: Path, output: Path, compiler: str, execute, cases: dict,
                   build_timeout: int, run_timeout: int) -> list[dict]:
    sources = [root / "cpp/src" / name for name in ("scheduler.cpp", "axi.cpp", "memory_backend.cpp")]
    sources.extend(sorted((root / "cpp/src/original_regraph").glob("*.cpp")))
    binaries = []
    for name, (source, args, expected) in cases.items():
        binary = output / f"ubsan_{name}"
        execute(f"ubsan_compile_{name}", [compiler, "-std=c++20", "-O1", "-g0", "-Wall", "-Wextra",
                "-Wpedantic", "-Werror", "-fsanitize=undefined", "-fno-sanitize-recover=all",
                "-D_GLIBCXX_ASSERTIONS", f"-I{root / 'cpp/include'}", *map(str, sources),
                str(root / "cpp/tests/original_regraph" / source), "-o", str(binary)], build_timeout)
        run = execute(f"ubsan_{name}", [str(binary), *args], run_timeout)
        if Path(run["stdout"]).read_text() != expected or Path(run["stderr"]).read_text():
            raise ValueError(f"UBSan {name} changed results or reported diagnostics")
        binaries.append({"path": str(binary), "sha256": sha256_file(binary)})
    return binaries
