"""Check numerical smoke equivalence and export one portable host cohort."""

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import shlex
import tarfile

from . import analysis
from ..r_credits.freeze import pin

STATUS = "PERSISTENT_PAIRED_SETUP_PREDICTION"
DATASETS = {"AU": "sx_askubuntu", "SU": "sx_superuser", "WK": "wiki_talk_temporal",
            "SO": "sx_stackoverflow", "PK": "soc_pokec"}


def checked(identity):
    path = Path(identity["path"])
    if pin(path) != identity:
        raise ValueError("changed portable receipt: " + str(path))
    return path.read_bytes()


def numerical_pins(report):
    result = {}
    for identity in report["pins"]:
        path = identity["path"]
        if "/cpp/" in path:
            key = "cpp/" + path.split("/cpp/", 1)[1]
        elif path.endswith("/configs/memory/HBM2_1ch_x128_summary_only.ini"):
            key = "configs/memory/HBM2_1ch_x128_summary_only.ini"
        elif path.endswith("/libdramsim3.so"):
            key = "dramsim3/libdramsim3.so"
        elif path.endswith("/src/dramsim3.h"):
            key = "dramsim3/dramsim3.h"
        else:
            continue
        if key in result:
            raise ValueError("duplicate numerical source identity")
        result[key] = {k: identity[k] for k in ("bytes", "sha256")}
    if not any(k.startswith("cpp/") for k in result) or not all(
            k in result for k in ("configs/memory/HBM2_1ch_x128_summary_only.ini",
                                 "dramsim3/libdramsim3.so", "dramsim3/dramsim3.h")):
        raise ValueError("incomplete numerical source identities")
    return result


def build_recipe(report, paths=None):
    identity = next(p for p in report["build_pins"] if p["path"].endswith("/compile_commands.json"))
    root = report["steps"]["plugin"]["cwd"]
    build = str(Path(identity["path"]).parent)
    paths = paths or report["environment"]["paths"]
    replacements = [(build, "$BUILD"), (root, "$SOURCE")]
    replacements += [(paths[k], "$" + k.upper()) for k in ("sst_include", "dram")]

    def normalize(command):
        tokens = list(command)
        tokens[0] = "$CXX"  # Compiler binaries belong to separate host cohorts.
        for old, new in replacements:
            tokens = [token.replace(old, new) for token in tokens]
        return tokens

    core = {}
    for row in json.loads(checked(identity)):
        if any("/" + target + ".dir/" in row["output"]
               for target in ("spine_cycle_core", "original_regraph_cycle")):
            key = "cpp/" + row["file"].split("/cpp/", 1)[1]
            if key in core:
                raise ValueError("duplicate compiled numerical unit")
            core[key] = normalize(row.get("arguments") or shlex.split(row["command"]))
    if not core:
        raise ValueError("compiled numerical units required")
    return dict(core=core, plugin=normalize(report["steps"]["plugin"]["command"]))


def verify_numerical_sources(report, reference):
    actual, expected = numerical_pins(report), reference["numerical_pins"]
    for identity in report["pins"]:
        if "/cpp/" in identity["path"] or any(
                identity["path"].endswith(suffix) for suffix in (
                    "/configs/memory/HBM2_1ch_x128_summary_only.ini",
                    "/libdramsim3.so", "/src/dramsim3.h")):
            checked(identity)
    # CMake may add unrelated test targets; compare the compiled units and flags.
    compared = set(expected) - {"cpp/CMakeLists.txt"}
    if any(actual.get(k) != expected[k] for k in compared):
        raise ValueError("numerical source or DRAM identity differs from local reference")
    extra = set(actual) - set(expected)
    if any(not k.startswith("cpp/tests/") for k in extra):
        raise ValueError("unreviewed numerical inventory expansion")
    if build_recipe(report) != reference["build_recipe"]:
        raise ValueError("compiled numerical units or flags differ from local reference")
    return sorted(extra)


