"""Fresh original-DDR synthesis, finite shared-bus simulation, and source controls."""

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..upstream_controls.execution import run_bounded, dependency_identities
from . import analysis, fixtures, preparation


def step_order(contract):
    names = ["version_" + name for name in ("hls", "xvlog", "xelab", "xsim")]
    names += ["synthesis", "xvlog", "xelab", "xelab_memory", "normal_compile", "ubsan_compile"]
    names += ["bus_" + item["id"] for item in contract["bus_controls"]]
    for case in contract["cases"]:
        names += [case["id"] + "_source_" + name for name in ("first", "repeat", "ubsan")]
        names += [case["id"] + f"_rtl_{index}" for index in range(contract["repetitions"])]
    return names


def run(root: Path, hls: Path, tools: Path, include: Path, baseline: Path, output: Path):
    path = root / "configs/experiments/original_grasu_ddr_rtl_v1.json"
    contract = json.loads(path.read_text())
    if not hls.is_file() or not (include / "ap_int.h").is_file() or any(not (tools / name).is_file() for name in ("xvlog", "xelab", "xsim")):
        raise ValueError("original DDR RTL control needs HLS, XSim and real HLS headers")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(path, output / "contract.json")
    report = {"schema_version": 1, "status": "NOT_COMPLETED", "contract_sha256": sha256_file(path),
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "source_identities": preparation.identities(root), "baseline": str(baseline),
        "preservation": preparation.preserve(root, baseline), "steps": [], "cases": [], "bus_controls": [],
        "FPGA_measured_cycles": None, "publication_rate_error_pct": None, "evidence_class": contract["evidence_class"]}

    def execute(name, command, cwd=root, timeout=contract["compile_timeout_seconds"], expected_rejection=False):
        print("Starting " + name + " (isolated original DDR RTL, not board/publication timing)", flush=True)
        step = {"id": name, **run_bounded(command, cwd, output / name, timeout=timeout,
            memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        report["steps"].append(step)
        atomic_write_json(output / "report.json", report)
        if step["timed_out"] or step["exit_code"] not in ((0, 1) if expected_rejection else (0,)):
            raise ValueError(name + " failed; original diagnostics retained")
        return step

    try:
        compiler = shutil.which("g++")
        if not compiler:
            raise ValueError("G++ missing")
        report["compiler_version"] = subprocess.check_output([compiler, "--version"], text=True)
        report["tools"] = []
        versions = output / "tool_versions"; versions.mkdir()
        for name, executable in [("hls", hls), *[(name, tools / name) for name in ("xvlog", "xelab", "xsim")]]:
            step = execute("version_" + name, [str(executable), "-version"], versions)
            actual = executable.parent / "unwrapped/lnx64.o" / executable.name
            report["tools"].append({"name": name, "version_stdout": Path(step["stdout"]).read_text(),
                "files": [{"path": str(path.resolve()), "sha256": sha256_file(path)} for path in (executable, actual)]})
        report["hls_preparation"] = preparation.prepare(root, output, include, contract)
        execute("synthesis", [str(hls), "-f", str(output / "hls/synthesis.tcl")], output / "hls")
        report["rtl_files"] = preparation.freeze_rtl(output)
        report["schedules"] = preparation.schedules(output)
        simulation = output / "simulation"; simulation.mkdir()
        verilog = sorted((output / "rtl").glob("*.v"))
        execute("xvlog", [str(tools / "xvlog"), "--sv", *map(str, verilog), *[str(output / "bench" / name) for name in ("shared_memory.sv", "bench.sv", "memory_test.sv")]], simulation)
        execute("xelab", [str(tools / "xelab"), "work.grasu_ddr_bench", "--snapshot", "grasu_ddr_sim", "--debug", "typical"], simulation)
        execute("xelab_memory", [str(tools / "xelab"), "work.grasu_memory_test", "--snapshot", "grasu_memory_sim", "--debug", "typical"], simulation)
        report["simulation_binaries"] = [{"path": str(path), "sha256": sha256_file(path)}
            for name in ("grasu_ddr_sim", "grasu_memory_sim") for path in sorted((simulation / "xsim.dir" / name).glob("xsimk*")) if path.is_file() and path.suffix not in (".wdb", ".log")]
        report["source_binaries"] = []
        for name in ("normal", "ubsan"):
            directory = output / name; directory.mkdir()
            binary = directory / "probe"
            flags = [compiler, "-std=c++20", "-O1", "-g0", "-D_GLIBCXX_ASSERTIONS", "-DDISABLE_MAX_HLS_STREAM_DEPTH_PRINT", "-Wno-unknown-pragmas",
                "-MD", "-MT", "probe", "-MF", str(directory / "dependencies.d"), f"-I{include}", f"-I{include / 'etc'}", f"-I{output / 'hls/source'}"]
            if name == "ubsan": flags += ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
            execute(name + "_compile", flags + [str(output / "bench/source_probe.cpp"), "-pthread", "-lgmp", "-o", str(binary)])
            report["source_binaries"].append({"path": str(binary), "sha256": sha256_file(binary), "dependencies": dependency_identities(directory / "dependencies.d", root)})
        bus_fixture = output / "bus_fixture"
        fixtures.prepare(bus_fixture, {"sequence": "empty"})
        for control in contract["bus_controls"]:
            command = [str(tools / "xsim"), "grasu_memory_sim", "--runall", "--onfinish", "quit", "--onerror", "quit",
                "--testplusarg", "LATENCY=64", "--testplusarg", f"INITIAL={bus_fixture / 'initial.hex'}", "--testplusarg", f"MODE={control['mode']}"]
            step = execute("bus_" + control["id"], command, simulation, contract["run_timeout_seconds"], control["rejection"] is not None)
            report["bus_controls"].append({"id": control["id"], **analysis.bus(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), control)})
        for case in contract["cases"]:
            directory = output / "cases" / case["id"]
            inputs = fixtures.prepare(directory, case)
            row = {"id": case["id"], "status": "RUNNING", "directory": str(directory), "fixture": inputs, "source": [], "rtl": []}
            report["cases"].append(row)
            for label, family in (("first", "normal"), ("repeat", "normal"), ("ubsan", "ubsan")):
                capture = directory / (label + "_source"); capture.mkdir()
                shutil.copyfile(directory / "expected.u32le", capture / "expected.u32le")
                step = execute(case["id"] + "_source_" + label, [str(output / family / "probe"), str(directory / "initial.u32le"), str(directory / "updates.u32le"), str(capture / "source.u32le")], timeout=contract["run_timeout_seconds"])
                row["source"].append(analysis.source(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), capture, case))
            if row["source"] != [row["source"][0]] * 3:
                raise ValueError("original DDR source repetition or UBSan changed state")
            for repetition in range(contract["repetitions"]):
                capture = directory / f"rtl_{repetition}.hex"
                args = {"LATENCY": case["latency"], "COUNT": inputs["updates"], "GAP": case["input_gap"], "MAX_CYCLES": contract["max_cycles"],
                    "INITIAL": directory / "initial.hex", "UPDATES": directory / "updates.hex", "OUTPUT": capture}
                command = [str(tools / "xsim"), "grasu_ddr_sim", "--runall", "--onfinish", "quit", "--onerror", "quit"]
                for key, value in args.items(): command += ["--testplusarg", f"{key}={value}"]
                step = execute(case["id"] + f"_rtl_{repetition}", command, simulation, contract["run_timeout_seconds"])
                row["rtl"].append(analysis.rtl(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), capture, directory, case, contract))
            if row["rtl"] != [row["rtl"][0]] * contract["repetitions"]:
                raise ValueError("original DDR RTL repetition changed complete state or event trace")
            row["status"] = row["rtl"][0]["status"]
            atomic_write_json(output / "report.json", report)
        if preparation.identities(root) != report["source_identities"]:
            raise ValueError("original DDR RTL experiment code changed during collection")
        report["preservation"] = preparation.preserve(root, baseline)
        report["status"] = analysis.STATUS if all(row["status"] == analysis.STATUS for row in report["cases"]) else analysis.MISMATCH
    except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as error:
        report["status"], report["error"] = "FAILED", str(error)
    atomic_write_json(output / "report.json", report)
    return report
