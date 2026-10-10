"""Compile explicit adapter ablations without linking or replacing a bitstream."""

from pathlib import Path
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .execution import identity


VARIANTS = {"original": (0, 0), "prefetch": (1, 0), "stop_after_last": (0, 1),
            "combined": (1, 1)}


def read_report(root: Path) -> dict:
    reports = list(root.glob("build/**/syn/report/pma_to_regraph_adapter_csynth.xml"))
    if len(reports) != 1:
        raise ValueError("exactly one primary HLS report required")
    report = reports[0]
    tree = ET.parse(report).getroot()
    resources = tree.find("AreaEstimates/Resources")
    def structured(element):
        if not len(element):
            return (element.text or "").strip()
        return {child.tag: structured(child) for child in element}

    loops = [{"name": loop.tag, **structured(loop)}
             for loop in tree.findall(".//SummaryOfLoopLatency/*")]
    bursts = list(root.glob("build/**/.autopilot/db/burst.xml"))
    if len(bursts) != 1:
        raise ValueError("exactly one burst-inference report required")
    # Vitis writes an undeclared namespace prefix; bind it in a wrapper.
    burst_tree = ET.fromstring('<wrapper xmlns:VitisHLS="urn:vitis-hls">' +
                               bursts[0].read_text() + '</wrapper>')
    return {"resources": {element.tag: int(element.text) for element in resources},
            "loops": loops,
            "estimated_clock_ns": float(tree.findtext("PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod")),
            "row_burst_findings": [dict(element.attrib) for element in burst_tree.iter("burst")
                                   if element.get("VarName") == "row_offset"],
            "report": identity(report), "burst_report": identity(bursts[0])}


def synthesize(integration: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    source = integration / "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp"
    files = [identity(source), identity(source.parent / "row_prefetch.hpp")]
    common = ["/data/yxx/tools/xilinx/Vitis/2024.1/bin/v++", "--target", "hw",
              "--compile", "--kernel_frequency", "150", "--kernel", "pma_to_regraph_adapter",
              "--platform", "/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm",
              "--save-temps", "-D_GTHREAD_USE_COND_INIT_FUNC", "-DGRASU_REGRAPH_WEIGHTED_PMA=1",
              "-DGRASU_REGRAPH_SHARDED_PMA=1", "-DGRASU_REGRAPH_SHARE_ALL_MEMORY_PORTS=1",
              "-I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc"]
    manifest = {"source": files, "variants": VARIANTS, "base_command": common,
                "claim": "SSSP_adapter_HLS_scheduling_ablation_not_routed_FPGA_performance"}
    atomic_write_json(output / "manifest.json", manifest)
    runs = {}
    for name, (prefetch, stop) in VARIANTS.items():
        directory = output / name
        directory.mkdir()
        command = common + [f"-DGRASU_REGRAPH_ROW_PREFETCH={prefetch}",
                            f"-DGRASU_REGRAPH_STOP_AFTER_LAST={stop}",
                            "--temp_dir", str(directory / "build"),
                            "--report_dir", str(directory / "reports"),
                            "--log_dir", str(directory / "logs"),
                            "-o", str(directory / "adapter.hw.xo"), str(source)]
        resources = run_bounded(command, directory, directory / "compile", timeout=900,
                                memory_gib=8, reserve_gib=16)
        runs[name] = {"execution": resources}
        atomic_write_json(output / "attempts.json", runs)
        if resources["exit_code"] != 0:
            raise RuntimeError(f"HLS candidate failed: {name}; raw evidence retained")
        runs[name].update({"analysis": read_report(directory),
                           "xo": identity(directory / "adapter.hw.xo")})
        atomic_write_json(output / "attempts.json", runs)
        print(f"{name} HLS PASS", flush=True)
    if any(identity(Path(row["path"])) != row for row in files):
        raise RuntimeError("HLS source changed during the study")
    result = {"status": "HLS_PASS_NOT_ROUTED", "source": files, "runs": runs,
              "claim": manifest["claim"]}
    atomic_write_json(output / "summary.json", result)
    return result
