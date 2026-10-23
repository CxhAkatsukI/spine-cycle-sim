"""Seal dense/sparse ResPR controls without rewriting preceding evidence."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from . import apply_equivalence, delivery, propagation_followup, tables
from .residual_followup import record


STATUS = "COMPLETE_SIMULATOR_SPARSE_RESIDUAL_APPLY_DIAGNOSTIC"


def arm_name(row, arm):
    return Path(row[arm]["evidence"]).name


def trajectory(read, row):
    rows = csv.DictReader(io.StringIO(read("matrix/" + arm_name(row, "spine") + "/rounds.csv").decode()))
    return [(int(r["active_in"]), int(r["active_out"])) for r in rows]


def compare(old, dense, sparse, old_read, dense_read, sparse_read):
    if old["matrix"] != dense["matrix"] or dense["matrix"] != sparse["matrix"]:
        raise ValueError("identical predeclared inputs required for all three controls")
    dense_model, sparse_model = dict(dense["model"]), dict(sparse["model"])
    if (dense_model.pop("spine_residual_apply") != "dense" or
            sparse_model.pop("spine_residual_apply") != "dirty-bitmap"):
        raise ValueError("explicit dense and dirty-bitmap controls required")
    for model in (dense_model, sparse_model):
        model.pop("apply_evidence")
    if dense_model != sparse_model:
        raise ValueError("non-Apply model settings changed")
    results = []
    for case, previous, control, candidate in zip(dense["matrix"], old["rows"], dense["rows"], sparse["rows"]):
        if len({r["dataset"] for r in (previous, control, candidate)}) != 1:
            raise ValueError("control row order changed")
        for arm in ("spine", "gr"):
            for field in ("cycles", "rounds", "read_bytes", "write_bytes", "energy_pj", "state_hashes"):
                if previous[arm][field] != control[arm][field]:
                    raise ValueError("default dense control changed: " + arm + ":" + field)
                if arm == "gr" and control[arm][field] != candidate[arm][field]:
                    raise ValueError("G+R changed during the Spine-only optimization")
            for state in ("old_state", "expected", "final", "residual"):
                def state_bytes(read, row):
                    return read("matrix/" + arm_name(row, arm) + "/" + state + ".u32le")
                before = state_bytes(old_read, previous)
                current = state_bytes(dense_read, control)
                after = state_bytes(sparse_read, candidate)
                if before != current:
                    raise ValueError("default dense full numerical state changed")
                if arm == "spine" and state == "residual":
                    residual = apply_equivalence.residual_comparison(current, after,
                        dense["model"]["residual_epsilon"], case["vertices"])
                elif current != after:
                    raise ValueError("full numerical state differs between controls")
        if not (trajectory(old_read, previous) == trajectory(dense_read, control) == trajectory(sparse_read, candidate)):
            raise ValueError("Spine frontier trajectory changed")
        frontier = apply_equivalence.frontier_comparison(dense_read, sparse_read, control, candidate, case["vertices"])
        trace = {}
        for name, read, row in (("dense", dense_read, control), ("sparse", sparse_read, candidate)):
            text = read("matrix/raw/" + arm_name(row, "spine") + ".stdout.txt").decode()
            trace[name] = record(text, "APPLY_TRACE ")
            propagation = record(text, "PROPAGATION_TRACE ")
            if propagation["computed_edges"] <= 0 or propagation["nonempty_rounds"] <= 0:
                raise ValueError("nonempty propagation required, not a zero-active shortcut")
            if name == "sparse" and (trace[name]["bitmap_marks"] != propagation["computed_edges"] or
                    trace[name]["dense_fallback_tiles"] != 0):
                raise ValueError("sink-free candidate bitmap work did not conserve reductions")
        t = trace["sparse"]
        if (trace["dense"]["dirty_bitmap"] != 0 or t["dirty_bitmap"] != 1 or
                not 0 < t["bitmap_storage_bytes"] <= 8192 or
                min(t["bitmap_clear_cycles"], t["bitmap_read_cycles"], t["bitmap_marks"]) <= 0 or
                not 0 < t["vertices_applied"] == t["sparse_vertices_applied"] < trace["dense"]["vertices_applied"]):
            raise ValueError("finite timed bitmap and actual Apply-work reduction required")
        results.append(dict(dataset=control["dataset"],
            dense_spine_cycles=control["spine"]["cycles"], sparse_spine_cycles=candidate["spine"]["cycles"],
            gr_cycles=control["gr"]["cycles"],
            dense_speedup_gr_over_spine=control["gr"]["cycles"] / control["spine"]["cycles"],
            sparse_speedup_gr_over_spine=candidate["gr"]["cycles"] / candidate["spine"]["cycles"],
            spine_improvement=control["spine"]["cycles"] / candidate["spine"]["cycles"],
            dense_vertices_applied=trace["dense"]["vertices_applied"], **{"sparse_" + k: v for k, v in t.items()},
            dense_spine_bytes=control["spine"]["read_bytes"] + control["spine"]["write_bytes"],
            sparse_spine_bytes=candidate["spine"]["read_bytes"] + candidate["spine"]["write_bytes"],
            dense_byte_ratio=control["accepted_bytes_ratio"], sparse_byte_ratio=candidate["accepted_bytes_ratio"],
            dense_hbm_energy_ratio=control["hbm_energy_ratio"], sparse_hbm_energy_ratio=candidate["hbm_energy_ratio"],
            full_rank_words_identical=True, **residual, **frontier,
            frontier_count_trajectory_identical=True, gr_unchanged=True))
    return dict(status=STATUS, baseline_admitted=False, evidence="simulator-only architecture candidate, not routed HLS",
        dense_default_equivalent=True, model=sparse["model"], rows=results)


def summarize(read):
    old_archive = read("before/evidence.tar.gz")
    index = json.loads(read("before/index.json"))
    if hashlib.sha256(old_archive).hexdigest() != index["sha256"]:
        raise ValueError("preceding frozen package identity changed")
    with tarfile.open(fileobj=io.BytesIO(old_archive)) as handle:
        old_read = delivery.checked_archive(handle, index)
        old = json.loads(old_read("matrix/results.json"))
        propagation_followup.summarize(old, json.loads(old_read("core-gates/results.json")), old_read)
        reports, readers = {}, {}
        for mode in ("dense", "sparse"):
            def scoped(name, mode=mode):
                return read(name if name.startswith("core-gates/") else mode + "/" + name)
            readers[mode] = scoped
            reports[mode] = json.loads(scoped("matrix/results.json"))
            propagation_followup.summarize(reports[mode], json.loads(read("core-gates/results.json")),
                                           scoped, expected_core_tests=40)
        return compare(old, reports["dense"], reports["sparse"], old_read, readers["dense"], readers["sparse"])


def package(output, dense, sparse, core, before, initial):
    if output.exists() or dense.parent.name != "matrix" or sparse.parent.name != "matrix" or core.parent.name != "core-gates":
        raise ValueError("fresh output and named matrix/core-gates reports required")
    files = {"before/evidence.tar.gz": before / "evidence/evidence.tar.gz", "before/index.json": before / "evidence/index.json",
             "analysis/sparse_apply_followup.py": Path(__file__)}
    for name in ("apply_equivalence.py", "propagation_followup.py", "validation.py"):
        files["analysis/" + name] = Path(__file__).with_name(name)
    directories = [("dense/matrix", dense.parent), ("sparse/matrix", sparse.parent), ("core-gates", core.parent)]
    directories += [("initial/" + name, initial / name) for name in ("core-gates", "dense/matrix", "sparse/matrix")]
    for prefix, directory in directories:
        report = json.loads((directory / "results.json").read_text())
        if report["status"].startswith("RUNNING"):
            raise ValueError("running evidence cannot be sealed")
        for path in directory.rglob("*"):
            if path.is_file() and "build" not in path.relative_to(directory).parts and path.suffix in (".json", ".csv", ".txt", ".gz", ".u32le"):
                if path.is_symlink():
                    raise ValueError("symlink evidence rejected")
                files[prefix + "/" + str(path.relative_to(directory))] = path
        if prefix in ("dense/matrix", "sparse/matrix"):
            for case in report["matrix"]:
                for key in ("graph", "update_file", "manifest"):
                    path = Path(case[key])
                    files[prefix.split("/")[0] + "/inputs/" + sha256_file(path)] = path
    summary = summarize(lambda name: files[name].read_bytes())
    (output / "data").mkdir(parents=True)
    (output / "evidence").mkdir()
    atomic_write_json(output / "data/summary.json", summary)
    (output / "data/before_after.csv").write_bytes(tables.csv_bytes(summary["rows"]))
    files.update({"data/" + p.name: p for p in (output / "data").iterdir()})
    archive = output / "evidence/evidence.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(files.items()):
            handle.add(path, arcname=name, recursive=False)
    atomic_write_json(output / "evidence/index.json", dict(status=STATUS, archive=archive.name, sha256=sha256_file(archive),
        members=[dict(path=n, bytes=p.stat().st_size, sha256=sha256_file(p)) for n, p in sorted(files.items())],
        external="Compiler, SST, DRAMSim3, linked binaries and the pre-edit git source archive are external pinned dependencies."))
    return verify(output)


def verify(output):
    index = json.loads((output / "evidence/index.json").read_text())
    archive = output / "evidence/evidence.tar.gz"
    if index["archive"] != archive.name or sha256_file(archive) != index["sha256"]:
        raise ValueError("sparse Apply archive identity changed")
    with tarfile.open(archive) as handle:
        read = delivery.checked_archive(handle, index)
        summary = summarize(read)
        for name, expected in (("summary.json", None), ("before_after.csv", tables.csv_bytes(summary["rows"]))):
            archived = read("data/" + name)
            if (output / "data" / name).read_bytes() != archived or (
                    json.loads(archived) != summary if expected is None else archived != expected):
                raise ValueError("export differs from raw dense/sparse comparison")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    for name in ("dense", "sparse", "core", "before", "initial"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if not args.verify and any(getattr(args, k) is None for k in ("dense", "sparse", "core", "before", "initial")):
        parser.error("packaging requires --dense, --sparse, --core, --before and --initial")
    result = verify(args.output) if args.verify else package(args.output, args.dense, args.sparse, args.core, args.before, args.initial)
    print(json.dumps(dict(status=result["status"], sha256=result["sha256"])))
