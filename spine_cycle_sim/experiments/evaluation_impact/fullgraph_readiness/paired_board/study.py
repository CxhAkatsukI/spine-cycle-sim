"""Revalidate admissions, pin closures and raw evidence without operating a card."""

import csv
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .. import board_protocol, preparation
from ..spine_resident.__main__ import experiment as spine_experiment
from . import analysis


def requests(path):
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or [row.get("algorithm") for row in rows] != list(preparation.ALGORITHMS):
        raise ValueError("exact ordered three-algorithm requests required")
    for row in rows:
        if set(row) != {"algorithm", "gr", "spine"}:
            raise ValueError("unexpected paired request fields")
        for arm in ("gr", "spine"):
            if set(row[arm]) != {"report", "admission"} or any(
                    not Path(value).is_absolute() for value in row[arm].values()):
                raise ValueError("absolute report/admission paths required for each arm")
    return rows


def read_arm(preflight, request, algorithm, experiment):
    path = Path(request["report"])
    report = json.loads(path.read_text())
    if report.get("status") != experiment.pass_status:
        raise ValueError("matrix is not complete: " + str(path))
    plan = experiment.prepare(preflight, Path(request["admission"]), algorithm)
    pins = [preparation.identity(path), *report["pins"]]
    pins += [attempt["result_identity"] for attempt in report["attempts"] if experiment.writes_result_file]
    preparation.unchanged(pins, full=True)
    accessed = []

    def read(name):
        source = path.parent / name
        pin = preparation.identity(source)
        data = source.read_text()
        preparation.unchanged([pin], full=True)
        accessed.append(pin)
        return data

    analysis.replay(report, plan, experiment, path.parent, read)
    pins += accessed
    return report, pins


def run(preflight, request_path, output):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING_REPLAY", "errors": [], "final_figures_admitted": False}
    atomic_write_json(output / "results.json", report)
    try:
        rows = requests(request_path)
        pins = [preparation.identity(request_path)]
        arms = {"gr": [], "spine": []}
        for row in rows:
            for arm, experiment in (("gr", board_protocol.gr_experiment()), ("spine", spine_experiment())):
                value, identities = read_arm(preflight, row[arm], row["algorithm"], experiment)
                arms[arm].append(value)
                pins += identities
        report = analysis.aggregate(arms["gr"], arms["spine"])
        preparation.unchanged(pins, full=True)
        report.update(requests=rows, pins=pins, errors=[])
        fields = [*analysis.DIMENSIONS, "gr_median_ms", "spine_median_ms", "speedup_gr_over_spine"]
        with (output / "paired_wall.csv").open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(report["rows"])
    except BaseException as error:
        report.update(status="FAILED_RETAINED", final_figures_admitted=False)
        report.setdefault("errors", []).append(repr(error))
        raise
    finally:
        atomic_write_json(output / "results.json", report)
    return report
