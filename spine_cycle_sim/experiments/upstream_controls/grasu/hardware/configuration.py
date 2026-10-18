"""Explicit same-platform port without compacting the author's memory interfaces."""

REVISION = "e95da256be9e7f2361449323b6fe0abf98c1b152"
SOURCE_DIRECTORY = "GraSU/GraSU_kernels/src"
SOURCE_HASHES = {
    "kernel_config.h": "a6176dafdce90d4916fb3bbf368b235fcd4efb4eb345cf542d15579052897959",
    "kernel_bin_search.cpp": "b078606b286e97b8b49617a73989ddc05d61eaa0eed860c39e428a7dc6e27572",
    "kernel_dispatch.cpp": "efc5bfe1c315940ac6023dcc06ad2d5d52b142fb3b96092897e52dc3faaec777",
    "kernel_process_cache.cpp": "34928ccfd2889af8874bbdb59700b379d7b89a6eebf04d0ffdd08d5f9bf1cb72",
    "kernel_process_ddr.cpp": "4fda96508724b55edc92b4c7984f4ad167e128cbafe0f360817fa2339b56e763",
}
KERNELS = {"bin_search": 4, "dispatch": 1, "process_cache": 2, "process_ddr": 2}
CLOCK_MHZ = 150
CLOCK_TOPOLOGY = sorted((("DATA", "DATA_CLK", CLOCK_MHZ),
                         ("KERNEL", "KERNEL_CLK", 500), ("SYSTEM", "hbm_aclk", 450)))
PART = "xcu55c-fsvh2892-2L-e"
POLICY = {"tree_memory_gib": 40, "reserve_gib": 32, "background_memory_gib": 8,
          "allow_bounded_builds": True}
FLAGS = ("board_programmed", "hardware_timing_measured", "production_g_admitted",
         "publication_performance_match", "final_figures_admitted")


def argument_names(kernel):
    if kernel == "bin_search":
        return ["edges", *[f"binary_{i}" for i in range(4)],
                *[f"row_offset_{i}" for i in range(4)], "edge_size", "segment_head_stream_out"]
    if kernel == "dispatch":
        return ["size", *[f"segment_head_stream_{i}" for i in range(1, 5)],
                *[f"dispatch_to_process_{kind}_{i}" for kind in ("cache", "ddr") for i in (1, 2)]]
    if kernel == "process_cache":
        return ["pma_cache", "update_stream"]
    if kernel == "process_ddr":
        return ["pma_in0_ddr", "pma_in1_ddr", "pma_out0_ddr", "pma_out1_ddr", "update_stream"]
    raise ValueError("unknown original G kernel")


def connectivity():
    lines = ["[connectivity]"]
    for name, count in KERNELS.items():
        lines.append(f"nk={name}:{count}:" + ".".join(f"{name}_{i}" for i in range(1, count + 1)))
    # Match the reviewed four-channel control mapping, without deleting a port.
    for index, slr in enumerate((0, 1, 2, 2), 1):
        for port in argument_names("bin_search")[:9]:
            lines.append(f"sp=bin_search_{index}.{port}:HBM[{index - 1}]")
        lines.append(f"slr=bin_search_{index}:SLR{slr}")
        lines.append(f"stream_connect=bin_search_{index}.segment_head_stream_out:dispatch_1.segment_head_stream_{index}")
    lines.append("slr=dispatch_1:SLR1")
    for index, bank, slr in ((1, 0, 0), (2, 2, 2)):
        lines += [f"sp=process_cache_{index}.pma_cache:HBM[{bank}]", f"slr=process_cache_{index}:SLR{slr}"]
    for index, bank, slr in ((1, 1, 1), (2, 3, 2)):
        lines += [f"sp=process_ddr_{index}.{port}:HBM[{bank}]" for port in argument_names("process_ddr")[:4]]
        lines.append(f"slr=process_ddr_{index}:SLR{slr}")
    for kind in ("cache", "ddr"):
        for index in (1, 2):
            lines.append(f"stream_connect=dispatch_1.dispatch_to_process_{kind}_{index}:process_{kind}_{index}.update_stream")
    return "\n".join(lines) + "\n"


def commands(compiler, platform, packet, output, *, legacy_include):
    base = [str(compiler), "--target", "hw", "--platform", str(platform), "--save-temps", "-O3",
            "--kernel_frequency", str(CLOCK_MHZ)]

    def directories(name):
        return [option for kind in ("temp", "report", "log")
                for option in ("--" + kind + "_dir", str(output / name / kind))]

    compilations = {name: [*base, "--compile", "--kernel", name,
        "-D_GTHREAD_USE_COND_INIT_FUNC", "-I" + str(packet / "source"), "-I" + str(legacy_include),
        *directories("compile/" + name), "-o", str(output / "xo" / (name + ".hw.xo")),
        str(packet / "source" / ("kernel_" + name + ".cpp"))] for name in KERNELS}
    link = [*base, "--link", "--config", str(packet / "link.cfg"),
            "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2", *directories("link"),
            "-o", str(output / "original_grasu.hw.xclbin"),
            *[str(output / "xo" / (name + ".hw.xo")) for name in KERNELS]]
    return compilations, link
