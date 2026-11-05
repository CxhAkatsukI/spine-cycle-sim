"""Measure a replacement Spine CC arm against the verified AU diagnostic."""

import argparse
import json
import os
from pathlib import Path
import re

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import board_memory
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.board_analysis import single

from . import cc_resident_results, clocks, figure7_receipts as figure, spine_cc_warm_receipt as warm, spine_smoke
from .follow import unchanged
from .runtime import identity, save


def candidate_route(spec):
    files = {key: spec[key] for key in ("host", "image", "manifest", "link", "timing", "skew")}
    host, image = (figure.checked(files[key]) for key in ("host", "image"))
    manifest, link, timing, skew = (figure.checked(files[key]).read_text()
                                    for key in ("manifest", "link", "timing", "skew"))
    if not os.access(host, os.X_OK) or Path(str(image) + ".weighted-manifest") != Path(files["manifest"]["path"]):
        raise ValueError("candidate image and host must have their own hardware manifest")
    expected = {f"build_sha256 {spec['abi']}", f"image_sha256 {files['image']['sha256']}", "target hw"}
    if not expected <= set(manifest.splitlines()) or files["image"]["sha256"] == warm.IMAGE_SHA256:
        raise ValueError("candidate manifest does not pin a new hardware image")
    linked_image = Path(spec["linked_image"])
    lines = link.splitlines()
    created = f"INFO: [v++ 60-586] Created {linked_image}"
    completed = "INFO: [v++ 60-1307] Run completed. Additional information can be found in:"
    if (not linked_image.is_absolute() or linked_image.name != image.name
            or created not in lines or completed not in lines or lines.index(created) >= lines.index(completed)):
        raise ValueError("Vitis link did not complete for the declared hardware image")
    summary = skew.rsplit("\n2. Bus Skew Report Per Constraint", 1)[0]
    slacks = re.findall(r"^\s*(?:Slow|Fast)(?:\s+[-.\d]+){2}\s+([-.\d]+)\s*$", summary, re.MULTILINE)
    if ("All user specified timing constraints are met." not in timing
            or not slacks or min(map(float, slacks)) < 0):
        raise ValueError("candidate route did not close timing and bus skew")
    return files


def preflight(anchor_pin, candidate_pin):
    matrix = figure.load(anchor_pin)
    if (matrix["algorithm"], matrix["r_retention_all_controls_pass"]) != ("cc", False):
        raise ValueError("expected the pinned non-parity CC diagnostic")
    entry = matrix["cases"]["AU"]
    child = figure.load(entry["result"])
    if entry["status"] != figure.MEASURED or child["status"] != figure.MEASURED:
        raise ValueError("AU anchor is not a completed board pair")
    gates, extra = matrix["baseline"], matrix["additional_r_gates"]
    previous = figure.measured("cc", "AU", child, child, gates, extra["amazon_odd"],
                               gates["image"], topology_miss=extra["au_slice"])
    previous["boundary"] = figure.BOUNDARIES["cc"]
    old_spine = figure.load(child["retained_spine"])
    inputs = next(pin for pin in old_spine["pins"] if pin["sha256"] == warm.INPUTS_SHA256)
    if figure.load(inputs) != old_spine["workload"]:
        raise ValueError("AU split inputs differ from the retained pair")
    candidate = figure.load(candidate_pin)
    files = candidate_route(candidate)
    return dict(anchor=anchor_pin, prior=previous, inputs=inputs, arm=entry["result"],
                candidate=candidate_pin, files=files, abi=candidate["abi"])


