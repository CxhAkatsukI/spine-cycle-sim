"""Bounded Release/XRT and UBSan replay; never selects or programs an FPGA."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.execution import inputs, PREFLIGHT_SHA256
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.runtime import library_paths
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from . import analysis, preparation


def run(root, integration, original_preflight, xrt, output, *, original_preflight_sha256=PREFLIGHT_SHA256):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING_MATCHED_G_HOST", "errors": [], "steps": [], "cases": [], "binaries": [],
              "evidence_class": "host_compile_and_same_input_oracle_only", **dict.fromkeys(analysis.CLAIMS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        compiler = shutil.which("g++")
        if compiler is None or not (xrt / "include/CL/cl_ext_xilinx.h").is_file():
            raise ValueError("real XRT headers and G++ required")
        _, cases, pins = inputs(original_preflight, expected_sha256=original_preflight_sha256)
        report["original_preflight"] = identity(original_preflight / "results.json")
        report["compiler_version"] = subprocess.check_output([compiler, "--version"], text=True)
        pins += preparation.freeze(root, integration, output / "source")
        pins += [identity(Path(compiler).resolve())]
        pins += [identity(Path(module.__file__)) for name, module in sorted(sys.modules.items())
                 if name.startswith("spine_cycle_sim.") and getattr(module, "__file__", None)]
        report["pins"] = pins
        environment = dict(os.environ)
        for name in ("XRT_INI_PATH", "XCL_EMULATION_MODE", "LD_PRELOAD", "LD_LIBRARY_PATH",
                     "CONTINUOUS_G_EXPECT_BDF", "MATCHED_G_LEASE_FD"):
            environment.pop(name, None)

        def execute(name, command, *, expected=0):
            print("Matched G host preflight: " + name + " (not board timing)", flush=True)
            child = run_link(command, root, output / name, timeout=600, tree_memory_gib=4,
                             reserve_gib=32, poll_seconds=0.2, environment=environment)
            report["steps"].append({"id": name, **child})
            save()
            if child["exit_code"] != expected or child["stop_reason"] != "process_exit" or child["cleanup_snapshot_error"]:
                raise ValueError("matched-G host preflight failed: " + name)
            return output / (name + ".stdout.txt"), output / (name + ".stderr.txt")

        for variant in ("release", "ubsan"):
            directory = output / variant
            directory.mkdir()
            binary = directory / "probe"
            execute("compile_" + variant, preparation.command(output / "source", xrt, compiler, binary,
                                                              sanitizer=variant == "ubsan"))
            dependencies = dependency_identities(binary.with_suffix(".d"), root)
            pins += [identity(binary), *dependencies]
            report["binaries"].append({"variant": variant, **identity(binary), "dependencies": dependencies})
            if variant == "release":
                loader = shutil.which("ldd")
                if loader is None:
                    raise ValueError("ldd required to freeze real Xilinx runtime dependencies")
                stdout, stderr = execute("inspect_release_loader", [loader, str(binary)])
                if stderr.read_bytes():
                    raise ValueError("matched-G runtime loader diagnostic")
                libraries = library_paths(stdout.read_text())
                libraries += [(xrt / "lib/libxrt_core.so.2").resolve(strict=True), Path(loader).resolve(strict=True)]
                report["runtime_libraries"] = [identity(path) for path in sorted(set(libraries))]
                pins += report["runtime_libraries"]
            for row in cases:
                stdout, stderr = execute(variant + "_" + row["id"],
                    [str(binary), "--self-test", row["packet"]["path"]])
                report["cases"].append({"variant": variant, "id": row["id"],
                    **analysis.inspect(stdout.read_text(), stderr.read_text(), row)})
        negative = output / "bad-input.ogb"
        negative.write_bytes(b"OGB1" + bytes(16))
        for variant in ("release", "ubsan"):
            stdout, stderr = execute("reject_bad_header_" + variant,
                [str(output / variant / "probe"), "--self-test", str(negative)], expected=1)
            if stdout.read_bytes() or stderr.read_text() != "original G packet header\n":
                raise ValueError("matched-G failed to reject packet header")
        stdout, stderr = execute("reject_unleased_board", [str(output / "release/probe"), "--board",
            cases[0]["packet"]["path"], str(output / "absent.xclbin"), "0"], expected=1)
        if stdout.read_bytes() or stderr.read_text() != "external matched G board lease required\n":
            raise ValueError("matched-G failed to reject board access before XRT enumeration")
        unchanged(pins)
        report["status"] = analysis.STATUS
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save()
    return report
