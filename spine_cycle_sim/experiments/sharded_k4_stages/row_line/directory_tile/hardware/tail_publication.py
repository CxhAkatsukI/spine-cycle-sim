"""Check the one permitted gather ABI change and its compiled host pair."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.routing import kernel_interface
from .component import unchanged


def check_gather(original, candidate):
    before, macros = kernel_interface(original, "lksg_stream")
    after, new_macros = kernel_interface(candidate, "lksg_stream")
    flag = "GRASU_REGRAPH_TAIL_PUBLICATION"
    if flag in macros or new_macros != {**macros, flag: "1"} or before["control"] != "ap_ctrl_chain":
        raise ValueError("unexpected gather control or compile options")
    control_port = next(port for port in before["ports"] if port["name"] == "S_AXI_CONTROL")
    if control_port["range"] != "0x30" or len(before["args"]) != 8:
        raise ValueError("unexpected production gather ABI")
    control_port["range"] = "0x38"
    before["args"][5:] = [
        dict(name="publication_rows", addressQualifier="0", id="5", port="S_AXI_CONTROL",
             size="0x4", offset="0x30", hostOffset="0x0", hostSize="0x4", type="unsigned int"),
        *[dict(arg, id=str(index)) for index, arg in enumerate(before["args"][5:], 6)],
    ]
    if after != before:
        raise ValueError("gather ABI change is not limited to publication_rows")


def host_pair(manifest):
    build = json.loads(manifest.read_text())
    by_arm = {record["arm"]: record for record in build["builds"]}
    flag = "-DSPINE_RETENTION_TAIL_PUBLICATION=1"
    if (build["status"] != "SINGLE_RUN_HOSTS_BUILD_PASS_NOT_BOARD"
            or build["candidate_publication"] != "tail" or len(build["builds"]) != 2
            or by_arm.keys() != {"reference", "candidate"}
            or any(record["status"] != "COMPILED" or
                   (flag in record["command"]) != (arm == "candidate") for arm, record in by_arm.items())):
        raise ValueError("matched tail-publication host pair required")
    binaries = {arm: record["binary"] for arm, record in by_arm.items()}
    for binary in binaries.values():
        path = Path(binary["path"])
        if {**identity(path), "bytes": path.stat().st_size} != binary:
            raise ValueError("pinned build input changed")
    return binaries


def gather_replacement(original, component, hosts):
    component, hosts = component.resolve(), hosts.resolve()
    execution, manifest = (component / name for name in ("execution.json", "manifest.json"))
    built, recipe = (json.loads(path.read_text()) for path in (execution, manifest))
    argv = recipe["command"]
    candidate = Path(argv[argv.index("-o") + 1])
    if (built["status"] != "COMPONENT_XO_PASS_NOT_ROUTED" or built["xo"] != identity(candidate)
            or candidate.name != original.name or "--compile" not in argv or "--link" in argv
            or argv[argv.index("--target") + 1] != "hw" or argv[argv.index("--kernel_frequency") + 1] != "150"):
        raise ValueError("passing 150-MHz tail-publication gather XO required")
    unchanged(recipe["pins"])
    check_gather(original, candidate)
    binaries = host_pair(hosts)
    pins = [identity(path) for path in (execution, manifest, candidate, hosts, Path(__file__))]
    return candidate, pins + [identity(Path(binary["path"])) for binary in binaries.values()] + recipe["pins"]
