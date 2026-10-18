"""Read-only review of a terminal algorithm compile and portable storage queries."""

import csv
import io
import json
from pathlib import Path
import sys
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ....search_pipeline.synthesis import unchanged
from ... import resource_delivery
from ...resource_fit import SLRS
from . import commands, inputs, inspection


def capacities(capsule):
    index = resource_delivery.verify(capsule)
    values, pins = {}, [identity(capsule / "index.json")]
    for scope, filename, field, expected in (
        ("physical", "uram_capacity.csv", "physical_capacity", resource_delivery.QUERY_STATUSES[0]),
        ("platform", "platform_uram_capacity.csv", "platform_uram_capacity", resource_delivery.QUERY_STATUSES[1]),
    ):
        entries = [row for row in index["attempts"] if row["kind"] == "query" and row["status"] == expected]
        if len(entries) != 1:
            raise ValueError("one independently verified capacity query required: " + scope)
        archive = capsule / entries[0]["archive"]
        pins.append(identity(archive))
        with tarfile.open(archive) as stream:
            report = json.load(stream.extractfile("results.json"))
            if report["part"] != inspection.PART or report.get("errors"):
                raise ValueError("storage query part/status changed")
            table = list(csv.DictReader(io.StringIO(stream.extractfile(filename).read().decode("ascii"))))
        counts = {row["region"]: int(row["uram_sites"]) for row in table}
        if len(table) != 4 or set(counts) != {*SLRS, "device"} or any(n <= 0 for n in counts.values()) \
                or sum(counts[slr] for slr in SLRS) != counts["device"] or counts != report[field]:
            raise ValueError("capacity table disagrees with its verified query")
        values[scope] = counts
    unchanged(pins)
    return values, pins


def run(compilation, storage, output):
    compilation, storage, output = (path.resolve() for path in (compilation, storage, output))
    output.mkdir(parents=True, exist_ok=False)
    result = {"status": "REVIEWING", "errors": [], **inputs.CLAIMS}
    try:
        execution_file, manifest_file = compilation / "execution.json", compilation / "manifest.json"
        runners = {Path(module.__file__) for name, module in sys.modules.copy().items()
                   if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)}
        pins = [identity(execution_file), identity(manifest_file), identity(Path(sys.executable)),
                *map(identity, sorted(runners))]
        execution, manifest = (json.loads(path.read_text()) for path in (execution_file, manifest_file))
        if execution["status"] != "COMPILATION_PASS_AWAITING_RESOURCE_RTL_AND_ROUTE" or execution["errors"]:
            raise ValueError("completed successful algorithm compilation required")
        if any(record.get(key) is not False for record in (execution, manifest) for key in inputs.CLAIMS):
            raise ValueError("compile manifest overstates its evidence boundary")
        if execution["manifest"] != identity(manifest_file) or execution["algorithm"] != manifest["algorithm"] \
                or manifest["clock_mhz"] != 150:
            raise ValueError("compile execution/manifest identity changed")
        pins.extend(manifest["pins"])
        unchanged(pins)
        source = Path(manifest["source_manifest"]["path"]).parent
        sources = inputs.verify(source)
        if manifest["source_manifest"] != identity(source / "sources.json") or \
                manifest["integration_revision"] != sources["integration_revision"]:
            raise ValueError("source identity differs from completed compilation")
        rows = manifest["compiles"]
        admitted = commands.compile_list(compilation / "packet", manifest["algorithm"], rows[0]["argv"][0], source / "source")
        if rows != admitted or [row["kernel"] for row in execution["compiles"]] != [row["kernel"] for row in rows]:
            raise ValueError("compile command/completed kernel coverage changed")
        for declared, completed in zip(rows, execution["compiles"]):
            measured = completed["resources"]
            if measured["exit_code"] or measured["stop_reason"] != "process_exit" or \
                    measured["cleanup_snapshot_error"] or completed["xo"] != identity(Path(declared["xo"])):
                raise ValueError("completed XO or compile outcome changed")
            pins.append(completed["xo"])
        events = dict(line.split() for line in execution["memory_events_after"].splitlines())
        if any(int(events.get(key, "0")) for key in ("oom", "oom_kill", "oom_group_kill")):
            raise ValueError("compilation recorded an OOM event")
        capacity, storage_pins = capacities(storage)
        pins.extend(storage_pins)
        configs = [path for path in (compilation / "packet/config").glob("*.cfg")
                   if "[connectivity]" in path.read_text()]
        if len(configs) != 1:
            raise ValueError("one complete generated connectivity config required")
        result.update(inspection.inspect(configs[0], rows, capacity["physical"], capacity["platform"]))
        pins.extend(result.pop("pins"))
        unchanged(pins)
        result.update(algorithm=manifest["algorithm"], integration_revision=manifest["integration_revision"],
                      inputs=pins)
    except BaseException as error:
        result.update(status="FAILED_RETAINED")
        result["errors"].append(repr(error))
        raise
    finally:
        atomic_write_json(output / "results.json", result)
    return result
