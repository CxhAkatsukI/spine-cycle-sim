"""Recheck component exports and source composition before a diagnostic link."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ...cache_probe.binding_delivery import validate as cache_validate
from ...search_binding.rtl_analysis import analyze as search_analyze, status as search_status
from ...search_binding.rtl_review import STABLE
from ...search_pipeline.synthesis import unchanged
from ..delivery import PASS, validate as composition_validate
from ..resource_delivery import validate_fit
from ..resource_fit import resources
from .core_identity import check as core_identity


def search(attempt, review):
    original = json.loads((attempt / "results.json").read_text())
    checked = json.loads((review / "results.json").read_text())
    if (original["status"] != "FAILED_RETAINED" or set(original["analysis"]["errors"]) != {"abi"}
            or checked["original"] != {"path": str(attempt / "results.json"),
                                      "sha256": sha256_file(attempt / "results.json")}
            or checked["errors"] or checked["new_hardware_execution"] is not False):
        raise ValueError("unchanged ABI-only failure and independent review required")
    execution = json.loads((attempt / "attempt/execution.resources.json").read_text())
    if execution != original["execution"] or execution["exit_code"] or execution["timed_out"]:
        raise ValueError("successful unchanged search-wrapper execution required")
    pins = original["source"] + original["basis"] + [original["script"], checked["original"]]
    pins += original["analysis"]["artifacts"]
    pins += [{"path": row["frozen_path"], "sha256": row["sha256"]}
             for row in original["runner_source"] + checked["runner_source"]]
    unchanged(pins)
    observation = search_analyze(attempt / "attempt", attempt / "reference")
    if (observation != checked["analysis"] or search_status(observation) != checked["status"]
            or checked["status"] != "WRAPPER_RTL_ABI_PASS_TARGET_MET_REQUIRES_INTEGRATION"
            or any(observation[key] != original["analysis"][key] for key in STABLE)):
        raise ValueError("search review differs from frozen RTL/export evidence")
    return attempt / "attempt/search_binding.xo"


def candidates(search_attempt, search_review, cache_attempt, composition, fit):
    search_xo = search(search_attempt, search_review)
    cache = json.loads((cache_attempt / "results.json").read_text())
    cache_validate(cache_attempt, cache)
    if cache["status"] != "CACHE_WRAPPER_RTL_ABI_PASS_TARGET_MET_REQUIRES_INTEGRATION":
        raise ValueError("passing full-cache wrapper export required")
    complete = json.loads((composition / "results.json").read_text())
    composition_validate(composition, complete)
    if complete["status"] != PASS:
        raise ValueError("passing complete-state source composition required")
    core = core_identity(composition, search_attempt, cache_attempt)
    ledger = json.loads((fit / "results.json").read_text())
    validate_fit(fit, ledger)
    relocated = ledger["single_cu_relocation_screen"]
    platform = relocated.get("platform_storage_screen")
    if (platform is None or platform["uram_oversubscribed_slrs"] or platform["total_uram_capacity_exceeded"]
            or relocated["uram_oversubscribed_slrs"] or relocated["total_uram_capacity_exceeded"]):
        raise ValueError("relocated storage screen does not fit platform hard pblocks")
    for name, attempt in (("bin_search", search_attempt), ("process_cache", cache_attempt)):
        if resources(fit / "source/hls" / (name + ".xml"), name) != resources(
                attempt / "attempt/project/solution/syn/report" / (name + "_csynth.xml"), name):
            raise ValueError("storage screen does not describe candidate wrapper resources")
    reports = [search_attempt / "results.json", search_review / "results.json",
               cache_attempt / "results.json", composition / "results.json", fit / "results.json"]
    return {"bin_search": search_xo, "process_cache": cache_attempt / "attempt/process_cache.hw.xo"}, reports, core
