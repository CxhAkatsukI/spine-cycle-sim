from copy import deepcopy

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    weighted_tail_link as link,
)
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity


@pytest.mark.parametrize("kernel,fault", [
    (link.GATHER, None), (link.GATHER, "register"), (link.GATHER, "stream_id"),
    (link.MERGER, None), (link.MERGER, "stream_width"), (link.MERGER, "clock_flag"),
])
def test_weighted_tail_interface_changes_only_gather_scalar(monkeypatch, kernel, fault):
    old = {"args": [{"id": str(i)} for i in range(8)],
           "ports": [{"name": "IN", "dataWidth": "64"}]}
    if kernel == link.GATHER:
        old["ports"].append({"name": "S_AXI_CONTROL", "range": "0x30"})
    new = deepcopy(old)
    if kernel == link.GATHER:
        new["ports"][1]["range"] = "0x38"
        for index in range(5, 8):
            new["args"][index]["id"] = str(index + 1)
        new["args"].insert(5, dict(link.PUBLICATION_ROWS))
    old_flags = {"HAVE_EDGE_PROP": "1", "HAVE_UNSIGNED_PROP": "1", "LITTLE_KERNEL_NUM": "1"}
    new_flags = {**old_flags, link.TAIL: "1"}
    if fault == "register":
        new["args"][5]["offset"] = "0x38"
    elif fault == "stream_id":
        new["args"][-1]["id"] = "7"
    elif fault == "stream_width":
        new["ports"][0]["dataWidth"] = "128"
    elif fault == "clock_flag":
        new_flags["EXTRA_FLAG"] = "1"
    interfaces = {"before": (old, old_flags), "after": (new, new_flags)}
    monkeypatch.setattr(link, "kernel_interface", lambda name, _: deepcopy(interfaces[name]))
    if fault:
        with pytest.raises(ValueError, match="only"):
            link.verify_interface("before", "after", kernel)
    else:
        link.verify_interface("before", "after", kernel)


@pytest.mark.parametrize("fault", [None, "old_abi", "wrong_algorithm", "changed_host"])
def test_weighted_tail_requires_exact_matching_host(tmp_path, fault):
    host = tmp_path / "sharded_k4_sssp_native_host"
    host.write_bytes(b"native host")
    pin = identity(host)
    (tmp_path / "manifest.txt").write_text(
        f"ALGORITHM={'residual_pagerank' if fault == 'wrong_algorithm' else 'weighted_sssp'}\n"
        f"PIPELINE_MODE=sharded-k4\nPREFETCH_COMPACT=1\n"
        f"TAIL_PUBLICATION={int(fault != 'old_abi')}\nHOST={host}\n"
    )
    (tmp_path / "weighted_pma_native_host.sha256").write_text(f"{pin['sha256']}  {host}\n")
    if fault == "changed_host":
        host.write_bytes(b"not the same host")
    if fault:
        with pytest.raises(ValueError, match="matching checksummed weighted tail host"):
            link.host_pins(host)
    else:
        assert link.host_pins(host)["host"] == pin
