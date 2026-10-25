"""Capture the author's numD=1/3 scheduling, without changing frozen evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

from spine_cycle_sim.experiments.original_regraph_inputs.analysis import analyze_layout
from .regraph import identity, save


def descriptor(layout):
    summary = layout["summary"]
    dense, sparse = summary["dense_partitions"], summary["sparse_groups"]
    if dense not in (1, 3) or (summary["little"], summary["big"]) != (11, 3):
        raise ValueError("only the declared numD=1/3, 11L3B diagnostic is supported")
    aligned = summary["aligned_vertices"]
    published = dense * 65536 + sparse * 524288
    words = [0x4d47524f, 1, summary["vertices"], summary["logical_edges"], aligned,
             published, max(aligned, published), len(layout["tasks"]), dense, sparse, 11, 3]
    if len(layout["tasks"]) != dense * 11 + sparse * 3:
        raise ValueError("task count does not match the author topology")
    for task in layout["tasks"]:
        words.extend(task[key] for key in ("partition", "subpartition", "kernel", "dst_offset",
                                          "dst_len", "offset_words", "words"))
        words.append(int(task["kind"] == "sparse"))
    return struct.pack(f"<{len(words)}I", *words)


def execute(command, output, name, timeout=180, cwd=None):
    save(output / (name + ".command.json"), command)
    with (output / (name + ".stdout.txt")).open("w") as stdout, (output / (name + ".stderr.txt")).open("w") as stderr:
        subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr, timeout=timeout, check=True)


def prepare(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "publication_match": False, "cases": [],
              "scope": "Amazon, unchanged static PR superstep; numD=1 and 3; author_initial binding",
              "board_matrix": "each numD: cold baseline + 3 warm repeats of baseline, author_order and prebound",
              "runner": identity(__file__), "errors": []}
    save(output / "preparation.json", report)
    try:
        root = Path(__file__).resolve().parents[3]
        contract_path = root / "configs/experiments/original_regraph_inputs_v1.json"
        contract = json.loads(contract_path.read_text())
        graph = next(item for item in contract["inputs"] if item["id"] == "amazon")
        report["graph"] = identity(args.graph)
        if report["graph"]["sha256"] != graph["sha256"]:
            raise ValueError("Amazon graph hash differs from the declared original input")
        report["contract"], report["probe"] = identity(contract_path), identity(args.probe)
        report["frozen_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=args.frozen, text=True).strip()
        original = args.frozen / "cpp/tests/original_regraph"
        report["frozen_headers"] = [identity(path) for path in sorted(original.rglob("*.hpp"))]
        stage = output / "original_regraph"
        shutil.copytree(original, stage)
        patch = Path(__file__).with_name("dense_admission.patch")
        report["admission_patch"] = identity(patch)
        execute(["git", "apply", str(patch)], output, "admission", cwd=stage)
        headers = stage / "hardware"
        compiler = ["/usr/bin/x86_64-linux-gnu-g++-15", "-std=c++20", "-O2", "-DNDEBUG",
                    "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-I/opt/xilinx/xrt/include", "-I" + str(headers)]
        for name in ("control", "model_tests"):
            command = compiler + [str(headers / (name + ".cpp")), "-o", str(output / name),
                                 "/opt/xilinx/xrt/lib/libxilinxopencl.so", "-Wl,-rpath,/opt/xilinx/xrt/lib"]
            execute(command, output, "compile_" + name, timeout=90)
        execute([str(output / "model_tests")], output, "model_tests")
        report["compiler"] = subprocess.check_output([compiler[0], "--version"], text=True)
        template = json.loads(args.manifest.read_text())
        frozen_case = next(case for case in template["cases"] if case["graph"] == "amazon"
                           and case["binding"] == "author_initial")
        shared = ("original_to_reordered.u32le", "csr_offsets.u32le", "csr_destinations.u32le",
                  "initial.u32le", "degrees.u32le")
        for dense in (1, 3):
            directory = output / f"numd{dense}"
            capture, inputs = directory / "capture", directory / "input"
            capture.mkdir(parents=True)
            inputs.mkdir()
            execute([str(args.probe.resolve()), str(args.graph.resolve()), str(capture), str(contract["seed"]), str(dense)],
                    directory, "capture")
            topology = {"id": "original_example", "little": 11, "big": 3, "dense_partitions_argument": dense}
            layout = analyze_layout((directory / "capture.stdout.txt").read_text(), capture, topology, graph, contract)
            (inputs / "mixed.u32le").write_bytes(descriptor(layout))
            for name in ("tasks.u32le", *shared[1:]):
                shutil.copyfile(capture / name, inputs / name)
            if dense == 1:
                for path in sorted(inputs.iterdir()):
                    if identity(path)["sha256"] != identity(Path(frozen_case["input"]) / path.name)["sha256"]:
                        raise ValueError("new numD=1 input differs from the frozen control")
            execute([str(output / "control"), "offline", str(inputs), "original_example", "author_initial",
                     str(directory / "offline")], directory, "offline")
            offline = json.loads((directory / "offline/result.json").read_text())
            expected = directory / "offline/expected.u32le"
            with expected.open("rb") as stream:
                logical = hashlib.sha256(stream.read(offline["vertices"] * 4)).hexdigest()
            case = {"graph": "amazon", "binding": "author_initial", "input": str(inputs), "offline": offline,
                    "expected": {"expected_sha256": identity(expected)["sha256"], "logical_sha256": logical}}
            save(directory / "layout.json", layout)
            save(directory / "manifest.json", {"configuration": "original_example", "xclbin": template["xclbin"], "cases": [case]})
            report["cases"].append({"numD": dense, "case": case, "layout": identity(directory / "layout.json"),
                "shared": {name: identity(capture / name)["sha256"] for name in shared},
                "inputs": [identity(path) for path in sorted(inputs.iterdir())]})
            print(f"numD={dense}: author layout and independent CSR oracle PASS", flush=True)
        left, right = report["cases"]
        if (left["shared"] != right["shared"] or
                left["case"]["expected"]["logical_sha256"] != right["case"]["expected"]["logical_sha256"] or
                left["case"]["expected"]["expected_sha256"] != frozen_case["expected"]["expected_sha256"]):
            raise ValueError("logical state/oracle changed between numD=1/3 or frozen baseline")
        if report["frozen_headers"] != [identity(path) for path in sorted(original.rglob("*.hpp"))]:
            raise ValueError("frozen headers changed")
        if identity(args.graph) != report["graph"] or identity(args.probe) != report["probe"]:
            raise ValueError("graph or layout executable changed during capture")
        report["status"] = "NUMD_INPUTS_ORACLE_PASS_NOT_FPGA"
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save(output / "preparation.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("frozen", "manifest", "probe", "graph", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    prepare(parser.parse_args())
