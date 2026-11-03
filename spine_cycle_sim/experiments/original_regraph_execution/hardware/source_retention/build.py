"""Build both single-run R probes with one compiler and frozen source inputs."""

import argparse
from pathlib import Path
import subprocess

from .runtime import identity, save


def build(repository, integration, output, compiler):
    output.mkdir(parents=True, exist_ok=False)
    cpp = repository / "cpp/tests"
    directories = [cpp / name for name in ("original_regraph/hardware",
                   "original_regraph/whole_graph", "publication_sources/grasu_board",
                   "publication_sources/source_retention")]
    directories += [integration / "include", Path("/opt/xilinx/xrt/include/CL")]
    sources = [identity(path) for path in sorted({p for directory in directories
               for p in directory.rglob("*") if p.is_file() and p.suffix in (".h", ".hpp", ".cpp")})]
    library = Path("/opt/xilinx/xrt/lib/libxilinxopencl.so")
    flags = ["-std=c++20", "-O2", "-DNDEBUG", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
             "-I/opt/xilinx/xrt/include"]
    compiler = compiler.resolve()
    report = {"status": "BUILDING", "compiler": identity(compiler), "sources": sources,
              "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
              "library": identity(library), "builds": [], "board_tested": False}
    save(output / "manifest.json", report)
    try:
        for arm, source in (("reference", cpp / "original_regraph/hardware/control.cpp"),
                            ("candidate", cpp / "publication_sources/source_retention/main.cpp")):
            binary = output / ("r_" + arm)
            includes = [] if arm == "reference" else ["-I" + str(p) for p in (
                cpp / "original_regraph/hardware", cpp / "publication_sources/grasu_board", integration / "include")]
            command = [str(compiler), *flags, *includes, str(source), "-o", str(binary),
                       str(library), "-Wl,-rpath,/opt/xilinx/xrt/lib"]
            record = {"arm": arm, "command": command, "status": "COMPILING"}
            report["builds"].append(record)
            save(output / "manifest.json", report)
            with (output / (arm + ".stdout.txt")).open("x") as out, (output / (arm + ".stderr.txt")).open("x") as err:
                subprocess.run(command, stdout=out, stderr=err, timeout=180, check=True)
            record.update(status="COMPILED", binary=identity(binary))
            save(output / "manifest.json", report)
        if any(identity(Path(p["path"])) != p for p in sources + [report["compiler"], report["library"]]):
            raise ValueError("host build dependency changed")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report.update(status="HOST_BUILD_FAILED_RETAINED", error=repr(error))
        save(output / "manifest.json", report)
        raise
    report["status"] = "SINGLE_RUN_HOSTS_BUILD_PASS_NOT_BOARD"
    save(output / "manifest.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, default=Path("/usr/bin/x86_64-linux-gnu-g++-15"))
    args = parser.parse_args()
    print(build(args.repository.resolve(), args.integration.resolve(), args.output.resolve(), args.compiler)["status"])
