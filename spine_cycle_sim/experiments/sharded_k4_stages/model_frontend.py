"""Bounded routed Scatter/source gates; no FPGA timing or whole-K4 claim."""

from pathlib import Path
import csv
import json
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .execution import identity


REPORTS = {
    "source": "PASS: 16 pairwise source/shared-writeback cases; completion and bounds PASS",
    "scatter": "PASS: 80 connected adapter/Scatter/source cases; dummy, empty-input and depth-one deadlock gates PASS",
    "hls": "PASS: 9 routed SSSP HLS dedicated source payload/count cases",
    "hls_worktree": "PASS: 9 worktree HLS pairwise source payload/count cases",
}


def require_report(name: str, text: str) -> None:
    lines = text.strip().splitlines()
    if name.startswith("hls"):
        lines = [line for line in lines if not re.fullmatch(
            r"INFO \[HLS SIM\]: The maximum depth reached by any hls::stream\(\) instance in the design is \d+", line)]
    if lines != [REPORTS[name]]:
        raise ValueError(f"frontend gate {name} did not execute its complete declared matrix")


def routed_source(xo: Path, route_manifest: Path, inputs: Path, headers: list[Path],
                  regraph: Path, output: Path) -> tuple[Path, dict]:
    route = json.loads(route_manifest.read_text())
    matches = [pin for pin in route["pins"] if Path(pin["path"]).resolve() == xo.resolve()]
    if len(matches) != 1 or identity(xo)["sha256"] != matches[0]["sha256"]:
        raise ValueError("source XO is not pinned by the measured adapter-replacement route")
    with inputs.open() as stream:
        compiled = list(csv.DictReader(stream, delimiter="\t"))
    for header in headers:
        matches = [row for row in compiled if row["path"].endswith("/" + str(header.relative_to(regraph)))]
        if len(matches) != 1 or identity(header)["sha256"] != matches[0]["sha256"]:
            raise ValueError("current ReGraph header differs from the routed compile input")
    with zipfile.ZipFile(xo) as archive:
        xml = ET.fromstring(archive.read("kernelHBMWrapper/kernel.xml"))
        masters = sorted(port.attrib["name"] for port in xml.iter("port") if port.attrib.get("mode") == "master")
        if masters != [f"M_AXI_GMEM{i}" for i in range(1, 5)]:
            raise ValueError("this gate targets the measured four-master SSSP XO")
        member = "kernelHBMWrapper/cpu_sources/kernel_hbm_wrapper.cpp"
        extracted = Path(archive.extract(member, output / "routed_source"))
    matches = [row for row in compiled if row["path"].endswith("/kernels/regraph_k4_shared_hbm_wrapper/kernel_hbm_wrapper.cpp")]
    if len(matches) != 1 or identity(extracted)["sha256"] != matches[0]["sha256"]:
        raise ValueError("XO embedded source differs from recorded compile input")
    return extracted, {"xo": identity(xo), "route_manifest": identity(route_manifest),
                       "compile_inputs": identity(inputs), "embedded_source": identity(extracted),
                       "masters": masters, "source_services": "four_independent_readers",
                       "header_hashes_match_routed_compile": True}


