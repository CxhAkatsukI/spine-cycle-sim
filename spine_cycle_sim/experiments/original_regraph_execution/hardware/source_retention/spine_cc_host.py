"""Build the frozen Spine CC repair host with resident wall-clock reporting."""

import argparse
from pathlib import Path
import shutil
import subprocess

from .runtime import check_memory, identity, save


HOST_DIR = Path("tests/test_integration")
HOST = "host_cc_repair.cpp"
ABI = "fcadde28526ca8708621b3645bd039e07a2613eeb88eb798f965a01b80221028"
INPUT_TUS = {
    HOST: "82ccd01e626f1a22802159346ee795b231fda4e41cf1fc09b8bc61a002f2b12f",
    "xcl2.cpp": "da8ca3fe01035c49bd25d9075a11ef6d31ff306d44355581ebdd70605f536365",
}
PATCH = Path(__file__).resolve().parents[5] / "patches/spine_cc_resident_wall.patch"
XRT = Path("/opt/xilinx/xrt")
XILINX = Path("/data/yxx/tools/xilinx")


def build(archive, output):
    group = check_memory()
    if int((group / "memory.max").read_text()) > 2 * 2**30:
        raise MemoryError("CC host build requires a cgroup with MemoryMax at most 2 GiB")
    archive, output = archive.resolve(strict=True), output.resolve()
    for name, expected in INPUT_TUS.items():
        if identity(archive / HOST_DIR / name)["sha256"] != expected:
            raise ValueError(f"unexpected frozen CC source: {name}")
    output.mkdir(parents=True, exist_ok=False)
    staged = output / "source"
    directories = (Path("src"), HOST_DIR)
    for path in directories:
        shutil.copytree(archive / path, staged / path)
    inputs = {}
    for path in directories:
        for file in sorted((staged / path).rglob("*")):
            if file.is_file():
                relative = file.relative_to(staged)
                original = identity(archive / relative)
                if identity(file)["sha256"] != original["sha256"]:
                    raise ValueError(f"archived input changed while staging: {relative}")
                inputs[str(relative)] = original
    patch = output / PATCH.name
    shutil.copyfile(PATCH, patch)
    subprocess.run(["git", "apply", str(patch)], cwd=staged, check=True, timeout=10)
    binary = output / "host_cc_repair_resident"
    command = [
        "/usr/bin/g++", "-std=c++17", "-O2", "-Wall", "-g0", "-I.", "-Istubs", "-I../../src",
        f"-I{XILINX}/Vitis/2024.1/include", "-DMAX_N=16777216", "-DVS_PARTITION_SIZE=1048576",
        "-DMAX_SORT_N=131072", "-DEDGE_BUF_CHUNK_SIZE=33554432", "-DSPINE_ALGORITHM_KIND=1",
        "-DSPINE_ENABLE_SSSP_REPAIR=0", "-DSPINE_ENABLE_CC_REPAIR=1",
        "-DSPINE_ENFORCE_PAPER_ALIGNMENT_CONTRACT=1", "-DCL_DEVICE_HALF_FP_CONFIG=0x1033",
        f'-DSPINE_WEIGHTED_BUILD_SHA256="{ABI}"', f"-I{XRT}/include",
        f"-I{XILINX}/Vitis_HLS/2024.1/include", HOST, "xcl2.cpp", "-o", str(binary),
        f"-L{XRT}/lib", f"-Wl,-rpath,{XRT}/lib", "-lxilinxopencl", "-lxrt_coreutil",
        "-lrt", "-pthread", "-lcrypto",
    ]
    manifest = {"status": "BUILDING", "image_abi": ABI, "inputs": inputs,
                "overlay": identity(patch), "host_source": identity(staged / HOST_DIR / HOST),
                "compiler": identity(command[0]), "opencl": identity(XRT / "lib/libxilinxopencl.so"),
                "cwd": str(staged / HOST_DIR), "argv": command}
    save(output / "manifest.json", manifest)
    try:
        with (output / "build.log").open("x") as log:
            subprocess.run(command, cwd=staged / HOST_DIR, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        manifest.update(status="BUILT_NOT_BOARD_TESTED", binary=identity(binary))
    except BaseException as error:
        manifest.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        manifest.update(memory_peak_bytes=int((group / "memory.peak").read_text()),
                        memory_events=(group / "memory.events").read_text())
        save(output / "manifest.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.archive, args.output)
