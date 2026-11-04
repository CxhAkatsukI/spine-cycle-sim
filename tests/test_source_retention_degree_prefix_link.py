from copy import deepcopy

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import degree_prefix_link as link
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity, save
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import candidate_board


@pytest.mark.parametrize("fault", [None, "stream", "control", "arg", "defines", "unexpected_master"])
def test_degree_interface_only_allows_burst_and_prefix_register(monkeypatch, fault):
    ports = [{"name": "M_AXI_GMEM0", "dataWidth": "64"}, {"name": "S_AXI_CONTROL", "range": "0x38"},
             {"name": "in", "dataWidth": "64"}]
    old = dict(ports=ports, args=[{"id": str(i)} for i in range(5)])
    new = deepcopy(old)
    new["ports"][0]["dataWidth"] = "512"
    new["ports"][1]["range"] = "0x40"
    new["args"].append(dict(link.PREFIX_ARG))
    before_flags = {"degree": "1"}
    after_flags = dict(before_flags)
    if fault == "stream":
        new["ports"][2]["dataWidth"] = "512"
    elif fault == "control":
        new["ports"][1]["range"] = "0x48"
    elif fault == "arg":
        new["args"][3]["id"] = "8"
    elif fault == "defines":
        after_flags["degree"] = "0"
    elif fault == "unexpected_master":
        new["ports"].append({"name": "M_AXI_GMEM1", "dataWidth": "512"})
    components = {"old": (old, before_flags), "new": (new, after_flags)}
    monkeypatch.setattr(link, "kernel_interface", lambda name, kernel: deepcopy(components[name]))
    if fault:
        with pytest.raises(ValueError, match="degree replacement must preserve"):
            link.verify_interface("old", "new")
    else:
        link.verify_interface("old", "new")


@pytest.mark.parametrize("fault", [None, "new_host_contents", "unpinned_host", "missing_replacement"])
def test_board_host_replays_degree_replacement_pins(tmp_path, fault):
    host = tmp_path / link.HOST_NAME
    replacement = tmp_path / f"{link.KERNEL}.hw.xo"
    host.write_bytes(b"host")
    replacement.write_bytes(b"xo")
    pins = {"host": identity(host), "after": identity(replacement)}
    save(tmp_path / "manifest.json", dict(
        degree_prefix=pins, pins=[pins["after"]] if fault == "unpinned_host" else list(pins.values()),
        command=["link"] if fault == "missing_replacement" else ["link", str(replacement)]))
    if fault == "new_host_contents":
        host.write_bytes(b"changed")
    if fault:
        with pytest.raises(ValueError):
            candidate_board.native_host_sha256(tmp_path)
    else:
        assert candidate_board.native_host_sha256(tmp_path) == pins["host"]["sha256"]