def validate_frontend(*, root: Path, integration: Path, regraph: Path, vitis: Path,
                      core_build: Path, output: Path, routed_hbm_xo: Path,
                      route_manifest: Path, compile_inputs: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    wrapper = integration / "kernels/regraph_k4_shared_hbm_wrapper/kernel_hbm_wrapper.cpp"
    probe = root / "cpp/tests/routed_regraph/source_service_hls_test.cpp"
    common = regraph / "acc_template/common"
    headers = [common / "acc_config.h", common / "acc_data_types.h", common / "l1_api.h",
               regraph / "acc_template/kernel_hbm_wrapper/hbm_wrapper.h"]
    routed_wrapper, artifact = routed_source(routed_hbm_xo, route_manifest, compile_inputs, headers, regraph, output)
    binaries = {"source": core_build / "cpp/routed_source_service_tests",
                "scatter": core_build / "cpp/routed_scatter_tests"}
    sources = [wrapper, routed_wrapper, routed_hbm_xo, route_manifest, compile_inputs, probe, *headers, Path(__file__),
               root / "scripts/validate_sharded_k4_frontend_model.py", vitis / "ap_int.h",
               vitis / "hls_stream.h", core_build / "cpp/libspine_cycle_core.a", *binaries.values()]
    sources += list((root / "cpp/src/routed_regraph").glob("*.cpp"))
    sources += list((root / "cpp/src/detail").glob("routed_regraph_*.hpp"))
    sources += [root / "cpp/tests/routed_regraph" / name for name in
                ("source_service_tests.cpp", "scatter_tests.cpp", "adapter_fixture.hpp")]
    pins = [identity(path) for path in sources]
    atomic_write_json(output / "manifest.json", {
        "schema_version": 1, "sources_and_executables": pins,
        "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
        "claim": "frontend_functional_and_finite_queue_gates_not_fpga_timing",
        "scope": "raw adapter to Scatter/source service; not whole lksg, four-worker dispatch or Apply",
        "expected_reports": REPORTS,
        "hardware_artifact": artifact,
        "worktree_variant": "two_pairwise_services_not_the_measured_SSSP_XO",
    })
    attempts = []

    def run(command: list[str], name: str) -> None:
        result = run_bounded(command, root, output / name, timeout=300, memory_gib=8, reserve_gib=16)
        attempts.append({"name": name, "resources": result})
        atomic_write_json(output / "attempts.json", attempts)
        if result["exit_code"]:
            raise RuntimeError(f"frontend gate {name} failed; logs retained at {output}")

    for name, binary in binaries.items():
        run([str(binary)], name)
    flags = ["HAVE_EDGE_PROP=1", "HAVE_UNSIGNED_PROP=1", "HAVE_APPLY_OUTDEG=0", "HAVE_VERTEX_PROP=1",
             "PARTITION_SIZE=65536", "LITTLE_KERNEL_DST_BUFFER_SIZE=65536", "BIG_KERNEL_DST_BUFFER_SIZE=524288",
             "SRC_BUFFER_SIZE=4096", "LOG2_SRC_BUFFER_SIZE=12", "VERTEX_REORDER_ENABLE=1",
             "ENABLE_COMPRESSED_EDGE_INPUT=0", "BIG_KERNEL_NUM=0", "LITTLE_KERNEL_NUM=4", "REGRAPH_PURE_LITTLE_ONLY"]
    hls_binaries = []
    for name, hls_source, pairwise in (("hls", routed_wrapper, 0), ("hls_worktree", wrapper, 1)):
        binary = output / (name + "_probe")
        command = ["g++", "-std=c++20", "-O2", "-Wno-unknown-pragmas", "-isystem", str(vitis),
                   "-isystem", str(vitis / "etc"), "-I", str(common), "-I", str(regraph / "acc_template/kernel_hbm_wrapper"),
                   *["-D" + flag for flag in flags], f'-DGRASU_HBM_WRAPPER_SOURCE="{hls_source}"',
                   f"-DGRASU_SOURCE_PAIRWISE={pairwise}", str(probe), "-lgmp", "-o", str(binary)]
        run(command, name + "_build")
        run([str(binary)], name)
        hls_binaries.append(identity(binary))
    for name in REPORTS:
        require_report(name, (output / f"{name}.stdout.txt").read_text())
    if [identity(Path(pin["path"])) for pin in pins] != pins:
        raise RuntimeError("frontend source or executable changed during validation")
    result = {"schema_version": 1, "status": "PASS", "reports": REPORTS,
              "source_unchanged": True, "hls_executables": hls_binaries, "attempts": attempts,
              "hardware_artifact": artifact,
              "claim": "frontend_functional_and_finite_queue_gates_not_fpga_timing"}
    atomic_write_json(output / "summary.json", result)
    return result
