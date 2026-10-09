"""Generate unmodified author Big routing/Gather/merger functional captures."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from spine_cycle_sim.experiments.upstream_controls.sources import prepare_regraph, read_pins, verify_snapshot
from .analysis import records


def capture_source(root: Path, output: Path, source: Path, hls: Path, contract: dict, compiler: str, execute) -> dict:
    pins = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json"
    pin = read_pins(pins)["regraph"]
    identity = verify_snapshot(source, pin)
    prepared = output / "prepared"
    generated = prepare_regraph(source, prepared, 11, 3, contract["generator_python"])
    binary = output / "original_big_probe"
    dependency = output / "source_dependencies.d"
    command = [compiler, "-std=c++17", "-O1", "-g0", "-Wno-unknown-pragmas", "-Wno-deprecated-declarations",
        "-DDISABLE_MAX_HLS_STREAM_DEPTH_PRINT", "-DSW_EMU", "-DLITTLE_KERNEL_NUM=11", "-DBIG_KERNEL_NUM=3",
        "-DLITTLE_KERNEL_DST_BUFFER_SIZE=65536", "-DBIG_KERNEL_DST_BUFFER_SIZE=524288", "-DSRC_BUFFER_SIZE=4096",
        "-DLOG2_SRC_BUFFER_SIZE=12", "-DHAVE_APPLY_OUTDEG=1", "-DHAVE_VERTEX_PROP=0", "-DHAVE_UNSIGNED_PROP=0",
        "-MD", "-MF", str(dependency), "-MT", "probe", f"-I{hls}"]
    for directory in (".", "acc_template/common", "acc_udfs/pr", "acc_template/kernel_big_gs",
                      "acc_template/kernel_big_gs_merger"):
        command.append(f"-I{prepared / directory}")
    command += [str(root / "cpp/tests/publication_sources/regraph_big_gather_probe.cpp"), "-pthread", "-lgmp", "-o", str(binary)]
    execute("source_compile", command, contract["build_timeout_seconds"])
    capture = output / "big_source.u32le"
    reference_text = None
    for repetition in ("first", "repeat"):
        observed = output / ("big_source.u32le" if repetition == "first" else "big_source_repeat.u32le")
        step = execute("source_" + repetition, [str(binary), str(observed)], contract["run_timeout_seconds"])
        text = Path(step["stdout"]).read_text()
        if (records(text, "BIG_SOURCE") != [{"cases": 4, "checked_words": 2097152, "big": 3,
                                             "boundary": "dispatch_to_global_merger"}] or
                Path(step["stderr"]).read_text() or observed.stat().st_size != contract["checked_source_words"] * 4):
            raise ValueError("original Big source capture/stream extent failed")
        if repetition == "first":
            reference_text = text
        elif text != reference_text or sha256_file(observed) != sha256_file(capture):
            raise ValueError("original Big source repetition changed outputs")
    if verify_snapshot(source, pin) != identity:
        raise ValueError("original Big source changed during capture")
    return {"snapshot": identity, "generated": generated, "dependencies": dependency_identities(dependency, root),
            "binary": {"path": str(binary), "sha256": sha256_file(binary)},
            "capture": {"path": str(capture), "sha256": sha256_file(capture), "bytes": capture.stat().st_size},
            "repeated_identically": True, "timing_measured": False}
