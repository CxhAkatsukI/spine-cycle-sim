"""Recompute the final prediction from portable raw states, traces and reports."""

import hashlib
from pathlib import Path
import tarfile
import zipfile

from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs
from ...adapter_axi.analysis import parse_trace
from ...adapter_axi.study import RTL_PREFIX
from ...empty_segment.production import require_report
from ...routing import adapter_interface
from ..continuous_directory.recheck import read, require_pin, source_archive
from ..cross_row.validation import FLAGS
from ..evidence import bounded
from .analysis import admit, directory_lines, matrix
from .contract import BASIS_SHA
from .validation import ALL_TRIALS, compare, functional, model_schedule, schedules


def checked_runs(run):
    for path in run.rglob("*.resources.json"):
        row = read(path)
        bounded(path, row["command"], row["cwd"], row["timeout_seconds"], row["tree_memory_gib"])


def model(root):
    run = root / "model"
    manifest, report = read(run / "manifest.json"), read(run / "results.json")
    require_pin(run / "manifest.json", {"sha256": report["manifest_sha256"]})
    require_pin(root / "basis/results.json", {"sha256": BASIS_SHA})
    require_pin(root / "hls/results.json", manifest["hls"])
    hls_report = read(root / "hls/results.json")
    model_schedule(hls_report)
    for key, default in (("tile_rows", 128), ("packet_pipeline", False),
                         ("bank_stream", False), ("bank_fifo_lines", 128)):
        if not same_typed(manifest.get(key, default), hls_report.get(key, default)):
            raise ValueError("model topology differs from realized HLS")
    source_archive(run)
    for pin in manifest["input_pins"]:
        old = Path(pin["path"])
        require_pin(run / "inputs" / old.parent.name / old.name, pin)
    for item in read(root / "basis/manifest.json")["inputs"]:
        for pin in item["files"]:
            old = Path(pin["path"])
            require_pin(run / "inputs" / old.parent.name / old.name, pin)
    for pin in report["build_files"]:
        old_build = Path(manifest["build_commands"][0][4])
        require_pin(run / "build" / Path(pin["path"]).relative_to(old_build), pin)
    options = {key: manifest.get(key, False) for key in ("packet_pipeline", "bank_stream", "bank_read_beats")}
    options["tile_rows"] = manifest["tile_rows"]
    if manifest.get("bank_fifo_lines", 128) != 128:
        options["bank_fifo_lines"] = manifest["bank_fifo_lines"]
    basis, cases = read(root / "basis/results.json"), []
    for row in report["cases"]:
        spec = tuple(row[key] for key in ("mode", "latency", "reverse", "arm"))
        mode, latency, reverse, arm = spec
        label = f"{mode}_lat{latency}_reverse{reverse}_{arm}"
        previous = f"{mode}_lat{latency}_reverse{reverse}_{'original' if arm == 'original' else 'cross_row'}"
        cases.append(admit((run / "raw" / (label + ".stdout.txt")).read_text(), run / "states" / label,
            basis, spec, (root / "basis/raw" / (previous + ".stdout.txt")).read_text(),
            directory_lines(run / "inputs" / mode), **options))
    summary = matrix(cases)
    if (not same_typed(cases, report["cases"]) or report["default_plugin_unchanged"] is not True
            or any(not same_typed(value, report[key]) for key, value in summary.items())):
        raise ValueError("raw model conclusion differs")
    checked_runs(run / "raw")
    names = ("legacy", "tile", "packet", "bank", "beats")
    if manifest.get("bank_fifo_lines", 128) != 128:
        names += ("wide",)
    for name in names:
        path = run / "raw" / (name + ".stdout.txt")
        if not path.is_file():
            raise ValueError("complete adapter modes required")
        if name == "legacy":
            markers = ("Whole-line directory PASS cases=240", "Cross-row structural model PASS cases=210")
        else:
            count = 132 if name in {"tile", "packet"} else 168
            markers = (f"Directory tile PASS cases={count} packet_traffic_order_backpressure_restart=PASS",)
        if any(marker not in path.read_text() for marker in markers):
            raise ValueError("adapter mode did not pass complete functional fixtures")
    return report


def hls_sources(run):
    pins = read(run / "manifest.json")["pins"]
    expected = {}
    for pin in pins:
        path = Path(pin["path"])
        if path.suffix in {".xo", ".xpfm"} or path.name in {"v++", "xvlog", "xelab", "xsim"}:
            continue
        integration = "kernels" in path.parts or path.name in {
            "pma_adapter_row_prefetch_tb.cpp", "check_pma_adapter_cross_row.sh", "env.sh"}
        anchor = ("kernels" if "kernels" in path.parts else path.parent.name) if integration else (
            "cpp" if "cpp" in path.parts else "spine_cycle_sim")
        name = ("integration/" if integration else "simulator/") + "/".join(path.parts[path.parts.index(anchor):])
        if name in expected:
            raise ValueError("duplicate archived source")
        expected[name] = pin
    blobs = {}
    with tarfile.open(run / "sources.tar.gz", "r:gz") as archive:
        members = archive.getmembers()
        if len(members) != len(expected) or {m.name for m in members} != expected.keys():
            raise ValueError("HLS source membership differs")
        for member in members:
            if not member.isfile() or member.size > 8 * 1024**2:
                raise ValueError("invalid HLS source type/size")
            data = archive.extractfile(member).read()
            if hashlib.sha256(data).hexdigest() != expected[member.name]["sha256"]:
                raise ValueError("HLS source bytes differ")
            blobs[expected[member.name]["path"]] = data
    return blobs


