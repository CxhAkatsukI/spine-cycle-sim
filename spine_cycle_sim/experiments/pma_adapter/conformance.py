"""Real HLS source and finite-reader captures, including cold/stale selection."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..upstream_controls.execution import dependency_identities


def run(root: Path, output: Path, include: Path, compiler: str, execute):
    binaries = []
    for name in ("normal", "ubsan"):
        directory = output / name
        directory.mkdir()
        flags = [compiler, "-std=c++20", "-O1", "-g0", "-D_GLIBCXX_ASSERTIONS", "-DDISABLE_MAX_HLS_STREAM_DEPTH_PRINT",
            "-Wno-unknown-pragmas", "-MD", "-MT", "probe", "-MF", str(directory / "dependencies.d"),
            f"-I{include}", f"-I{include / 'etc'}", f"-I{output / 'source'}",
            "-DGRASU_REGRAPH_WEIGHTED_PMA=0", "-DGRASU_REGRAPH_DESTINATION_ONLY=1",
            "-DGRASU_REGRAPH_SHARDED_PMA=1", "-DGRASU_REGRAPH_SHARE_ALL_MEMORY_PORTS=1"]
        if name == "ubsan":
            flags += ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
        binary = directory / "probe"
        execute("routing_" + name + "_compile", flags + [str(root / "cpp/tests/publication_sources/adapter_routing_probe.cpp"), "-pthread", "-lgmp", "-o", str(binary)])
        binaries.append({"path": str(binary), "sha256": sha256_file(binary), "dependencies": dependency_identities(directory / "dependencies.d", root)})
    steps = []
    for name, family in (("source_first", "normal"), ("source_repeat", "normal"), ("source_ubsan", "ubsan")):
        directory = output / name
        directory.mkdir()
        steps.append(execute(name, [str(output / family / "probe"), str(directory)]))
    finite = output / "finite"
    finite.mkdir()
    steps.append(execute("finite_routing", [str(output / "build/cpp/pma_adapter_tests"), str(finite)]))
    for step in steps:
        if Path(step["stderr"]).read_text():
            raise ValueError("adapter routing source/finite diagnostics")
    captures = []
    for cache in (0, 1, 3):
        files = [output / name / f"cache{cache}.u32le" for name in ("source_first", "source_repeat", "source_ubsan", "finite")]
        digests = [sha256_file(path) for path in files]
        if len(set(digests)) != 1 or any(path.stat().st_size != 768 for path in files):
            raise ValueError("source/finite complete routing/stale-copy capture mismatch")
        captures.extend({"path": str(path), "bytes": 768, "sha256": digests[0]} for path in files)
    return {"all_source_repeat_UBSan_and_finite_packets_identical": True, "captures": captures, "binaries": binaries}


def compile_ubsan(root: Path, output: Path, compiler: str, execute):
    sources = [root / "cpp/src" / name for name in ("scheduler.cpp", "axi.cpp", "memory_backend.cpp")]
    sources += sorted((root / "cpp/src/original_regraph").glob("*.cpp"))
    sources += [root / "cpp/src/pma_adapter/reader.cpp"]
    binary = output / "ubsan_pma_r"
    flags = [compiler, "-std=c++20", "-O1", "-g0", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        "-fsanitize=undefined", "-fno-sanitize-recover=all", "-D_GLIBCXX_ASSERTIONS", f"-I{root / 'cpp/include'}"]
    execute("pma_r_ubsan_compile", flags + list(map(str, sources)) + [str(root / "cpp/tests/pma_adapter/whole_execution.cpp"), "-o", str(binary)])
    return {"path": str(binary), "sha256": sha256_file(binary)}