def device_row(report, name, *, updates, batches):
    arm = name.rsplit("_", 1)[1]
    row = report["rows"][name]
    checked(row["stdout"])
    if report["steps"][name]["stdout"] != row["stdout"]["path"]:
        raise ValueError("step and row stdout differ")
    parsed = analysis.persistent_device(report["steps"][name], arm=arm,
                                        updates=updates, batch_count=batches)
    if parsed != {key: row[key] for key in ("device", "batches")}:
        raise ValueError("stored device counters differ from raw log")
    return parsed


def freeze_reference(path, paths=None):
    report = json.loads(path.read_bytes())
    if report["status"] != STATUS:
        raise ValueError("complete local reference required")
    rows = {arm: device_row(report, "smoke_" + arm, updates=3, batches=3)
            for arm in ("spine", "gr")}
    return dict(reference=pin(path), numerical_pins=numerical_pins(report),
                build_recipe=build_recipe(report, paths), smoke=rows,
                reference_environment_paths=paths or report["environment"]["paths"],
                raw_smoke={arm: checked(report["rows"]["smoke_" + arm]["stdout"]).decode()
                           for arm in rows},
                boundary="exact smoke device counters only; host nanoseconds excluded")


def cohort_key(report):
    environment = report["environment"]
    if not environment.get("host") or not environment.get("cpu_model"):
        raise ValueError("explicit host and CPU model required")
    dependencies = {}
    for key in ("compiler", "sst"):
        path = environment["paths"][key]
        identity = next(item for item in report["pins"] if item["path"] == path)
        checked(identity)
        dependencies[key] = {k: identity[k] for k in ("bytes", "sha256")}
    return dict(host=environment["host"], cpu_model=environment["cpu_model"],
                platform=environment["platform"], compiler_version=report["compiler_version"],
                dependencies=dependencies, git_head=report["git_head"])


def collect(dataset, path, reference):
    report_bytes = path.read_bytes()
    report = json.loads(report_bytes)
    if dataset not in DATASETS or report["status"] not in (STATUS, "FAILED_RETAINED"):
        raise ValueError("completed or retained-failure predeclared case required")
    extra_tests = verify_numerical_sources(report, reference)
    for arm in ("spine", "gr"):
        if device_row(report, "smoke_" + arm, updates=3, batches=3) != reference["smoke"][arm]:
            raise ValueError("portable smoke device counters differ")
    manifests = [item for item in report["pins"] if Path(item["path"]).name == "manifest.json"
                 and Path(item["path"]).parent.name == dataset.lower()]
    if len(manifests) != 1:
        raise ValueError("one dataset-specific relocated manifest required")
    manifest_bytes = checked(manifests[0])
    manifest = json.loads(manifest_bytes)
    relocation = manifest["input_relocation"]
    original_bytes = checked(relocation["source_manifest"])
    original = json.loads(original_bytes)
    expected = dict(original, graph=manifest["graph"], updates=manifest["updates"],
                    input_relocation=relocation)
    if manifest != expected or manifest["dataset"] != DATASETS[dataset]:
        raise ValueError("relocation changed dataset semantics")
    for key in ("graph", "updates"):
        identity = next(item for item in report["pins"] if item["path"] == manifest[key])
        if identity != relocation["inputs"][key] or pin(Path(identity["path"])) != identity:
            raise ValueError("relocated input identity differs")
    members = {f"{dataset}/results.json": report_bytes,
               f"{dataset}/input_manifest.json": manifest_bytes,
               f"{dataset}/original_manifest.json": original_bytes}
    compiled = next(p for p in report["build_pins"] if p["path"].endswith("/compile_commands.json"))
    members[f"{dataset}/compile_commands.json"] = checked(compiled)
    for name, step in report["steps"].items():
        for stream in ("stdout", "stderr"):
            source = Path(step[stream])
            members[f"{dataset}/raw/{name}.{stream}.txt"] = source.read_bytes()
    for name, row in report["rows"].items():
        for key in ("config", "backend", "stdout"):
            members[f"{dataset}/{name}/{key}" + Path(row[key]["path"]).suffix] = checked(row[key])
        for key, identity in row.get("host_evidence", {}).items():
            members[f"{dataset}/{name}/host_{key}" + Path(identity["path"]).suffix] = checked(identity)
    row = dict(dataset=dataset, status=report["status"], cpu=report["cpu"], updates=4096,
               batches=10, host_samples_per_arm=1, baseline_admitted=False,
               speedup_gr_over_spine=None, error=report.get("error", ""),
               expanded_test_files=len(extra_tests),
               receipt_sha256=hashlib.sha256(report_bytes).hexdigest())
    if report["status"] == STATUS:
        for arm in ("spine", "gr"):
            name = "trace_" + arm
            device_row(report, name, updates=4096, batches=10)
            host = analysis.persistent_host(report["steps"][name + "_host"], arm=arm,
                                            updates=4096, batch_count=10)
            if host != report["rows"][name]["host"]:
                raise ValueError("stored host row differs from raw log")
            for label in ("config", "host_evidence"):
                identity = (report["rows"][name][label] if label == "config" else
                            report["rows"][name][label]["config"])
                config = json.loads(checked(identity))
                if any(config[k] != manifest[k] for k in ("graph", "updates")) or config["batches"] != 10:
                    raise ValueError("trace arm input or batch scope differs")
        comparison = analysis.persistent_comparison(
            {arm: report["rows"]["trace_" + arm] for arm in ("spine", "gr")},
            updates=4096, batch_count=10)
        if comparison != report["comparisons"]["trace"]:
            raise ValueError("stored comparison differs from setup formula")
        row["speedup_gr_over_spine"] = comparison["speedup_gr_over_spine"]
        for arm in ("spine", "gr"):
            row.update({arm + "_" + k: v for k, v in comparison[arm].items()})
            row[arm + "_device_cycles"] = report["rows"]["trace_" + arm]["device"]["cycles"]
    elif "trace" in report["comparisons"] or not report.get("error"):
        raise ValueError("failed case must retain its error, not a trace comparison")
    return row, members, cohort_key(report)


