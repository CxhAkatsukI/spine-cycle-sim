"""Admit the reviewed production exports without rewriting their route manifest."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ..continuous_board.execution import route as shared
from ..search_pipeline.synthesis import unchanged

EXPORTS = {
    "bin_search": "e17f8394e1bbffc5ca5e7ca69b19c51ed0acafcd64c726341249287c4bf6a6ff",
    "process_cache": "2a2b3947f39387937207e2f6b77dbffd10e0d3931a2e76ffc6bd4022dda01b1b",
}
MEMBERS = {
    "grasu_complete/" + name for name in (
        "search_binding/top.cpp", "search_binding/top.hpp", "search_pipeline/types.hpp",
        "search_pipeline/search_worker.hpp", "search_pipeline/workers.hpp",
        "search_pipeline/transport.hpp", "search_pipeline/network.hpp", "cache_bank.hpp",
        "cache_lane.hpp", "cache_pipeline.hpp", "process_cache.cpp", "provenance.json")
} | {"upstream/kernel_config.h"}


def candidate(manifest):
    core = manifest.get("core_identity", {})
    if manifest.get("status") != "PREPARED_DIAGNOSTIC_LINK_NOT_BASELINE_ADMISSION" or \
            manifest.get("candidate_owner") != "production-source-grasu-complete" or \
            type(manifest.get("clock_mhz")) is not int or manifest["clock_mhz"] != 150 or \
            manifest.get("production_source_evidence") != core or any(
                core.get(key) is not True for key in ("rtl_components_rechecked", "connected_host_rechecked")) or any(
                manifest.get(key) is not False for key in ("integrated_rtl_admitted", "FPGA_timing_admitted",
                    "production_baseline_admitted", "publication_match_admitted")) or any(
                core.get(key) is not False for key in ("integrated_rtl_admitted", "device_metadata_refresh_admitted",
                    "production_baseline_admitted", "publication_match_admitted")):
        raise ValueError("reviewed production-source candidate required, not the diagnostic exports")
    rows = core.get("production_source_members", [])
    pins = {row["path"]: row["sha256"] for row in manifest["pins"]}
    if len(rows) != len(MEMBERS) or {row["member"] for row in rows} != MEMBERS or any(
            pins.get(row["path"]) != row["sha256"] for row in rows):
        raise ValueError("complete pinned production core/configuration required")
    for name, digest in EXPORTS.items():
        kernel = manifest["kernel_inputs"][name]
        if kernel["replaced"] is not True or any(kernel[key]["sha256"] != digest for key in ("source", "frozen")):
            raise ValueError("production search/cache export identity changed")
    unchanged(manifest["pins"])


def snapshot(attempt):
    manifest = json.loads((attempt / "manifest.json").read_text())
    candidate(manifest)
    extra = [row for row in manifest["pins"] if row["path"] == str(attempt / "preflight/results.json")]
    if len(extra) > 1 or extra and manifest["pins"][-1] != extra[0]:
        raise ValueError("ambiguous route preflight pin")
    return {**manifest, "pins": manifest["pins"][:-1] if extra else manifest["pins"]}


def unchanged_packet(attempt, frozen, *, complete=False):
    manifest = json.loads((attempt / "manifest.json").read_text())
    base = frozen["pins"]
    if {key: value for key, value in manifest.items() if key != "pins"} != \
            {key: value for key, value in frozen.items() if key != "pins"} or manifest["pins"][:len(base)] != base:
        raise ValueError("production route packet changed while queued")
    added = manifest["pins"][len(base):]
    if added and (len(added) != 1 or added[0] != identity(attempt / "preflight/results.json")) or complete and not added:
        raise ValueError("only the final route preflight pin may be appended")
    unchanged(manifest["pins"])


def review(attempt, original, output):
    manifest = json.loads((attempt / "manifest.json").read_text())
    candidate(manifest)
    frozen = snapshot(attempt)
    unchanged_packet(attempt, frozen, complete=True)
    checked = shared.admit_completed(attempt, original, output, manifest)
    checked["pins"].append(identity(Path(__file__)))
    checked["candidate_owner"] = manifest["candidate_owner"]
    return checked
