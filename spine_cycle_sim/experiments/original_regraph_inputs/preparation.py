"""Prepare reviewed graph fixtures and a build over unmodified author functions."""

from __future__ import annotations

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


def write_fixture(name: str, path: Path) -> None:
    if name not in ("boundary_ring", "skewed_sources"):
        raise ValueError("undeclared original-R input fixture")
    with path.open("x", encoding="ascii") as stream:
        if name == "boundary_ring":
            for vertex in range(131073):
                stream.write(f"{vertex} {(vertex + 1) % 131073}\n")
            for vertex in range(64):
                stream.write(f"{vertex} {(vertex + 1) % 131073}\n")
        else:
            for edge in range(8192):
                stream.write(f"{edge % 4096} {(edge * 17) % 6144}\n")
            stream.write("65536 0\n")


def inspect_graph(path: Path) -> dict:
    if "ungraph" in str(path):
        raise ValueError("this matrix admits directed inputs only; original loader treats 'ungraph' specially")
    count, minimum, maximum = 0, 2**31, 0
    with path.open(encoding="ascii") as stream:
        for line in stream:
            fields = line.split()
            if len(fields) != 2:
                raise ValueError("original graph input requires exactly two integer columns, no headers or blank rows")
            source, destination = map(int, fields)
            if min(source, destination) < 0 or max(source, destination) >= 2**31 - 1:
                raise ValueError("original graph IDs exceed the supported signed-32-bit domain")
            minimum, maximum = min(minimum, source, destination), max(maximum, source, destination)
            count += 1
    if not count or maximum + 1 > 255 * 65536 or count > 2**31 - 1:
        raise ValueError("input exceeds the nonempty original wrapper/host count domain")
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "logical_edges": count,
            "vertices": maximum + 1, "minimum_id": minimum, "directed": True}


def compiler_command(root: Path, prepared: Path, topology: dict, output: Path,
                     compiler: str, xrt_include: Path) -> list[str]:
    command = [compiler, "-std=c++17", "-O1", "-g0", "-ffunction-sections", "-fdata-sections",
               "-MD", "-MF", str(output / "dependencies.d"), "-MT", "probe",
               f"-DLITTLE_KERNEL_NUM={topology['little']}", f"-DBIG_KERNEL_NUM={topology['big']}",
               "-DPARTITION_SIZE=65536", "-DLITTLE_KERNEL_DST_BUFFER_SIZE=65536",
               "-DBIG_KERNEL_DST_BUFFER_SIZE=524288", "-DSRC_BUFFER_SIZE=4096", "-DHAVE_UNSIGNED_PROP=0"]
    command.extend(f"-I{prepared / name}" for name in (
        "host/host_config", "host/graph_loader", "host/preprocess", "utils/common/includes/xcl2",
        "acc_udfs/pr", "acc_template/common"))
    command += [f"-I{xrt_include}", str(root / "cpp/tests/publication_sources/regraph_layout_probe.cpp"),
                "-Wl,--gc-sections", "-lOpenCL", "-o", str(output / "probe")]
    return command