def export(cases, reference_path, output):
    if set(cases) != set(DATASETS):
        raise ValueError("all five cases, including failures, required")
    reference_bytes = reference_path.read_bytes()
    reference = json.loads(reference_bytes)
    rows, members, cohort = [], {"reference.json": reference_bytes}, None
    for dataset in DATASETS:
        row, files, key = collect(dataset, cases[dataset], reference)
        if cohort is not None and key != cohort:
            raise ValueError("mixed host, compiler or runtime cohorts")
        cohort = key
        rows.append(row)
        members.update(files)
    output.mkdir(parents=True, exist_ok=False)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with (output / "fig8_ten_batch.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    scope = dict(evidence="same-host measured preparation plus simulated device/transfer; not FPGA",
        status="COMPLETE" if all(r["status"] == STATUS for r in rows) else "PARTIAL_RETAINED",
        expected=list(DATASETS), measured=[r["dataset"] for r in rows if r["status"] == STATUS],
        failed=[r["dataset"] for r in rows if r["status"] != STATUS], cohort=cohort,
        exact_local_smoke_device_match=True, numerical_pins=reference["numerical_pins"],
        cases=rows, reference_sha256=hashlib.sha256(reference_bytes).hexdigest())
    (output / "scope.json").write_text(json.dumps(scope, indent=2) + "\n")
    with (output / "receipts.tar.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for name, content in sorted(members.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
    return scope


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--reference", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--reference-sst-include", type=Path)
    freeze.add_argument("--reference-dram", type=Path)
    run = sub.add_parser("export")
    run.add_argument("--case", nargs=2, action="append", required=True)
    run.add_argument("--reference", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "freeze":
        if (args.reference_sst_include is None) != (args.reference_dram is None):
            parser.error("both reference runtime directories are required together")
        paths = (dict(sst_include=str(args.reference_sst_include), dram=str(args.reference_dram))
                 if args.reference_dram is not None else None)
        reference = freeze_reference(args.reference, paths)
        with args.output.open("x") as stream:
            stream.write(json.dumps(reference, indent=2) + "\n")
    else:
        cases = {name: Path(path) for name, path in args.case}
        if len(cases) != len(args.case):
            parser.error("duplicate dataset labels")
        export(cases, args.reference, args.output)
