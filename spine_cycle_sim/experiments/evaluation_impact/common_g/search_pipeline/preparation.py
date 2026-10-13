"""Freeze a separate 64-context HLS candidate, leaving the cycle engine unchanged."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..study import ROOT
from ..metadata_credits.preparation import CASES

SOURCE = Path("cpp/tests/evaluation_impact/common_g")
MODES = ("unblocked", "stalled")


def prepare(output: Path, basis: Path):
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    shutil.copytree(ROOT / SOURCE, source / SOURCE)
    for relative in ("cpp/tests/original_grasu", "cpp/include/spine_sim"):
        shutil.copytree(ROOT / relative, source / relative)
    (source / "cpp/src/original_grasu").mkdir(parents=True)
    shutil.copy2(ROOT / "cpp/src/original_grasu/types.cpp", source / "cpp/src/original_grasu/types.cpp")
    shutil.copytree(Path(__file__).parent, source / "runner",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for relative in ("spine_cycle_sim/experiments/campaign_runtime.py",
                     "spine_cycle_sim/experiments/upstream_controls/execution.py"):
        shutil.copy2(ROOT / relative, source / "runner" / Path(relative).name)
    for name, _, _ in CASES:
        shutil.copytree(basis / "inputs" / name, output / "inputs" / name)
    return [{"path": str(path), "sha256": sha256_file(path)}
            for folder in (source, output / "inputs")
            for path in sorted(folder.rglob("*")) if path.is_file()]


def command(source: Path, include: Path, compiler: str, binary: Path, *, rtl=False):
    kernel = source / SOURCE / "hls/search_pipeline"
    return [compiler, "-std=c++14" if rtl else "-std=c++20", "-O2", "-pthread", "-Wno-unknown-pragmas",
            "-MMD", "-MF", str(binary.with_suffix(".d")), "-MT", "probe",
            "-D_GTHREAD_USE_COND_INIT_FUNC", "-DSEARCH_PIPELINE_SOURCE_TOP",
            "-I" + str(include), "-I" + str(include / "etc"),
            "-I" + str(source / "cpp/include"),
            str(kernel / ("rtl_control.cpp" if rtl else "control.cpp")),
            *([] if rtl else [str(source / "cpp/src/original_grasu/types.cpp")]), "-o", str(binary)]


def tcl():
    flags = "-std=c++14 -pthread -D_GTHREAD_USE_COND_INIT_FUNC -I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc"
    source = "../source/cpp/tests/evaluation_impact/common_g/hls/search_pipeline"
    return f'''open_project -reset project
set_top bin_search_pipeline
add_files {source}/top.cpp -cflags {{{flags}}}
add_files -tb {source}/rtl_control.cpp -cflags {{{flags}}}
open_solution -reset solution -flow_target vitis
set_part {{xcu55c-fsvh2892-2L-e}}
create_clock -period 5 -name default
config_rtl -deadlock_detection sim
csim_design -ldflags {{-pthread}}
csynth_design
cosim_design -rtl verilog -tool xsim -ldflags {{-pthread}}
exit
'''
