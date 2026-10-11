"""Audit finite compute-stream capacities from the two measured routed designs."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

ROUTED_BD_HASHES = {
    "original": "50ee61c6ec4c018d2c7d4d9f638cba8bfb1944d7e1eadd95dd5b78f3f17f6a46",
    "candidate": "e03a277dea556b31c3fa6282b1af78b2fe7704f6919cc994bfc5ce62e6f7a344",
}


def compute_streams() -> list[tuple[str, str, int]]:
    """Each entry is a producer port, consumer port and finite AXIS beat depth."""
    result = []
    for worker in range(1, 5):
        result.extend([
            (f"pma_to_regraph_adapter_{worker}/edge_burst_out", f"lksg_stream_{worker}/edge_burst_in", 32),
            (f"lksg_stream_{worker}/l_tmp_prop_stm", f"regraph_frontend_mux_1/input{worker - 1}", 32),
            (f"lksg_stream_{worker}/l_ppb_request_stm", f"kernelHBMWrapper_1/l_ppb_request_stm_{worker}", 16),
            (f"kernelHBMWrapper_1/l_ppb_response_stm_{worker}", f"lksg_stream_{worker}/l_ppb_response_stm", 16),
        ])
    result.extend([
        ("regraph_frontend_mux_1/output_r", "kernelLittleGSMerger_1/l_tmp_prop_stm_1", 32),
        ("kernelLittleGSMerger_1/l_write_burst_stm", "kernelApply_1/l_merged_prop_stm", 16),
        ("kernelApply_1/prop_write_burst_stm", "kernelHBMWrapper_1/prop_write_burst_stm", 16),
    ])
    return result


def validate_design(document: dict) -> list[dict]:
    design = document["design"]
    nets = [set(net["interface_ports"]) for net in design["interface_nets"].values()]
    rows = []
    for producer, consumer, depth in compute_streams():
        name = "buffer_" + producer.replace("/", "_")
        cell = design["components"].get(name, {})
        if (cell.get("vlnv") != "xilinx.com:ip:axis_data_fifo:2.0"
                or cell.get("parameters", {}).get("FIFO_DEPTH", {}).get("value") != str(depth)
                or nets.count({producer, f"{name}/S_AXIS"}) != 1
                or nets.count({f"{name}/M_AXIS", consumer}) != 1):
            raise ValueError(f"routed compute stream depth or wiring differs: {name}")
        rows.append({"cell": name, "producer": producer, "consumer": consumer, "depth": depth})
    return rows


def audit_design(path: Path, arm: str) -> dict:
    digest = sha256_file(path)
    if arm not in ROUTED_BD_HASHES or digest != ROUTED_BD_HASHES[arm]:
        raise ValueError("not the measured original/candidate routed block design")
    return {"path": str(path.resolve()), "sha256": digest, "arm": arm,
            "streams": validate_design(json.loads(path.read_text()))}
