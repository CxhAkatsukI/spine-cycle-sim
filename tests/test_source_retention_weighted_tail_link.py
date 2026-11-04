from copy import deepcopy
import json

import pytest

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    tail_topology as topology,
)
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


def test_weighted_tail_bound_host_is_not_substitutable(tmp_path):
    capsule = tmp_path / "capsule"
    (capsule / "parent").mkdir(parents=True)
    manifest = capsule / "parent/manifest.json"
    manifest.write_text("{}")
    host = tmp_path / "host"
    host.write_bytes(b"host")
    assert link.check_bound_host(capsule, host, "weighted_sssp") == []
    pins = {"host": identity(host)}
    manifest.write_text(json.dumps({"weighted_tail": {"host": pins}}))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(link, "host_pins", lambda value: {"host": identity(value)})
        assert link.check_bound_host(capsule, host, "weighted_sssp") == [identity(manifest), pins["host"]]
        for bad_host, algorithm in ((manifest, "weighted_sssp"), (host, "cc")):
            with pytest.raises(ValueError, match="exact weighted tail capsule"):
                link.check_bound_host(capsule, bad_host, algorithm)


def routed_fixture(tail):
    memory = [("HBM[22]", "MEM_HBM", 1, "0x40000")]
    connections = [("adapter", 0, "HBM[22]")]
    for index, cu in enumerate(sorted(topology.GATHER_CUS)):
        for arg in (0, 5, 6, 7):
            tag = f"test_{index}_{arg}_{tail}"
            memory.append((tag, topology.STREAM_TYPE, 1, "0"))
            connections.extend([(cu, arg + int(tail and arg != 0), tag), (f"peer{index}", arg, tag)])
    return {"clock": [("DATA", "DATA_CLK", 150)], "kernels": sorted(topology.GATHER_CUS),
            "memory": sorted(memory), "connections": sorted(connections)}


@pytest.mark.parametrize("fault", [None, "axis_endpoint", "arg_id", "physical", "clock"])
def test_routed_tail_accepts_only_the_expected_stream_renumbering(fault):
    old, candidate = routed_fixture(False), routed_fixture(True)
    if fault == "clock":
        candidate["clock"] = [("DATA", "DATA_CLK", 140)]
    if fault == "physical":
        candidate["connections"][0] = ("adapter", 1, "HBM[22]")
    if fault in ("axis_endpoint", "arg_id"):
        index = next(i for i, (_, arg, _) in enumerate(candidate["connections"]) if arg == 8)
        cu, arg, tag = candidate["connections"][index]
        candidate["connections"][index] = (cu if fault == "arg_id" else "wrong_peer",
                                             5 if fault == "arg_id" else arg, tag)
    if fault:
        with pytest.raises(ValueError, match="weighted"):
            topology.verify(old, candidate)
    else:
        topology.verify(old, candidate)