def rtl(run, arm, xo, sources, trials):
    directory = run / arm
    with zipfile.ZipFile(xo) as archive:
        generated = {Path(name).name: archive.read(name) for name in archive.namelist()
            if name.startswith(RTL_PREFIX) and Path(name).suffix in {".v", ".vh"}}
    if not generated:
        raise ValueError("complete generated RTL required")
    for name, data in generated.items():
        if (directory / name).read_bytes() != data:
            raise ValueError("executed RTL differs from XO")
    for pin in read(directory / "inputs.json"):
        if pin["path"] in sources:
            if hashlib.sha256(sources[pin["path"]]).hexdigest() != pin["sha256"]:
                raise ValueError("RTL external source differs")
        elif Path(pin["path"]).suffix == ".xo":
            require_pin(xo, pin)
        else:
            require_pin(directory / Path(pin["path"]).name, pin)
    for name in ("bank_stream_axi_tb.sv", "adapter_axi_tb.sv"):
        source = next(data for path, data in sources.items() if path.endswith("/" + name))
        if (directory / name).read_bytes() != source:
            raise ValueError("executed bench differs")
    return parse_trace((directory / "simulate.stdout.txt").read_text(), trials)


def hls(root):
    run = root / "hls"
    manifest, report = read(run / "manifest.json"), read(run / "results.json")
    sources = hls_sources(run)
    candidate, reference = run / "production/adapter.hw.xo", root / "reference.xo"
    require_pin(candidate, report["xo"])
    reference_pin = next(pin for pin in manifest["pins"] if Path(pin["path"]).suffix == ".xo")
    require_pin(reference, reference_pin)
    interface, flags = adapter_interface(candidate)
    old_interface, old_flags = adapter_interface(reference)
    if not same_typed(interface, old_interface):
        raise ValueError("unchanged ABI required")
    expected_flags = FLAGS | {"GRASU_REGRAPH_DIRECTORY_TILE_ROWS": "1024",
                              "GRASU_REGRAPH_PACKET_PIPELINE": "1", "GRASU_REGRAPH_BANK_STREAM": "1"}
    if report.get("bank_fifo_lines", 128) != 128:
        expected_flags["GRASU_REGRAPH_BANK_FIFO_LINES"] = str(report["bank_fifo_lines"])
    if ({k: v for k, v in flags.items() if k.startswith("GRASU_")} != manifest["flags"] or
            manifest["flags"] != expected_flags or
            {k: v for k, v in old_flags.items() if k.startswith("GRASU_")} != FLAGS):
        raise ValueError("declared HLS selection differs")
    functional((run / "functional.stdout.txt").read_text(), True, True)
    parsed = require_report(run / "production")
    for key, value in parsed.items():
        if key in {"report", "burst_report"}:
            value = value["sha256"]
            expected = report["hls"][key]["sha256"]
        else:
            expected = report["hls"][key]
        if not same_typed(value, expected):
            raise ValueError("raw HLS resources/timing differ")
    observed = schedules(run / "production/build", True, True)
    normalize = lambda rows: {name: {k: v for k, v in row.items() if k != "path"} for name, row in rows.items()}
    if not same_typed(normalize(observed), normalize(report["schedule"])):
        raise ValueError("raw HLS schedule differs")
    model_schedule(report)
    if any(row["estimated_ns"] > row["target_ns"] for row in observed.values()):
        raise ValueError("realized schedule misses target clock")
    trials = ALL_TRIALS + [(1023, 1, 1, 64, 0), (1024, 2, 1, 64, 0), (1025, 1, 1, 128, 1000),
                           (257, 0, 3, 64, 0), (129, 0, 3, 128, 1000)]
    arms = {arm: rtl(run, arm, xo, sources, trials) for arm, xo in (("reference", reference), ("candidate", candidate))}
    comparison = compare(arms["reference"], arms["candidate"], 1024, trials, True)
    if not same_typed(arms, report["arms"]) or not same_typed(comparison, report["comparison"]):
        raise ValueError("complete RTL trace conclusion differs")
    checked_runs(run)
    return report


def recheck(root):
    prediction, hardware = model(root), hls(root)
    regression = root / "regression"
    legacy = compare_runs(read(regression / "contract.json"), root / "legacy_basis", regression / "legacy-after")
    if legacy["status"] != "PASS" or not same_typed(legacy, read(regression / "legacy-after/equivalence.json")):
        raise ValueError("legacy SST full-result replay differs")
    require_pin(regression / "plugin/libspine_cycle.so", {"sha256": legacy["candidate_identity"]["plugin_sha256"]})
    checked_runs(regression)
    if "100% tests passed, 0 tests failed out of 27" not in (regression / "core-tests.stdout.txt").read_text():
        raise ValueError("core verification incomplete")
    warm = [row for row in prediction["cases"] if row["mode"] == "warm_update" and row["arm"] == "tile" and not row["reverse"]]
    return {"status": prediction["status"], "target_met": prediction["target_met"],
        "model_runs": len(prediction["cases"]), "warm_results": [{key: row[key] for key in
            ("latency", "cycles", "candidate_over_A4", "v3_over_candidate")} for row in warm],
        "core_tests": 27, "legacy_SST_cases": len(legacy["cases"]), "RTL_cases": len(hardware["comparison"]),
        "adapter_resources": hardware["hls"]["resources"], "hardware_timing_admitted": False,
        "strict_resource_match_admitted": False, "publication_match_admitted": False,
        "production_promotion": False, "paper_modified": False}
