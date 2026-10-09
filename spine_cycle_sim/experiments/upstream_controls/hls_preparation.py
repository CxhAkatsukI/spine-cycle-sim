"""Prepare unmodified author kernels and explicit synthesis configurations."""

from __future__ import annotations

from pathlib import Path
import re
import shutil

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from .sources import prepare_regraph


G_KERNELS = {
    "cache": ("process_cache", "kernel_process_cache.cpp"),
    "ddr": ("process_ddr", "kernel_process_ddr.cpp"),
    "search": ("bin_search", "kernel_bin_search.cpp"),
    "dispatch": ("dispatch", "kernel_dispatch.cpp"),
}
R_KERNELS = {
    "little": ("littleKernelScatterGather", "kernel_little_gs/kernel_scatter_gather.cpp"),
    "big": ("bigKernelScatterGather", "kernel_big_gs/kernel_scatter_gather.cpp"),
    "little_merger": ("kernelLittleGSMerger", "kernel_little_gs_merger/kernel_little_gs_merger.cpp"),
    "big_merger": ("kernelBigGSMerger", "kernel_big_gs_merger/kernel_big_gs_merger.cpp"),
    "apply": ("kernelApply", "kernel_apply/kernel_apply.cpp"),
    "memory_wrapper": ("kernelHBMWrapper", "kernel_hbm_wrapper/kernel_hbm_wrapper.cpp"),
}


def validate_synthesis_contract(contract: dict) -> None:
    if (contract.get("schema_version") != 1
            or contract.get("evidence_class") != "upstream_hls_schedule_not_board_timing"):
        raise ValueError("unsupported HLS schedule contract")
    for name in ("memory_limit_gib", "reserve_gib", "timeout_seconds"):
        if type(contract.get(name)) is not int or contract[name] <= 0:
            raise ValueError(f"{name} must be an explicit positive integer")
    if contract["reserve_gib"] < 16 or not contract.get("not_claimed"):
        raise ValueError("memory reserve and evidence limitations are required")
    for family in ("grasu", "regraph"):
        clock = contract.get(f"{family}_clock_ns")
        if type(clock) not in (int, float) or not 0 < clock < 100:
            raise ValueError("clock must be finite, positive and explicit")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", contract.get(f"{family}_part", "")):
            raise ValueError("unsafe or missing FPGA part")
    if not contract.get("jobs") or not contract.get("generator_python"):
        raise ValueError("empty job matrix or missing generator")
    ids = set()
    for job in contract["jobs"]:
        name = job.get("id", "")
        if not re.fullmatch(r"[a-z0-9_]+", name) or name in ids:
            raise ValueError("duplicate or unsafe job id")
        ids.add(name)
        family, kernel = job.get("family"), job.get("kernel")
        if family == "grasu" and kernel in G_KERNELS:
            if "little" in job or "big" in job:
                raise ValueError("GraSU does not have a ReGraph topology")
        elif family == "regraph" and kernel in R_KERNELS:
            little, big = job.get("little"), job.get("big")
            if (type(little) is not int or type(big) is not int or little < 1
                    or big < 0 or little + big > 14):
                raise ValueError("invalid original ReGraph topology")
            if kernel in ("big", "big_merger") and big == 0:
                raise ValueError("Big synthesis needs a Big pipeline")
        else:
            raise ValueError("unsupported author kernel")
        if "bind_arg_reg_control" in job and (
                type(job["bind_arg_reg_control"]) is not bool
                or family != "regraph" or kernel != "apply"):
            raise ValueError("control-bundle compatibility is only defined for PR apply")


def _tcl_string(value: str) -> str:
    # Braced Tcl arguments preserve spaces; reject structural delimiters.
    if any(char in value for char in "{}\\\n\r"):
        raise ValueError("unsupported character in Tcl argument")
    return "{" + value + "}"


def _include_flag(path: Path) -> str:
    # HLS 2024.1 retains embedded quote characters in -I directory tokens.
    if any(char.isspace() or char in "\"'{}\\" for char in str(path)):
        raise ValueError("HLS include paths must not contain whitespace or quotes")
    return f"-I{path}"


def prepare_hls_job(job: dict, contract: dict, source_root: Path, case: Path,
                    tool_include: Path | None = None,
                    portability_header: Path | None = None) -> dict:
    family = job["family"]
    source = case / "source"
    generation = None
    if family == "grasu":
        original = source_root / "grasu/GraSU/GraSU_kernels/src"
        shutil.copytree(original, source)
        top, relative = G_KERNELS[job["kernel"]]
        kernel = source / relative
        flags = _include_flag(source)
        tool_configuration = []
    else:
        generation = prepare_regraph(source_root / "regraph", source, job["little"],
                                      job["big"], contract["generator_python"])
        top, relative = R_KERNELS[job["kernel"]]
        kernel = source / "acc_template" / relative
        directories = ["acc_template/common", "acc_udfs/pr", str(kernel.parent.relative_to(source))]
        includes = " ".join(_include_flag(source / name) for name in directories)
        flags = (f"{includes} -DLITTLE_KERNEL_NUM={job['little']} -DBIG_KERNEL_NUM={job['big']} "
                 "-DLITTLE_KERNEL_DST_BUFFER_SIZE=65536 -DBIG_KERNEL_DST_BUFFER_SIZE=524288 "
                 "-DSRC_BUFFER_SIZE=4096 -DLOG2_SRC_BUFFER_SIZE=12 "
                 "-DHAVE_APPLY_OUTDEG=1 -DHAVE_VERTEX_PROP=0 -DHAVE_UNSIGNED_PROP=0")
        tool_configuration = [f"source {_tcl_string(str(source / 'acc_template/hls_config.tcl'))}"]
    if tool_include is not None:
        flags += " " + _include_flag(tool_include / "etc")
    compatibility = []
    if job.get("bind_arg_reg_control", False):
        tool_configuration.append(
            "set_directive_interface -mode s_axilite -bundle control kernelApply arg_reg")
        compatibility.append("bind_missing_arg_reg_control_bundle_for_Vitis_2024_1")
    if family == "regraph" and portability_header is not None:
        header = source / "hls_portability.hpp"
        shutil.copyfile(portability_header, header)
        _include_flag(header)
        flags += f" -include {header}"
        compatibility.append("force_include_global_32bit_uint_alias_only")
    script = case / "synthesis.tcl"
    lines = [
        "open_project project", f"set_top {top}",
        f"add_files {_tcl_string(str(kernel))} -cflags {_tcl_string(flags)}",
        "open_solution -flow_target vitis solution",
        f"set_part {_tcl_string(contract[f'{family}_part'])}",
        f"create_clock -period {contract[f'{family}_clock_ns']} -name default",
        *tool_configuration, "csynth_design", "exit",
    ]
    script.write_text("\n".join(lines) + "\n", encoding="ascii")
    identities = [{"path": str(path.relative_to(case)), "sha256": sha256_file(path)}
                  for path in sorted(source.rglob("*")) if path.is_file()]
    return {"top": top, "kernel": str(kernel), "flags": flags,
            "script": str(script), "script_sha256": sha256_file(script),
            "source_files": identities, "generation": generation,
            "compatibility": compatibility,
            "tool_configuration": tool_configuration,
            "solution": str(case / "project/solution")}
