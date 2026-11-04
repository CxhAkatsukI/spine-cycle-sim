"""Single-run ResPR dispatch diagnostic on the previous paired image and fixture."""

import argparse
import json
from pathlib import Path

from ..board_execution import pair_resources
from . import analysis, clocks, matched_hbm, runtime


def _read_pin(pin):
    if runtime.identity(pin["path"]) != pin:
        raise ValueError(f"pinned input changed: {pin['path']}")
    return json.loads(Path(pin["path"]).read_text())


def run(previous, previous_sha, host_manifest, host_sha, output):
    output.mkdir(exist_ok=False)
    result = {"status": "DISPATCH_PROBE_FAILED_RETAINED", "repetitions": 1}
    try:
        result["previous"] = runtime.identity(previous)
        result["host_build"] = runtime.identity(host_manifest)
        if result["previous"]["sha256"] != previous_sha or result["host_build"]["sha256"] != host_sha:
            raise ValueError("previous paired receipt or host manifest hash mismatch")
        prior = _read_pin(result["previous"])
        manifest = _read_pin(result["host_build"])
        if (prior["status"] != "PAIRED_LOWER_CLOCK_ROW_GATE_FAILED"
                or (prior["case"], prior["device"], prior["bdf"]) != ("skewed_sources", 0, "0000:82:00.1")
                or manifest["status"] != "SINGLE_RUN_HOSTS_BUILD_PASS_NOT_BOARD"
                or (manifest["candidate_publication"], manifest["candidate_dispatch"]) != ("tail", "prebound")):
            raise ValueError("expected the original skewed-sources pair and prebound tail probe")
        result.update(case=prior["case"], device=prior["device"], bdf=prior["bdf"])
        reference = _read_pin(prior["reference_receipt"])
        if any(reference[key] != prior[key] for key in ("device", "bdf", "case", "input_pins")):
            raise ValueError("reference and previous candidate differ")
        target = 445
        for arm in (reference, prior):
            matched_hbm.validate_after(arm["prepared"], arm["clock_after"], target)
        reference_runs = analysis.profiled_runs(
            dict(stage="R", arm="reference", repetitions=1, result_json=reference["result"],
                 result_directory=str(Path(reference["result"]["path"]).parent),
                 clock_evidence=reference["clock_after"], **reference["run"]))
        prior_runs = _candidate_runs(prior)
        pins = prior["input_pins"]
        fixture = Path(pins[0]["path"]).parent
        if len(pins) != 6 or fixture.name != prior["case"] or any(
                Path(pin["path"]).parent != fixture or runtime.identity(pin["path"]) != pin for pin in pins):
            raise ValueError("fixture identity changed")
        build, = [row for row in manifest["builds"] if row["arm"] == "candidate"]
        if build["status"] != "COMPILED" or "-DSPINE_RETENTION_PREBOUND_DISPATCH=1" not in build["command"]:
            raise ValueError("candidate was not built with prebound dispatch")
        result.update(host=build["binary"], binary=prior["binary"], input_pins=pins)
        for key in ("host", "binary"):
            if runtime.identity(result[key]["path"]) != result[key]:
                raise ValueError(f"{key} identity changed")
        binary = Path(result["binary"]["path"])
        bdf = result["bdf"]
        expected = clocks.image(binary, output, "candidate")
        group = runtime.check_memory()
        with pair_resources.admit(0, bdf, group, 600, lambda phase, state: print(phase, state, flush=True)) as (node, fd):
            result["prepared"] = matched_hbm.prepare(binary, expected, target, output, "candidate", fd, node, bdf)
            result["run"] = runtime.execute(
                [result["host"]["path"], binary, fixture, 0, 1], output, "candidate", fd, node, bdf)
            result["clock_after"] = clocks.capture(bdf, expected, output, "candidate.after")
            matched_hbm.validate_after(result["prepared"], result["clock_after"], target)
        runs = _candidate_runs(result)
        comparison = analysis.summarize(reference_runs, runs, repetitions=1)
        before, after = prior_runs[0]["resident_wall_ms"], runs[0]["resident_wall_ms"]
        result.update(comparison=comparison, previous_resident_wall_ms=before, current_resident_wall_ms=after,
                      lower_resident_wall=after < before, status="DISPATCH_PROBE_COMPLETE_NOT_MATRIX_ADMISSION")
    except Exception as error:
        result["error"] = repr(error)
        raise
    finally:
        runtime.save(output / "results.json", result)
    return result


def _candidate_runs(row):
    return analysis.profiled_runs(dict(stage="R", arm="current", repetitions=1,
                                      clock_evidence=row["clock_after"], **row["run"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("previous", "host-manifest", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--previous-sha", required=True)
    parser.add_argument("--host-sha", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.previous, args.previous_sha, args.host_manifest,
                         args.host_sha, args.output), indent=2))
