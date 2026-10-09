"""Capture the original Big generator, cache wrapper and Scatter independently."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.sources import prepare_regraph, read_pins, verify_snapshot
from spine_cycle_sim.experiments.upstream_controls.study import compiler_command
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from .analysis import records


def capture(root: Path, source: Path, hls: Path, output: Path, contract: dict, compiler: str, execute) -> dict:
    pin = read_pins(root / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json")["regraph"]
    snapshot = verify_snapshot(source, pin)
    directory = output / "source_control"
    directory.mkdir()
    prepared = directory / "prepared"
    generated = prepare_regraph(source, prepared, 11, 3, contract["generator_python"])
    topology = {"id": "mixed", "little": 11, "big": 3}
    command = compiler_command(root, source.parent, {"mixed": {"directory": str(prepared)}},
        {"source": "regraph_big_probe.cpp", "topology": "mixed"}, topology, hls, compiler, directory)
    source_index = command.index(str(root / "cpp/tests/publication_sources/regraph_big_probe.cpp"))
    command[source_index] = str(root / "cpp/tests/publication_sources/regraph_big_frontend_probe.cpp")
    execute("source_compile", command, contract["build_timeout_seconds"])
    reports = []
    paths = []
    for name in ("first", "repeat"):
        path = directory / (name + ".u32le")
        row = execute("source_" + name, [str(directory / "probe"), str(path)], contract["run_timeout_seconds"])
        reports.append(Path(row["stdout"]).read_text())
        paths.append(path)
        observed = records(reports[-1], "BIG_FRONTEND_SOURCE")
        if ([(item.get("case"), item.get("bursts")) for item in observed] != list(zip(
                contract["source_cases"], contract["source_bursts"], strict=True)) or
                any(type(item.get("requests_including_end")) is not int or item["requests_including_end"] < 2 for item in observed) or
                Path(row["stderr"]).read_text()):
            raise ValueError("original Big source protocol capture failed")
    if reports[0] != reports[1] or sha256_file(paths[0]) != sha256_file(paths[1]):
        raise ValueError("original Big source repeat changed outputs")
    execute("source_ubsan_compile", [*command[:1], "-fsanitize=undefined", "-fno-sanitize-recover=all",
        *command[1:-1], str(directory / "probe_ubsan")], contract["build_timeout_seconds"])
    instrumented = directory / "ubsan.u32le"
    row = execute("source_ubsan", [str(directory / "probe_ubsan"), str(instrumented)], contract["run_timeout_seconds"])
    if (Path(row["stdout"]).read_text() != reports[0] or Path(row["stderr"]).read_text() or
            sha256_file(instrumented) != sha256_file(paths[0])):
        raise ValueError("original Big source UBSan changed output or reported diagnostics")
    if verify_snapshot(source, pin) != snapshot: raise ValueError("original Big source snapshot changed")
    return {"snapshot": snapshot, "generated": generated,
        "dependencies": dependency_identities(directory / "dependencies.d", root),
        "binaries": [{"path": str(directory / name), "sha256": sha256_file(directory / name)} for name in ("probe", "probe_ubsan")],
        "capture": {"path": str(paths[0]), "sha256": sha256_file(paths[0]), "bytes": paths[0].stat().st_size},
        "cases": records(reports[0], "BIG_FRONTEND_SOURCE"), "repeated_and_ubsan_identical": True}
