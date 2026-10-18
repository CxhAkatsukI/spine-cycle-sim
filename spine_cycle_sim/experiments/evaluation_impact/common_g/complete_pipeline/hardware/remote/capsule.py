"""Export an already reviewed production packet without rewriting its evidence."""

import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.routing import relocate_config
from ....production_board import route as production
from ....search_pipeline.synthesis import unchanged
from ..preparation import COUNTS

SCHEMA = "production-link-relocation-v1"
FLAGS = ("integrated_rtl_admitted", "FPGA_timing_admitted",
         "production_baseline_admitted", "publication_match_admitted")
POLICY = {"tree_memory_gib": 40, "reserve_gib": 32, "background_memory_gib": 8,
          "allow_bounded_builds": True}


def validate_command(parent):
    command = parent["command"]
    expected = {"--target": "hw", "--kernel_frequency": "150",
                "--vivado.synth.jobs": "2", "--vivado.impl.jobs": "2"}
    for flag in (*expected, "--config", "-o"):
        if command.count(flag) != 1 or command.index(flag) + 1 == len(command):
            raise ValueError("ambiguous production link argument: " + flag)
    if any(command[command.index(flag) + 1] != value for flag, value in expected.items()) or \
            command.count("--link") != 1 or any(parent.get(key) is not False for key in FLAGS):
        raise ValueError("unchanged 150-MHz, two-job, unadmitted production link required")
    xos = [arg for arg in command if arg.endswith(".xo")]
    inputs = parent["kernel_inputs"]
    if set(inputs) != set(COUNTS) or len(xos) != len(COUNTS) or \
            set(xos) != {row["frozen"]["path"] for row in inputs.values()} or \
            len({Path(path).name for path in xos}) != len(COUNTS):
        raise ValueError("all eleven exact production XOs required")


def prepare(parent_directory, output):
    if output.exists():
        raise FileExistsError("fresh relocation capsule required")
    parent_path = parent_directory / "manifest.json"
    parent = json.loads(parent_path.read_text())
    production.candidate(parent)
    validate_command(parent)
    parent_identity = identity(parent_path)
    output.mkdir(parents=True)
    files, replacements = [], {}

    def copy(source, member, digest=None):
        before = identity(source)
        if digest is not None and before["sha256"] != digest:
            raise ValueError("source differs from production admission: " + str(source))
        target = output / member
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if identity(source) != before or sha256_file(target) != before["sha256"]:
            raise ValueError("input changed while copying")
        files.append({"member": member, "sha256": before["sha256"], "source": before})
        return member

    copy(parent_path, "parent/manifest.json", parent_identity["sha256"])
    config_path = Path(parent["command"][parent["command"].index("--config") + 1])
    config_pins = [row for row in parent["pins"] if row["path"] == str(config_path)]
    if len(config_pins) != 1:
        raise ValueError("one production connectivity pin required")
    copy(config_path, "parent/link.cfg", config_pins[0]["sha256"])
    for row in parent["kernel_inputs"].values():
        source = row["frozen"]
        replacements[source["path"]] = copy(Path(source["path"]), "inputs/" + Path(source["path"]).name,
                                             source["sha256"])
    for row in parent["core_identity"]["production_source_members"]:
        copy(Path(row["path"]), "source/" + row["member"], row["sha256"])
    old_environment = json.loads((parent_directory / "environment.json").read_text())
    shim = Path(old_environment["effective"]["values"]["CPLUS_INCLUDE_PATH"]) / "bits/gthr-default.h"
    shim_pins = [row for row in parent["pins"] if row["path"] == str(shim.resolve())]
    if len(shim_pins) != 1:
        raise ValueError("one reviewed compatibility shim pin required")
    copy(shim, "gcc_compat/bits/gthr-default.h", shim_pins[0]["sha256"])
    unchanged(parent["pins"])
    if identity(parent_path) != parent_identity:
        raise ValueError("production manifest changed during export")
    packet = {"schema": SCHEMA, "parent": parent_identity, "files": files,
              "xo_replacements": replacements, "checked_parent_pin_count": len(parent["pins"]),
              "policy": dict(POLICY), "timeout_seconds": 43200, **dict.fromkeys(FLAGS, False),
              "legacy_include_flags": "retained verbatim; this is XO link, not source recompilation",
              "scope": "same production XOs/connectivity; remote toolchain and platform recorded separately"}
    atomic_write_json(output / "capsule.json", packet)
    return packet


