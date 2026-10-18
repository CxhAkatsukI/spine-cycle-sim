"""Admit only complete, generated hardware compile lists, never shell execution."""

from pathlib import Path
import shlex

from .inputs import ALGORITHMS

BANK_FLAGS = {"ROW_PREFETCH=1", "STOP_AFTER_LAST=1", "SKIP_EMPTY_SEGMENT=1",
              "ROW_LINE_READ=1", "CROSS_ROW_PIPELINE=1", "DIRECTORY_TILE_ROWS=1024",
              "PACKET_PIPELINE=1", "BANK_STREAM=1", "BANK_FIFO_LINES=256",
              "SHARDED_PMA=1", "SHARE_ALL_MEMORY_PORTS=1", "DESTINATION_ONLY=1"}
PURE = {"bin_search", "dispatch", "process_cache", "process_ddr", "kernelApply",
        "kernelHBMWrapper", "kernelLittleGSMerger", "pma_completion_barrier",
        "pma_to_regraph_adapter", "regraph_frontend_mux", "lksg_stream"}
PR = {"bin_search", "dispatch_degree", "process_cache", "process_ddr", "grasu_degree_update",
      "pma_to_regraph_adapter", "lksg_stream", "kernelLittleGSMerger", "regraph_pagerank_apply",
      "regraph_pagerank_source_prepare", "kernelHBMWrapper", "regraph_frontend_mux"}


def value(argv, name):
    if argv.count(name) != 1 or argv.index(name) + 1 == len(argv):
        raise ValueError("exactly one value required: " + name)
    return argv[argv.index(name) + 1]


def compile_list(packet, algorithm, tool, source_root):
    if algorithm not in ALGORITHMS:
        raise ValueError("unsupported algorithm")
    commands = []
    seen = set()
    for line in (packet / "compile_commands.sh").read_text().splitlines():
        if not line.startswith("v++ "):
            continue
        argv = shlex.split(line)
        if value(argv, "--target") != "hw" or "--compile" not in argv or "--link" in argv \
                or value(argv, "--kernel_frequency") != "150":
            raise ValueError("hardware compile at 150 MHz required")
        config, binary = Path(value(argv, "--config")), Path(value(argv, "-o"))
        if config.parent != packet / "config" or binary.parent != packet / "build" or binary.suffix != ".xo":
            raise ValueError("compile config/output escaped packet")
        fields = dict(line.split("=", 1) for line in config.read_text().splitlines()
                      if "=" in line and not line.startswith("#"))
        kernel = fields["kernel"]
        if kernel in seen:
            raise ValueError("duplicate compile kernel")
        seen.add(kernel)
        source = Path(argv[-1])
        if source.suffix != ".cpp" or not source.resolve().is_relative_to(source_root.resolve()):
            raise ValueError("compile source escaped frozen closure")
        if kernel == "pma_to_regraph_adapter":
            required = {"-DGRASU_REGRAPH_" + flag for flag in BANK_FLAGS}
            definitions = [arg for arg in argv if arg.startswith("-D")]
            if not required.issubset(argv) or any(
                    arg.startswith("-DGRASU_REGRAPH_WEIGHTED_PMA") for arg in definitions) or any(
                    sum(arg.split("=", 1)[0] == flag.split("=", 1)[0] for arg in definitions) != 1
                    for flag in required):
                raise ValueError("destination-only bank-stream flags missing or conflicting")
        if kernel == "bin_search" and source.parts[-2:] != ("search_binding", "top.cpp"):
            raise ValueError("production search source required")
        if kernel == "process_cache":
            if source.parts[-2:] != ("grasu_complete", "process_cache.cpp") or \
                    "-DCACHE_BANK_REGISTERED" not in argv or \
                    "-DGRASU_PURE_PIPELINE_DIRECT_CACHE" in argv:
                raise ValueError("complete registered cache required")
        if kernel in ("process_cache", "process_ddr"):
            token = "-DGRASU_ENABLE_COMPLETION_TOKEN" in argv
            if token != (algorithm == "connected_components"):
                raise ValueError("algorithm-specific completion token ABI changed")
        if kernel in ("regraph_pagerank_apply", "regraph_pagerank_source_prepare"):
            mode = "1" if algorithm == "full_pagerank" else "2"
            if "-DGRASU_REGRAPH_PAGERANK_MODE=" + mode not in argv:
                raise ValueError("PageRank algorithm mode changed")
        argv[0] = str(tool)
        commands.append({"kernel": kernel, "argv": argv, "source": str(source), "xo": str(binary)})
    if seen != (PURE if algorithm == "connected_components" else PR):
        raise ValueError("incomplete or unexpected algorithm kernel set")
    return commands
