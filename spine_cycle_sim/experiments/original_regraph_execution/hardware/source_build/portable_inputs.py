"""Freeze the author A4 CC source and allow only machine-path relocation."""

import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import replacement_capsule
from .. import artifact
from . import active_min, configuration as config, snapshot


SCHEMA = "public-a4-cc-source-relocation-v1"
STATUS = "AUTHOR_TOPOLOGY_SNAPSHOT_PASS_AWAITING_COMPILE_ABI_ROUTE_BOARD"
ALGORITHM = "cc"
TOPOLOGY = "a4"
CONNECTIVITY = Path("source/acc_template/connectivity.cfg")
VENDOR_FILES = ("Vitis/2024.1/bin/v++", "Vivado/2024.1/bin/vivado",
                "Vitis_HLS/2024.1/bin/vitis_hls", "Vitis_HLS/2024.1/include/ap_int.h")


def vendor(xilinx):
    return {name: artifact.identity(xilinx / name)["sha256"] for name in VENDOR_FILES}


def source_files(report, base):
    if (report["status"] != STATUS or report["errors"] or report["algorithm"] != ALGORITHM
            or report["configuration"] != TOPOLOGY or report["placement"] != "author"
            or report["compiler_launched"] is not False or report["board_programmed"] is not False
            or report["physical_configuration"]["config"] != str(base / CONNECTIVITY)):
        raise ValueError("passing author A4 CC source snapshot required")
    files = {}
    for row in report["pins"]:
        path = Path(row["path"])
        if path.is_relative_to(base):
            name = path.relative_to(base)
            if name.parts[0] in ("source", "algorithm", "entries"):
                files[str(name)] = row["sha256"]
    required = {str(CONNECTIVITY), "algorithm/udf/l2.h", "entries/apply_interface.tcl",
                *(f"entries/{name}.cpp" for name in config.kernels(TOPOLOGY))}
    if not required <= files.keys():
        raise ValueError("incomplete author source and compatibility entries")
    return files


def prepare(previous, output, shim):
    receipt = previous / "results.json"
    pin = artifact.identity(receipt)
    report = json.loads(receipt.read_text())
    files = source_files(report, previous)
    snapshot.unchanged([pin, *report["pins"]])
    output.mkdir(parents=True, exist_ok=False)
    for name, path in {**{name: previous / name for name in files}, "source-preflight.json": receipt,
                       "gcc_compat/bits/gthr-default.h": shim}.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    packet = {"schema": SCHEMA, "preflight": pin, "files": replacement_capsule.inventory(output),
              "platform": replacement_capsule.platform_pin(config.PLATFORM),
              "vendor": vendor(config.COMPILER.parents[3])}
    atomic_write_json(output / "capsule.json", packet)
    verify(output, config.PLATFORM, config.COMPILER.parents[3], artifact.identity(output / "capsule.json")["sha256"])
    return packet


def verify(root, platform, xilinx, digest):
    capsule = root / "capsule.json"
    if artifact.identity(capsule)["sha256"] != digest:
        raise ValueError("A4 capsule digest differs from the submitted manifest")
    packet = json.loads(capsule.read_text())
    observed = replacement_capsule.inventory(root)
    del observed["capsule.json"]
    if (packet["schema"] != SCHEMA or observed != packet["files"]
            or any(path.is_symlink() for path in root.rglob("*"))
            or packet["platform"] != replacement_capsule.platform_pin(platform)
            or packet["vendor"] != vendor(xilinx)):
        raise ValueError("A4 source, platform or reviewed vendor files changed")
    report = json.loads((root / "source-preflight.json").read_text())
    base = Path(packet["preflight"]["path"]).parent
    expected = {**source_files(report, base), "source-preflight.json": packet["preflight"]["sha256"],
                "gcc_compat/bits/gthr-default.h": packet["files"]["gcc_compat/bits/gthr-default.h"]}
    if expected != packet["files"]:
        raise ValueError("transferred sources differ from the original preflight")
    canonical = commands(base / "source", base, config.COMPILER, config.PLATFORM)
    if report["commands_not_executed"] != canonical:
        raise ValueError("preflight command differs from the author topology")
    active_min.check_apply_bank(root / CONNECTIVITY, TOPOLOGY, ALGORITHM)
    return packet


def commands(source, output, compiler, platform):
    def relocate(argv):
        argv = list(argv)
        argv[0] = str(compiler)
        argv[argv.index("--platform") + 1] = str(platform)
        include = "-I" + str(config.COMPILER.parents[3] / "Vitis_HLS/2024.1/include/etc")
        if include in argv:
            argv[argv.index(include)] = "-I" + str(compiler.parents[3] / "Vitis_HLS/2024.1/include/etc")
        return argv

    return {"compilations": {name: relocate(config.compile_command(source, output, name,
                TOPOLOGY, algorithm=ALGORITHM)) for name in config.kernels(TOPOLOGY)},
            "link": relocate(config.link_command(source, output, TOPOLOGY, algorithm=ALGORITHM))}
