"""Freeze a production-shaped RTL probe independently of earlier source runs."""

import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..search_pipeline.preparation import ROOT, SOURCE
from ..search_pipeline.synthesis import unchanged
from ..search_pipeline.analysis import analyze as analyze_isolated
from .analysis import analyze as analyze_binding


def prepare(output, binding, search, reference):
    binding_path, search_path = binding / "results.json", search / "results.json"
    controls, isolated = (json.loads(path.read_text()) for path in (binding_path, search_path))
    if controls.get("status") != "SEARCH_BINDING_SOURCE_PASS_NOT_RTL" or \
            isolated.get("status") != "FINITE_HLS_SOURCE_PASS_NOT_RTL_TIMING":
        raise ValueError("complete binding and isolated source controls required")
    unchanged(controls["source"] + controls["dependencies"])
    unchanged(isolated["source"] + isolated["dependencies"])
    analyze_binding(Path(controls["execute"]["stdout"]).read_text())
    unchanged([isolated["previous"]])
    analyze_isolated(isolated, json.loads(Path(isolated["previous"]["path"]).read_text()))
    for path in (binding / "source" / SOURCE / "hls/search_pipeline").glob("*"):
        if path.is_file() and path.suffix in (".hpp", ".cpp"):
            counterpart = search / "source" / SOURCE / "hls/search_pipeline" / path.name
            if sha256_file(path) != sha256_file(counterpart):
                raise ValueError("binding and isolated search use different source: " + path.name)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(binding / "source", output / "source")
    for pin in controls["source"]:
        frozen = output / "source" / Path(pin["path"]).relative_to(binding / "source")
        if sha256_file(frozen) != pin["sha256"]:
            raise ValueError("binding source changed while copying")
    bench = ROOT / SOURCE / "hls/search_binding/rtl_control.cpp"
    if sha256_file(bench) != sha256_file(output / "source" / SOURCE / "hls/search_binding/rtl_control.cpp"):
        raise ValueError("binding controls do not freeze the current RTL bench")
    runner = sorted(Path(__file__).parent.glob("*.py")) + [
        ROOT / "spine_cycle_sim/experiments/campaign_runtime.py",
        ROOT / "spine_cycle_sim/experiments/upstream_controls/execution.py",
        *(Path(__file__).parent.parent / "search_pipeline").glob("*.py")]
    pins = []
    for path in runner:
        frozen = output / "runner" / path.relative_to(ROOT)
        frozen.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, frozen)
        digest = sha256_file(frozen)
        if sha256_file(path) != digest:
            raise ValueError("RTL runner changed while copying")
        pins.append({"path": str(path), "frozen_path": str(frozen), "sha256": digest})
    reference_pins = []
    for name, path in (("kernel.xml", reference / "impl/kernel/kernel.xml"),
                       ("component.xml", reference / "impl/ip/component.xml")):
        frozen = output / "reference" / name
        frozen.parent.mkdir(exist_ok=True)
        shutil.copy2(path, frozen)
        digest = sha256_file(frozen)
        if sha256_file(path) != digest:
            raise ValueError("reference ABI changed while copying")
        reference_pins.append({"original_path": str(path), "path": str(frozen), "sha256": digest})
    sources = [{"path": str(path), "sha256": sha256_file(path)}
               for folder in (output / "source", output / "reference")
               for path in sorted(folder.rglob("*")) if path.is_file()]
    basis = [{"path": str(path), "sha256": sha256_file(path)} for path in (binding_path, search_path)]
    return {"source": sources, "runner_source": pins, "basis": basis, "reference_abi": reference_pins}


def tcl():
    flags = "-std=c++14 -pthread -D_GTHREAD_USE_COND_INIT_FUNC -I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc"
    source = "../source/cpp/tests/evaluation_impact/common_g/hls/search_binding"
    return f'''open_project -reset project
set_top bin_search
add_files {source}/top.cpp -cflags {{{flags}}}
add_files -tb {source}/rtl_control.cpp -cflags {{{flags}}}
open_solution -reset solution -flow_target vitis
set_part {{xcu55c-fsvh2892-2L-e}}
create_clock -period 5 -name default
config_rtl -deadlock_detection sim
csim_design -ldflags {{-pthread}}
csynth_design
cosim_design -rtl verilog -tool xsim -ldflags {{-pthread}}
export_design -format xo -output search_binding.xo
exit
'''
