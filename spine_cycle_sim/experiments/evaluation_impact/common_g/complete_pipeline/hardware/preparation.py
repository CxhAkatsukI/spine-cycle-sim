"""Freeze eleven XOs; replace only reviewed G wrappers and one Little placement."""

import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.routing import relocate_config
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.contract import reconstruct
from ...search_pipeline.preparation import ROOT
from ...search_pipeline.synthesis import unchanged
from ..resource_fit import topology
from .gates import candidates

COUNTS = {"bin_search": 4, "dispatch": 1, "process_cache": 2, "process_ddr": 2,
          "pma_completion_barrier": 1, "pma_to_regraph_adapter": 4, "lksg_stream": 4,
          "regraph_frontend_mux": 1, "kernelLittleGSMerger": 1, "kernelApply": 1, "kernelHBMWrapper": 1}


def relocate(contents, output, ledger):
    kernels, original = topology(contents)
    expected = {row["instance"]: row["slr"] for row in ledger["instances"]}
    if original != expected or {key: len(value) for key, value in kernels.items()} != COUNTS:
        raise ValueError("storage-screen topology differs from route basis")
    if contents.splitlines().count("slr=lksg_stream_4:SLR0") != 1:
        raise ValueError("one exact Little placement change required")
    changed = relocate_config(contents, output).replace("slr=lksg_stream_4:SLR0", "slr=lksg_stream_4:SLR1")
    placed_kernels, placed = topology(changed)
    screened = {row["instance"]: row["slr"] for row in ledger["single_cu_relocation_screen"]["instances"]}
    if placed_kernels != kernels or placed != screened:
        raise ValueError("relocated route differs from the admitted storage screen")
    return changed


def prepare(build, basis, search, review, cache, composition, fit, output):
    if output.exists():
        raise FileExistsError("fresh diagnostic route attempt required")
    replacements, reports, core = candidates(search, review, cache, composition, fit)
    previous = json.loads((basis / "manifest.json").read_text())
    unchanged(previous["pins"])
    command = list(previous["command"])
    if previous["clock_mhz"] != 150 or previous["FPGA_timing_admitted"] is not False:
        raise ValueError("unchanged 150-MHz route basis required")
    for flag in ("--config", "-o", "--target", "--kernel_frequency", "--vivado.synth.jobs", "--vivado.impl.jobs"):
        if command.count(flag) != 1:
            raise ValueError("ambiguous link command")
    if [command[command.index(flag) + 1] for flag in ("--target", "--kernel_frequency",
            "--vivado.synth.jobs", "--vivado.impl.jobs")] != ["hw", "150", "2", "2"]:
        raise ValueError("changed target, clock or jobs")
    xos = [Path(arg) for arg in command if arg.endswith(".xo")]
    if len(xos) != 11 or len(set(xos)) != 11:
        raise ValueError("eleven distinct route XOs required")
    config = Path(command[command.index("--config") + 1])
    if sha256_file(config) != sha256_file(fit / "source/link.cfg"):
        raise ValueError("resource screen was not made against this configuration")
    ledger = json.loads((fit / "results.json").read_text())
    output.mkdir(parents=True)
    (output / "inputs").mkdir()
    selected, pins = {}, [identity(basis / "manifest.json"), identity(config), *map(identity, reports)]
    for path in xos:
        kernel = path.name.split(".")[0]
        if kernel in selected:
            raise ValueError("duplicate kernel XO")
        source = replacements.get(kernel, path)
        destination = output / "inputs" / path.name
        shutil.copy2(source, destination)
        if sha256_file(source) != sha256_file(destination):
            raise ValueError("XO changed during freezing")
        selected[kernel] = {"source": identity(source), "frozen": identity(destination),
                            "replaced": kernel in replacements}
        pins += [identity(source), identity(destination)]
        command[command.index(str(path))] = str(destination)
    if set(replacements) - set(selected):
        raise ValueError("candidate kernel absent from route")
    relocated = output / "link.cfg"
    relocated.write_text(relocate(config.read_text(), output, ledger))
    command[command.index("--config") + 1] = str(relocated)
    command[command.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    (output / "tmp").mkdir()
    environment, contract = reconstruct(build, output)
    atomic_write_json(output / "environment.json", contract)
    owner = ROOT / "spine_cycle_sim/experiments/sharded_k4_stages"
    paths = [relocated, output / "environment.json"]
    paths += sorted(Path(__file__).parent.glob("*.py"))
    paths += [owner / name for name in ("execution.py", "routing.py", "link_runtime.py", "process_cleanup.py")]
    paths += sorted((owner / "empty_segment/route_environment").glob("*.py"))
    paths += [owner / "row_line/directory_tile/hardware" / name for name in
              ("concurrent.py", "admission.py", "containment.py")]
    paths += [ROOT / "spine_cycle_sim/experiments/campaign_runtime.py"]
    common = Path(__file__).parents[2]
    paths += [common / name for name in (
        "cache_probe/binding_delivery.py", "cache_probe/binding_analysis.py", "cache_probe/binding_abi.py",
        "search_binding/abi.py", "search_binding/rtl_analysis.py", "search_binding/rtl_review.py",
        "search_pipeline/rtl_analysis.py", "search_pipeline/synthesis.py", "search_pipeline/preparation.py",
        "complete_pipeline/delivery.py", "complete_pipeline/analysis.py", "complete_pipeline/resource_fit.py",
        "complete_pipeline/resource_delivery.py", "complete_pipeline/resource_probe.py")]
    pins += [*contract["pins"], *map(identity, paths)]
    manifest = {"status": "PREPARED_DIAGNOSTIC_LINK_NOT_BASELINE_ADMISSION", "command": command,
        "pins": list({pin["path"]: pin for pin in pins}.values()), "kernel_inputs": selected,
        "core_identity": core,
        "placement_change": {"instance": "lksg_stream_4", "from": "SLR0", "to": "SLR1"},
        "clock_mhz": 150, "tree_memory_gib": 40, "reserve_gib": 24, "background_memory_gib": 8,
        "allow_bounded_builds": True, "timeout_seconds": 21600, "queue_timeout_seconds": 86400,
        "integrated_rtl_admitted": False, "FPGA_timing_admitted": False,
        "production_baseline_admitted": False, "publication_match_admitted": False,
        "claim": "diagnostic_full_cache_search_export_link_not_integrated_RTL_or_board_performance"}
    unchanged(manifest["pins"])
    atomic_write_json(output / "manifest.json", manifest)
    return manifest
