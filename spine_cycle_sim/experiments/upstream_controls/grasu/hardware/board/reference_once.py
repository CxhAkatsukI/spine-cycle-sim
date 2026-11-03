"""Build a one-batch public-source G control from the frozen probe sources."""

import argparse
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity, save


SOURCES = {
    "01_grasu_gap_control.cpp": "7808d15af533107366cf6f4a522e6a872a00e9849304e168928c482367251b82",
    "02_grasu_gap_model.hpp": "57100097bf5627f10fb71c16e8b5097d5c3bde85518cc1e1f24476997281d1e9",
    "03_weighted_pma_graph.hpp": "e246456d9bce914d079b8e8dad62700c75289db9406655ef5a73801d63ecb514",
    "04_weighted_pma_runtime_plan.hpp": "39d4bb5b6325875202b525c4e4e5a0e36a133dd45d8b1dcc0279b97bde0afc49",
    "05_weighted_pma_update_reference.hpp": "103122b02d166f500907322a227dccbd630a68c4efacbd54002e6669e50ea625",
    "06_runtime.hpp": "9c77ba7367e653e7a53fe383b2baa5989bc9ace3abbd730881878397552aa0a6",
    "07_model.hpp": "5fa1b41443e048d4d944024d6b673a50bae00dd275d15f0795ade8b1770d08e9",
}
PATCH = Path(__file__).with_suffix(".patch")
XRT = Path("/opt/xilinx/xrt")


def build(frozen, output, compiler):
    pins = [identity(frozen / name) for name in SOURCES]
    if any(pin["sha256"] != expected for pin, expected in zip(pins, SOURCES.values())):
        raise ValueError("archived G probe source differs from the frozen campaign")
    output.mkdir(parents=True, exist_ok=False)
    sources = output / "source"
    sources.mkdir()
    compiler = compiler.resolve(strict=True)
    library = XRT / "lib/libxilinxopencl.so"
    binary = output / "original_g_once"
    command = [str(compiler), "-std=c++20", "-O2", "-DNDEBUG", "-Wall", "-Wextra",
               "-Wpedantic", "-Werror", "-I" + str(XRT / "include"),
               str(sources / "grasu_gap_control.cpp"), "-o", str(binary), str(library),
               "-Wl,-rpath," + str(library.parent)]
    report = {"status": "BUILDING_NOT_BOARD", "input_sources": pins, "patch": identity(PATCH),
              "builder": identity(__file__), "compiler": identity(compiler), "xrt_library": identity(library),
              "command": command, "repetitions": 1, "board_tested": False}
    manifest = output / "manifest.json"
    save(manifest, report)
    try:
        for pin, name in zip(pins, SOURCES):
            staged = sources / name[3:]
            shutil.copyfile(pin["path"], staged)
            if identity(staged)["sha256"] != pin["sha256"]:
                raise ValueError("frozen G source changed while staging")
        with (output / "patch.log").open("x") as log:
            subprocess.run(["patch", "--batch", "--forward", "--fuzz=0", "-p0", "-i", str(PATCH)],
                           cwd=sources, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=5)
        report["built_sources"] = [identity(path) for path in sorted(sources.iterdir())]
        report["compiler_version"] = subprocess.check_output([compiler, "--version"], text=True, timeout=5)
        with (output / "compile.log").open("x") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=90, check=True)
        report.update(status="HOST_BUILD_PASS_NOT_BOARD", binary=identity(binary))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report.update(status="HOST_BUILD_FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(manifest, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compiler", type=Path, default=Path("/usr/bin/x86_64-linux-gnu-g++-15"))
    args = parser.parse_args()
    print(build(args.frozen.resolve(), args.output.resolve(), args.compiler)["status"])
