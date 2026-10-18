"""Compile the standalone XRT host and replay its oracle, without a board call."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.runtime import library_paths
from .. import configuration as config
from . import preparation

STATUS = "ORIGINAL_G_BOARD_HOST_PREFLIGHT_PASS_NOT_BOARD_OR_TIMING"
CPP = Path("cpp/tests/publication_sources/grasu_board")


def compiler_command(root, xrt, output, compiler, *, sanitizer):
    command = [compiler, "-std=c++17", "-O1" if sanitizer else "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-Werror",
               "-MD", "-MT", "probe", "-MF", str(output / "dependencies.d")]
    if sanitizer:
        command += ["-DORIGINAL_G_MODEL_ONLY", "-fsanitize=undefined", "-fno-sanitize-recover=all"]
    else:
        command += ["-I" + str(xrt / "include")]
    command += [str(root / CPP / "control.cpp"), "-o", str(output / "probe")]
    if not sanitizer:
        command += ["-L" + str(xrt / "lib"), "-Wl,-rpath," + str(xrt / "lib"), "-lxilinxopencl"]
    return command


def inspect_model(stdout, stderr, row):
    lines = stdout.read_text().splitlines()
    if stderr.read_bytes() or len(lines) != 1 or not lines[0].startswith("ORIGINAL_G_MODEL "):
        raise ValueError("original G model diagnostics")
    observed = json.loads(lines[0].removeprefix("ORIGINAL_G_MODEL "))
    expected = {"status": "PASS_NOT_BOARD", **{key: row["facts"][key] for key in
                ("vertices", "segments", "updates", "route_updates")},
                "checked_slots_including_guards": row["expected_slots_including_guards"]}
    if observed != expected:
        raise ValueError("original G model counters differ")
    return observed


def run(root: Path, baseline: Path, xrt: Path, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING_ORIGINAL_G_BOARD_HOST", "errors": [], "steps": [], "cases": [],
              "binaries": [], **dict.fromkeys(config.FLAGS, False), "board_programmed": False,
              "measured_FPGA_cycles": None, "evidence_class": "host_compile_and_independent_oracle_only"}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        compiler = shutil.which("g++")
        if compiler is None or not (xrt / "include/CL/cl_ext_xilinx.h").is_file():
            raise ValueError("real XRT headers and G++ required")
        report["compiler_version"] = subprocess.check_output([compiler, "--version"], text=True)
        manifest = preparation.prepare(baseline, output / "inputs")
        pins = [identity(path) for path in sorted((root / CPP).glob("*")) if path.is_file()]
        pins += [identity(Path(compiler).resolve()), identity(output / "inputs/manifest.json")]
        pins += [row["packet"] for row in manifest["cases"]]
        pins += [identity(Path(module.__file__)) for name, module in sorted(sys.modules.items())
                 if name.startswith("spine_cycle_sim.") and getattr(module, "__file__", None)]
        report["pins"] = pins
        environment = dict(os.environ)
        for name in ("XRT_INI_PATH", "XCL_EMULATION_MODE", "LD_PRELOAD", "LD_LIBRARY_PATH"):
            environment.pop(name, None)

        def execute(name, command, *, expected=0):
            print("Original G host preflight: " + name + " (not board timing)", flush=True)
            child = run_link(command, root, output / name, timeout=600, tree_memory_gib=4,
                             reserve_gib=32, poll_seconds=0.2, environment=environment)
            report["steps"].append({"id": name, **child})
            save()
            if child["exit_code"] != expected or child["stop_reason"] != "process_exit" or child["cleanup_snapshot_error"]:
                raise ValueError("original G host preflight failed: " + name)
            return output / (name + ".stdout.txt"), output / (name + ".stderr.txt")

        for variant in ("release", "ubsan"):
            directory = output / variant
            directory.mkdir()
            execute("compile_" + variant, compiler_command(root, xrt, directory, compiler, sanitizer=variant == "ubsan"))
            dependencies = dependency_identities(directory / "dependencies.d", root)
            report["binaries"].append({"variant": variant, **identity(directory / "probe"), "dependencies": dependencies})
            pins += [identity(directory / "probe"), *dependencies]
            if variant == "release":
                loader = shutil.which("ldd")
                if loader is None:
                    raise ValueError("ldd required to freeze real Xilinx runtime dependencies")
                stdout, stderr = execute("inspect_release_loader", [loader, str(directory / "probe")])
                if stderr.read_bytes():
                    raise ValueError("original G runtime loader diagnostic")
                libraries = library_paths(stdout.read_text())
                libraries += [(xrt / "lib/libxrt_core.so.2").resolve(strict=True), Path(loader).resolve(strict=True)]
                report["runtime_libraries"] = [identity(path) for path in sorted(set(libraries))]
                pins += report["runtime_libraries"]
            for row in manifest["cases"]:
                stdout, stderr = execute(variant + "_" + row["id"],
                    [str(directory / "probe"), "--self-test", row["packet"]["path"]])
                report["cases"].append({"variant": variant, "id": row["id"], **inspect_model(stdout, stderr, row)})
        negative = output / "bad-input.ogb"
        negative.write_bytes(b"OGB1" + bytes(16))
        for variant in ("release", "ubsan"):
            stdout, stderr = execute("reject_bad_header_" + variant,
                [str(output / variant / "probe"), "--self-test", str(negative)], expected=1)
            if stdout.read_bytes() or stderr.read_text() != "original G packet header\n":
                raise ValueError("original G failed to reject packet header")
        for pin in [*pins, *manifest["pins"]]:
            if identity(Path(pin["path"])) != pin:
                raise ValueError("original G host input/dependency changed")
        report["status"] = STATUS
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save()
    return report
