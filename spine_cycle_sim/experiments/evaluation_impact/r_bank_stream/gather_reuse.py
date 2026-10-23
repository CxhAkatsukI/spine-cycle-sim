"""Control redundant Gather resets using the source's destructive output scan."""

import argparse
from functools import partial
import json
from pathlib import Path
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..r_credits.freeze import ROOT, pin
from . import elastic_analysis, prefetch_convergence, wrapper_schedule
from .runtime import FRESH_CPU

ARMS = ("a4_io16", "prefetch_sssp_write_issue", "prefetch_gather_reuse")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]


def verify(pins):
    if any(pin(Path(item["path"])) != item for item in pins):
        raise ValueError("frozen Gather reset artifact changed")


def freeze(output, reference, regraph):
    baseline = json.loads(reference.read_text())
    if (baseline.get("status") != "SSSP_WRAPPER_CONTROL_COMPLETE_SIMULATOR_PREDICTION" or
            baseline.get("pins_unchanged") is not True or baseline.get("failures") != [] or
            [elastic_analysis.identity(row) for row in baseline["r_rows"]] != wrapper_schedule.MATRIX):
        raise ValueError("checked complete wrapper reference required")
    external = [item for item in baseline["pins"] if not Path(item["path"]).is_relative_to(ROOT)]
    verify(external)
    gather = regraph / "acc_template/kernel_little_gs/acc_gather.h"
    host = regraph / "host/host.cpp"
    if ("dst_tmp_prop_buffer[u][i] = 0;" not in gather.read_text() or
            "bool reset_tmp_prop = (super_step == 0);" not in host.read_text()):
        raise ValueError("review required: original destructive-flush/reset contract differs")
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim", "configs", "tests", "scripts", "sst")
                     for p in (ROOT / owner).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts) + [ROOT / "CMakeLists.txt"]
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for source in sources:
            archive.add(source, arcname=source.relative_to(ROOT), recursive=False)
    (output / "pre_edit.diff").write_bytes(subprocess.check_output(
        ["git", "diff", "--binary", "HEAD"], cwd=ROOT))
    result = dict(status="PRE_GATHER_REUSE_CONTROL_FROZEN", reference=pin(reference),
        sources=[pin(p) for p in sources], external=external, compiler=pin(Path("/usr/bin/g++").resolve()),
        source_contract=[pin(gather), pin(host)],
        artifacts=[pin(output / name) for name in ("sources.tar.gz", "pre_edit.diff")],
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        baseline_admitted=False)
    atomic_write_json(output / "freeze.json", result)
    return result


def summarize(rows, reference, *, before):
    result = elastic_analysis.summarize(rows, reference, before=before, arms=ARMS,
        before_matrix=wrapper_schedule.MATRIX, physical_masters=dict(zip(ARMS, (13, 16, 16))),
        reduction_key="cycle_reduction_from_redundant_reset")
    result["only_control_change"] = (
        "first Gather invocation resets; later invocations reuse storage cleared by the complete output scan; "
        "all output rows, backpressure, physical traffic and memory timings retained")
    return result


def run(output, reference, before, core_reference, cpus):
    frozen = json.loads(before.read_text())
    if frozen.get("status") != "PRE_GATHER_REUSE_CONTROL_FROZEN" or frozen["reference"] != pin(reference):
        raise ValueError("pre-edit Gather reset freeze required")
    verify(frozen["artifacts"] + frozen["source_contract"] + frozen["external"] + [frozen["compiler"]])
    baseline = json.loads(reference.read_text())
    return prefetch_convergence.run(output, core_reference, cpus, matrix=MATRIX,
        analyze=partial(summarize, before=baseline["r_rows"]), extra_references=(before, reference,
            *[Path(p["path"]) for p in frozen["source_contract"] + frozen["artifacts"]]),
        complete_status="GATHER_REUSE_COMPLETE_SIMULATOR_PREDICTION", prefetch_checks=True,
        extra_input_checks={"PREFETCH_CAPACITY_TEST": 16}, memory_profile=FRESH_CPU)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    for name in ("regraph", "before", "core-reference"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--cpus", type=int, nargs="+")
    args = parser.parse_args()
    if args.freeze:
        if args.regraph is None: parser.error("--regraph required")
        result = freeze(args.output.resolve(), args.reference.resolve(), args.regraph.resolve())
    else:
        if args.before is None or args.core_reference is None or args.cpus is None:
            parser.error("--before, --core-reference and --cpus required")
        result = run(args.output.resolve(), args.reference.resolve(), args.before.resolve(),
                     args.core_reference.resolve(), args.cpus)
    print(json.dumps({"status": result["status"]}))
