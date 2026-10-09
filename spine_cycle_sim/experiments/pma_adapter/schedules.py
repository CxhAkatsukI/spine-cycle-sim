"""Inspect lowered HLS accesses, not only optimistic front-end burst remarks."""

from pathlib import Path
import re
import shutil
from xml.sax import parseString
from xml.sax.handler import ContentHandler

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


class BurstRemarks(ContentHandler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def startElement(self, name, attrs):
        if name == "burst":
            self.rows.append({key: attrs.get(key) for key in ("group", "VarName", "LoopName", "msg_body")})


def inspect(packet: Path, output: Path):
    solution = packet / "build/pma_to_regraph_adapter/pma_to_regraph_adapter/pma_to_regraph_adapter/pma_to_regraph_adapter/solution"
    db = solution / ".autopilot/db"
    files = {"manifest.env": packet / "manifest.env", "burst.xml": db / "burst.xml",
        "top.verbose.rpt": db / "pma_to_regraph_adapter.verbose.rpt",
        "segment.verbose.rpt": db / "pma_to_regraph_adapter_Pipeline_segment_loop.verbose.rpt",
        "top.v": solution / "syn/verilog/pma_to_regraph_adapter.v"}
    manifest = dict(line.split("=", 1) for line in files["manifest.env"].read_text().splitlines() if "=" in line)
    if manifest["GRI_GIT_HEAD"] != "d886f42a730c5b75666fc51d8c1c246023b0f5cb" or manifest["ADAPTER_MODE_DEFINE"] != "-DGRASU_REGRAPH_DESTINATION_ONLY=1":
        raise ValueError("adapter HLS packet source/mode differs")
    remarks = BurstRemarks()
    # SAX without namespace processing accepts Vitis' undeclared root prefix.
    parseString(files["burst.xml"].read_bytes(), remarks)
    requests = {}
    for name in ("top.verbose.rpt", "segment.verbose.rpt"):
        rows = []
        for line in files[name].read_text().splitlines():
            match = re.match(r'^ST_(\d+) : .*?\[71/71\].*?"%(\S+) = readreq i1 @_ssdm_op_ReadReq\.m_axi\.i512P1A, .*?, i64 1"', line)
            if match:
                rows.append({"state": int(match[1]), "operation": match[2], "width_bits": 512, "beats": 1})
        requests[name] = rows
    top = files["top.v"].read_text()
    if (len(requests["top.verbose.rpt"]) != 2 or len(requests["segment.verbose.rpt"]) != 4 or
            ".NUM_READ_OUTSTANDING( 16 )" not in top or "C_M_AXI_GMEM0_DATA_WIDTH = 512" not in top or
            "gmem0_ARLEN = 64'd1;" not in top):
        raise ValueError("adapter lowered access/master geometry differs")
    output.mkdir(parents=True, exist_ok=False)
    indexed = []
    for name, path in files.items():
        shutil.copyfile(path, output / name)
        indexed.append({"path": name, "sha256": sha256_file(output / name), "bytes": path.stat().st_size})
    return {"source_revision": manifest["GRI_GIT_HEAD"], "packet_target_mhz": int(manifest["KERNEL_FREQ"]),
        "remarks": remarks.rows, "lowered_read_requests": requests, "files": indexed,
        "row_logical_bytes_per_access": 8, "row_bus_bytes_per_access": 64,
        "row_line_cache_present": False, "RTL_or_FPGA_timing_calibrated": False,
        "interpretation": "front-end sequential-burst remark does not survive as a multi-beat/cached row reader"}