def verify(root):
    packet = json.loads((root / "capsule.json").read_text())
    if packet["schema"] != SCHEMA or packet["policy"] != POLICY or packet["timeout_seconds"] != 43200 or \
            any(packet.get(key) is not False for key in FLAGS):
        raise ValueError("relocation scope or resource contract changed")
    seen = set()
    for row in packet["files"]:
        member = Path(row["member"])
        if member.is_absolute() or ".." in member.parts or member in seen or \
                not (root / member).resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe or duplicate capsule member")
        seen.add(member)
        if sha256_file(root / member) != row["sha256"] or row["source"]["sha256"] != row["sha256"]:
            raise ValueError("relocated input changed: " + str(member))
    if sha256_file(root / "parent/manifest.json") != packet["parent"]["sha256"]:
        raise ValueError("parent identity changed")
    parent = json.loads((root / "parent/manifest.json").read_text())
    validate_command(parent)
    expected = {row["frozen"]["path"]: "inputs/" + Path(row["frozen"]["path"]).name
                for row in parent["kernel_inputs"].values()}
    indexed = {row["member"]: row["sha256"] for row in packet["files"]}
    if packet["xo_replacements"] != expected or any(
            indexed.get(expected[row["frozen"]["path"]]) != row["frozen"]["sha256"]
            for row in parent["kernel_inputs"].values()):
        raise ValueError("XO relocation differs from parent")
    sources = {row["member"]: row["source"] for row in packet["files"]}
    config_path = parent["command"][parent["command"].index("--config") + 1]
    pinned = {row["path"]: row["sha256"] for row in parent["pins"]}
    required = {"parent/manifest.json": packet["parent"],
                "parent/link.cfg": {"path": config_path, "sha256": pinned[config_path]},
                **{"inputs/" + Path(row["frozen"]["path"]).name: row["frozen"]
                   for row in parent["kernel_inputs"].values()},
                **{"source/" + row["member"]: {key: row[key] for key in ("path", "sha256")}
                   for row in parent["core_identity"]["production_source_members"]}}
    shim = sources.get("gcc_compat/bits/gthr-default.h", {})
    if pinned.get(shim.get("path")) != shim.get("sha256") or not shim.get("sha256"):
        raise ValueError("compatibility shim is not a reviewed parent input")
    required["gcc_compat/bits/gthr-default.h"] = shim
    if set(indexed) != set(required) or any(sources[member] != source or
            indexed[member] != source["sha256"] for member, source in required.items()):
        raise ValueError("relocation source/configuration differs from parent")
    if packet["checked_parent_pin_count"] != len(parent["pins"]):
        raise ValueError("parent pin count changed")
    return packet, parent


def configuration(contents, output, platform):
    lines = contents.splitlines()
    if len([line for line in lines if line.startswith("platform=")]) != 1:
        raise ValueError("one explicit platform required")
    changed = "\n".join("platform=" + str(platform) if line.startswith("platform=") else line
                        for line in lines) + "\n"
    return relocate_config(changed, output)


def command(packet, parent, root, output, compiler):
    argv = [str(root / packet["xo_replacements"][arg]) if arg in packet["xo_replacements"] else arg
            for arg in parent["command"]]
    argv[0] = str(compiler)
    argv[argv.index("--config") + 1] = str(output / "link.cfg")
    argv[argv.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    return argv
