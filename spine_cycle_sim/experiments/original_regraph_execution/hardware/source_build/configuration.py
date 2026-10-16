"""Explicit 11-Little/3-Big PR control, not a graph-selected publication match."""

from pathlib import Path

COMPILER = Path("/data/yxx/tools/xilinx/Vitis/2024.1/bin/v++")
GENERATOR_PYTHON = Path("/usr/bin/python3.11")
PLATFORM = Path("/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/"
                "xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm")
CLOCK_MHZ = 150
PART = "xcu55c-fsvh2892-2L-e"
POLICY = {"tree_memory_gib": 40, "reserve_gib": 24, "background_memory_gib": 8,
          "allow_bounded_builds": True}
DEFINES = {"HAVE_EDGE_PROP": 0, "HAVE_UNSIGNED_PROP": 0, "HAVE_APPLY_OUTDEG": 1,
           "HAVE_VERTEX_PROP": 0, "PARTITION_SIZE": 65536,
           "LITTLE_KERNEL_DST_BUFFER_SIZE": 65536, "BIG_KERNEL_DST_BUFFER_SIZE": 524288,
           "SRC_BUFFER_SIZE": 4096, "LOG2_SRC_BUFFER_SIZE": 12, "VERTEX_REORDER_ENABLE": 1,
           "KERNEL_NUM": 14, "LITTLE_KERNEL_NUM": 11, "BIG_KERNEL_NUM": 3}
KERNELS = {
    "kernelApply": ("kernel_apply/kernel_apply.cpp", 1),
    "kernelHBMWrapper": ("kernel_hbm_wrapper/kernel_hbm_wrapper.cpp", 1),
    "littleKernelScatterGather": ("kernel_little_gs/kernel_scatter_gather.cpp", 11),
    "kernelLittleGSMerger": ("kernel_little_gs_merger/kernel_little_gs_merger.cpp", 1),
    "bigKernelScatterGather": ("kernel_big_gs/kernel_scatter_gather.cpp", 3),
    "kernelBigGSMerger": ("kernel_big_gs_merger/kernel_big_gs_merger.cpp", 1),
}


def directories(output: Path, name: str) -> list[str]:
    step = output / name
    return ["--temp_dir", str(step / "build"), "--report_dir", str(step / "reports"),
            "--log_dir", str(step / "logs")]


def compile_command(source: Path, output: Path, kernel: str) -> list[str]:
    relative, _ = KERNELS[kernel]
    includes = [source / name for name in ("acc_udfs/pr", ".", "acc_template",
                                          "acc_template/common", "acc_udfs")]
    includes += [source / "acc_template" / Path(relative).parent,
                 Path("/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc")]
    directives = (["--hls.pre_tcl", str(output / "entries/apply_interface.tcl")]
                  if kernel == "kernelApply" else [])
    return [str(COMPILER), "--target", "hw", "--platform", str(PLATFORM), "--save-temps", "-O3",
            "--kernel_frequency", str(CLOCK_MHZ), "--compile", "--kernel", kernel,
            "-D_GTHREAD_USE_COND_INIT_FUNC", *[f"-D{key}={value}" for key, value in DEFINES.items()],
            *["-I" + str(path) for path in includes], *directives, *directories(output, "compile/" + kernel),
            "-o", str(output / "xo" / (kernel + ".hw.xo")),
            str(output / "entries" / (kernel + ".cpp"))]


def link_command(source: Path, output: Path) -> list[str]:
    return [str(COMPILER), "--target", "hw", "--platform", str(PLATFORM), "--save-temps", "-O3",
            "--link", "--kernel_frequency", str(CLOCK_MHZ),
            "--config", str(source / "acc_template/connectivity.cfg"),
            "--xp", "prop:solution.kernel_compiler_margin=10%",
            "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2", *directories(output, "link"),
            "-o", str(output / "original_r_11l3b.hw.xclbin"),
            *[str(output / "xo" / (kernel + ".hw.xo")) for kernel in KERNELS]]


def argument_names(kernel: str) -> list[str]:
    if kernel not in KERNELS:
        raise ValueError("unknown author kernel")
    if kernel == "kernelApply":
        return ["outdegree", "num_dense_paritions", "num_sparse_paritions", "arg_reg",
                "l_merged_prop_stm", "b_merged_prop_stm", "prop_write_burst_stm"]
    if kernel == "kernelHBMWrapper":
        return [*[f"src_prop_{i}" for i in range(1, 15)], *[f"new_prop_{i}" for i in range(1, 15)],
                "num_dense_paritions", "num_sparse_paritions",
                *[f"l_ppb_request_stm_{i}" for i in range(1, 12)],
                *[f"l_ppb_response_stm_{i}" for i in range(1, 12)],
                *[f"b_cacheline_request_stm_{i}" for i in range(1, 4)],
                *[f"b_cacheline_response_stm_{i}" for i in range(1, 4)], "prop_write_burst_stm"]
    little = "Little" in kernel or kernel.startswith("little")
    prefix, count = ("l", 11) if little else ("b", 3)
    if "Merger" in kernel:
        return [*[f"{prefix}_tmp_prop_stm_{i}" for i in range(1, count + 1)],
                prefix + "_write_burst_stm"]
    request = "ppb" if little else "cacheline"
    return ["part_edge_array", "part_edge_num", "part_dst_offset",
            f"{prefix}_{request}_request_stm", f"{prefix}_{request}_response_stm",
            prefix + "_tmp_prop_stm"]


def control_protocol(kernel: str) -> str:
    if kernel not in KERNELS:
        raise ValueError("unknown author kernel")
    return "ap_ctrl_none" if "Merger" in kernel else "ap_ctrl_chain"
