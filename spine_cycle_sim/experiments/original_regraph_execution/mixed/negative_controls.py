"""Reject original allocation overrun and corrupt descriptors/data without repair."""

from pathlib import Path
import shutil
import struct

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


def run(binary: Path, output: Path, inputs: list[dict], contract: dict, execute) -> list[dict]:
    result = []
    for item in inputs:
        if item["geometry"]["original_host_capacity_pass"]: continue
        directory = output / ("negative_capacity_" + item["id"]); directory.mkdir()
        step = execute("negative_capacity_" + item["id"], [str(binary), item["directory"], str(directory),
            "16", "64", "0", str(contract["max_cycles"]), "0"], contract["run_timeout_seconds"], True)
        diagnostic = "original host allocation is smaller than mixed publication extent"
        if step["exit_code"] != 1 or diagnostic not in Path(step["stderr"]).read_text(): raise ValueError("unsafe original mixed allocation not rejected")
        result.append({"id": "capacity_" + item["id"], "diagnostic": diagnostic, "expected_rejection": True})
    original = Path(inputs[0]["directory"])
    for name, filename, word, diagnostic in (
        ("header", "mixed.u32le", 0, "descriptor header"),
        ("assignment", "mixed.u32le", 14, "task assignment"),
        ("source", "tasks.u32le", 0, "source outside graph"),
        ("arithmetic", "initial.u32le", 0, "signed arithmetic domain"),
        ("edge_value", "tasks.u32le", 1, "pre-Apply sum"),
        ("truncated", "mixed.u32le", None, "descriptor geometry")):
        directory = output / ("negative_" + name); shutil.copytree(original, directory)
        path = directory / filename; data = bytearray(path.read_bytes())
        if name == "truncated": del data[-4:]
        elif name == "source": struct.pack_into("<I", data, word * 4, 0x7fffffff)
        elif name == "arithmetic": struct.pack_into("<I", data, word * 4, 0x7fffffff)
        elif name == "edge_value":
            old = struct.unpack_from("<I", data, word * 4)[0]; struct.pack_into("<I", data, word * 4, old ^ 1)
        else: data[word * 4] ^= 1
        path.write_bytes(data)
        state = directory / "state"; state.mkdir()
        step = execute("negative_" + name, [str(binary), str(directory), str(state), "16", "64", "0",
            str(contract["max_cycles"]), "1"], contract["run_timeout_seconds"], True)
        if step["exit_code"] != 1 or diagnostic not in Path(step["stderr"]).read_text():
            raise ValueError("corrupted mixed input not rejected by the declared gate: " + name)
        result.append({"id": name, "diagnostic": diagnostic, "expected_rejection": True, "path": str(path), "sha256": sha256_file(path)})
    return result