def replay(prepared, smoke_pin):
    data = figure.load(smoke_pin)
    previous, files = prepared["prior"], prepared["files"]
    workload = figure.load(prepared["inputs"])
    clock = clocks.replay(data["clock_evidence"])
    if (data["status"] != "RESIDENT_CC_STATE_WORK_AND_CLOCK_PASS_NOT_PERFORMANCE_ADMISSION"
            or data["performance_admission"] is not False or data["errors"] != []
            or data["workload"] != workload or (data["bdf"], data["device"]) != (warm.BDF, 0)
            or clock["binary"] != files["image"] or clock["bdf"] != warm.BDF
            or clock["driver_reported_mhz"] != previous["clocks_mhz"]["gr"]):
        raise ValueError("candidate smoke does not match the AU graph, card and clock")
    execution = data["execution"]
    command = ["/usr/bin/taskset", "-c", "124,125", files["host"]["path"],
               "--xclbin", files["image"]["path"], "--hot", "0", "--mode", "partial",
               "--samples", "1", "--slice", workload["graph"]["path"], "--update", workload["update"]["path"]]
    if (not set(warm.AFFINITY).issubset(execution["host_affinity"])
            or (execution["command"], execution["exit_code"], execution["stop_reason"],
                execution["cleanup_snapshot_error"], execution["cleanup_signaled_pids"])
            != (command, 0, "process_exit", None, [])):
        raise ValueError("expected one clean, CPU-pinned AU candidate execution")
    required = [files["host"], files["image"], files["manifest"], prepared["inputs"],
                *(workload[key] for key in ("source", "graph", "update")), identity(spine_smoke.__file__)]
    if any(pin not in data["pins"] for pin in required):
        raise ValueError("candidate runner did not pin the exact image, host and inputs")
    board_memory.require_unthrottled(data["memory_events"])
    gr_log = previous["raw"]["gr"]["stdout"]
    spine_log = figure.checked(data["stdout"]).read_text()
    if single(spine_log.splitlines(), "CC_SETUP").get("source_config_sha256") != prepared["abi"]:
        raise ValueError("candidate host log does not match the routed build configuration")
    unchanged([smoke_pin, data["stderr"], prepared["anchor"], prepared["arm"],
               prepared["candidate"], gr_log, data["stdout"], *required, *files.values()])
    pair = cc_resident_results.analyze(workload, figure.checked(gr_log).read_text(), spine_log, bdf=warm.BDF)
    if pair["gr_ms"] != previous["gr_ms"] or pair["boundary"] != previous["boundary"]:
        raise ValueError("candidate comparison changed the baseline time or boundary")
    return dict(status="CC_AU_REVISION_DIAGNOSTIC_NOT_PARITY_ADMISSION", new_pair=pair,
                old_spine_ms=previous["spine_ms"], old_pair=previous["comparison"],
                retained_gr_log=gr_log, candidate_smoke=smoke_pin, candidate_route=prepared["candidate"],
                anchor=prepared["anchor"], stage_ratios=previous["stage_ratios"], verifier=identity(__file__))


def pinned_arg(path_and_sha):
    path, sha = path_and_sha
    pin = identity(path)
    if pin["sha256"] != sha:
        raise ValueError(f"declared SHA-256 does not match {path}")
    return pin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("anchor", "candidate"):
        parser.add_argument("--" + name, nargs=2, required=True, metavar=("JSON", "SHA256"))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--run", type=Path, metavar="NEW_OUTPUT_DIR")
    action.add_argument("--replay", nargs=2, metavar=("SMOKE_JSON", "SHA256"))
    parser.add_argument("--admission-wait-seconds", type=int, default=0)
    args = parser.parse_args()
    prepared = preflight(pinned_arg(args.anchor), pinned_arg(args.candidate))
    if args.preflight:
        print(json.dumps({"status": "PREFLIGHT_ONLY", **prepared}, indent=2))
        return
    if args.run is not None:
        args.run.mkdir(parents=True, exist_ok=False)
        save(args.run / "preflight.json", prepared)
        files = prepared["files"]
        smoke = args.run / "spine" / "results.json"
        spine_smoke.run(argparse.Namespace(
            host=Path(files["host"]["path"]), image=Path(files["image"]["path"]), output=smoke.parent,
            memory_gib=24, admission_wait_seconds=args.admission_wait_seconds,
            input_manifest=Path(prepared["inputs"]["path"]), resident_wall=True))
    result = replay(prepared, identity(smoke) if args.run is not None else pinned_arg(args.replay))
    if args.run is not None:
        save(args.run / "comparison.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
