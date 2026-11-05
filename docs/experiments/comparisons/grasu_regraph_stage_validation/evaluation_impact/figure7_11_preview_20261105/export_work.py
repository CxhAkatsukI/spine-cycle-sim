"""Recheck and package fresh Figures 10--11, preserving failed-case retries."""

import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.delivery import archive


def export(campaign, replacements, analysis_dir, output):
    # Refit calibration rows and replay every admission. The published analysis
    # must match this replay; no value is copied from a previous figure package.
    with TemporaryDirectory(prefix="fig1011-replay-") as temporary:
        replay = Path(temporary)
        summary = analyze(campaign, replacements=replacements, output=replay)
        for path in sorted(replay.iterdir()):
            if sha256_file(path) != sha256_file(analysis_dir / path.name):
                raise ValueError("analysis differs from fresh replay: " + path.name)
    if (summary["status"], summary["executions"], summary["fig10_bars"],
            summary["fig11_fit_and_holdout_rows"], summary["fpga_stage_calibrated"]) != (
            "PASS_SIMULATOR_PREDICTION", 42, 11, 41, False):
        raise ValueError("wrong execution scope or evidence claim")
    output.mkdir(parents=True, exist_ok=True)
    for path in sorted(analysis_dir.iterdir()):
        if path.is_file():
            name = "fig11_" + path.name.removeprefix("rq3_") if path.name.startswith("rq3_") else path.name
            shutil.copyfile(path, output / name)
    origins = json.loads((analysis_dir / "measurement_origins.json").read_text())
    files, inputs = [], {}
    for origin in origins:
        directory = Path(origin["out_dir"])
        files.extend((p, f"runs/{origin['execution_id']}/{p.relative_to(directory)}")
                     for p in sorted(directory.rglob("*")) if p.is_file())
    for index, directory in enumerate((campaign, *replacements)):
        prefix = "campaign" if index == 0 else f"retry{index}"
        for name in ("identity.json", "matrix.json", "status.json"):
            files.append((directory / name, f"{prefix}/{name}"))
        files.extend((p, f"{prefix}/profiles/{p.name}") for p in sorted((directory / "profiles").glob("*")))
        for case in json.loads((directory / "matrix.json").read_text())["cases"]:
            for pin in case["inputs"].values():
                inputs[pin["sha256"]] = Path(pin["path"])
    embedded, external = {}, {}
    for sha, path in inputs.items():
        if sha256_file(path) != sha:
            raise ValueError("changed figure input: " + str(path))
        pin = dict(path=str(path), sha256=sha, bytes=path.stat().st_size)
        if path.stat().st_size <= 8 * 1024 * 1024:
            files.append((path, f"inputs/{sha}/{path.name}"))
            embedded[sha] = pin
        else:
            external[sha] = pin
    index = archive(output / "fig10_11_receipts.tar.gz", files)
    atomic_write_json(output / "fig10_11_scope.json", dict(
        status="COMPLETE_SIMULATOR_PREDICTION", summary=summary, evidence=index,
        sources={str(p): sha256_file(p) for p in sorted(analysis_dir.iterdir()) if p.is_file()},
        embedded_inputs=embedded, external_inputs=external,
        fpga_stage_calibrated=False, failed_original_case_preserved=True,
        failed_attempts="original status/matrix retained; successful R19 CC retry changes memory budget only",
        not_claimed="no FPGA stage calibration; model predicts simulator output, not hardware"))
    return dict(status="COMPLETE_SIMULATOR_PREDICTION", executions=42, fig10_bars=11, fig11_rows=41)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--replacement-campaign", type=Path, action="append", default=[])
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.campaign.resolve(), tuple(p.resolve() for p in args.replacement_campaign),
                            args.analysis.resolve(), args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
