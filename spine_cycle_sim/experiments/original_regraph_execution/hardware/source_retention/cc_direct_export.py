"""Package the direct CC campaign without rerunning a board or filling failures."""

import argparse
import csv
import gzip
import io
import json
from pathlib import Path
import tarfile

from . import cc_resident_results, clocks
from .active_min_resident import DATASETS
from .runtime import identity, save


MEASURED = "MEASURED_WITHOUT_RAW_SKEW_REPORT"
FIELDS = ("algorithm", "dataset", "status", "vertices", "initial_edges", "logical_insertions",
          "physical_updates", "boundary", "spine_wall_ms", "gr_wall_ms", "speedup_gr_over_spine",
          "spine_rounds", "gr_rounds", "fresh_spine_samples", "fresh_gr_samples", "gr_sample_reused",
          "spine_hot_layout", "spine_data_mhz", "spine_kernel_mhz", "spine_hbm_mhz",
          "gr_data_mhz", "gr_kernel_mhz", "gr_hbm_mhz", "routing_report_complete", "error")


def measured(dataset, case, arms, bdf, artifacts, *, reused=False):
    if case["updates"] != 16:
        raise ValueError("expected eight reciprocal insertions")
    logs = {name: Path(arm["stdout"]["path"]).read_text() for name, arm in arms.items()}
    pair = cc_resident_results.analyze(case, logs["gr"], logs["spine"], bdf=bdf)
    row = dict(algorithm="cc", dataset=dataset, status=MEASURED, vertices=case["vertices"],
               initial_edges=case["edges"], logical_insertions=8, physical_updates=case["updates"],
               boundary=pair["boundary"], spine_wall_ms=pair["spine_ms"], gr_wall_ms=pair["gr_ms"],
               speedup_gr_over_spine=pair["gr_over_spine"], spine_rounds=pair["spine_rounds"],
               gr_rounds=pair["gr_supersteps"], fresh_spine_samples=1,
               fresh_gr_samples=0 if reused else 1, gr_sample_reused=reused,
               spine_hot_layout=pair["spine_hot_layout"], routing_report_complete=False)
    for name, arm in arms.items():
        observed = clocks.replay(arm["clock_evidence"])
        if observed["bdf"] != bdf or observed["binary"] != artifacts[name + "_image"]:
            raise ValueError("CC sample uses a different board or image")
        row.update(zip((name + "_" + key + "_mhz" for key in ("data", "kernel", "hbm")),
                       observed["driver_reported_mhz"][:3]))
    return row, pair


def _attempts(matrix_path, matrix, resume_path):
    attempts = [(matrix_path, matrix)]
    cases = dict(matrix["cases"])
    paths = (resume_path,) if isinstance(resume_path, Path) else (resume_path or ())
    for path in paths:
        resumed = json.loads(path.read_text())
        if (resumed["status"] not in (MEASURED, "COMPLETED_WITH_FAILURES")
                or not resumed["cases"] or not set(resumed["cases"]) <= set(cases)):
            raise ValueError("resume must be a terminal subset of the original CC matrix")
        for key in ("artifacts", "boundary", "bdf", "repetitions_per_arm", "warmups", "memory_profile"):
            if resumed[key] != matrix[key]:
                raise ValueError("resume changed comparison configuration: " + key)
        for dataset, row in resumed["cases"].items():
            original = cases[dataset]
            if original["status"] != "FAILED":
                raise ValueError("resume cannot replace an already measured sample")
            if any(row[key] != original[key] for key in ("case", "inputs")):
                raise ValueError("resume changed the original workload")
            if row["status"] not in (MEASURED, "FAILED"):
                raise ValueError("resume contains a nonterminal case")
            cases[dataset] = row
        attempts.append((path, resumed))
    return cases, attempts


def collect(matrix_path, au_path, au_gr_path, *, resume_path=None):
    matrix, au, reference = (json.loads(path.read_text()) for path in (matrix_path, au_path, au_gr_path))
    if (matrix["status"] not in (MEASURED, "COMPLETED_WITH_FAILURES")
            or set(matrix["cases"]) != set(DATASETS) - {"AU"}
            or matrix["repetitions_per_arm"] != 1 or matrix["warmups"] != 0):
        raise ValueError("a terminal seven-case, one-sample matrix is required")
    if au["execution"]["exit_code"] != 0 or reference["dataset"] != "AU":
        raise ValueError("AU must use the completed new Spine and named retained G+R sample")
    if any(au["workload"][key] != reference["case"][key] for key in ("vertices", "edges", "updates")):
        raise ValueError("AU workloads differ")
    cases, attempts = _attempts(matrix_path, matrix, resume_path)
    au_arms = dict(spine=dict(stdout=au["stdout"], clock_evidence=au["clock_evidence"]),
                   gr=reference["arms"]["gr"])
    rows, pairs = [], {}
    for dataset in DATASETS:
        if dataset == "AU":
            case, arms, reused = au["workload"], au_arms, True
        else:
            record = cases[dataset]
            if record["status"] == "FAILED":
                rows.append(dict(algorithm="cc", dataset=dataset, status="FAILED",
                                 routing_report_complete=False, error=record["error"]))
                continue
            if record["status"] != MEASURED:
                raise ValueError("nonterminal case in terminal matrix")
            case, arms, reused = record["case"], record["arms"], False
        row, pair = measured(dataset, case, arms, matrix["bdf"], matrix["artifacts"], reused=reused)
        if dataset != "AU" and pair != cases[dataset]["comparison"]:
            raise ValueError("CC summary differs from raw program output")
        rows.append(row)
        pairs[dataset] = pair
    scope = dict(status="MEASURED" if len(pairs) == 8 else "COMPLETED_WITH_FAILURES",
                 measured_pairs=len(pairs), expected_pairs=8, boundary=matrix["boundary"],
                 bdf=matrix["bdf"], repetitions_per_arm=1, warmups=0, artifacts=matrix["artifacts"],
                 raw_source_records=[identity(path) for path in
                                     (au_path, au_gr_path, *(path for path, _ in attempts))],
                 pairs=pairs, routing_report_complete=False, memory_profile=matrix["memory_profile"],
                 memory_peak_bytes=max(record["memory_peak_bytes"] for _, record in attempts),
                 attempts=[dict(source=identity(path), status=record["status"],
                                datasets=list(record["cases"]),
                                arm_timeout_seconds=record.get("arm_timeout_seconds", 1800),
                                memory_peak_bytes=record["memory_peak_bytes"],
                                memory_events=record["memory_events"])
                           for path, record in attempts],
                 limitations=["Spine raw routed bus-skew report unavailable; board times are measured",
                              "AU reuses the named same-image G+R sample; other arms are newly measured",
                              "Initial graph loading and old-graph convergence are outside the window",
                              "Historical case gr_binary/expected_pins are not current artifact identities; use artifacts and actual arm commands"])
    return rows, scope


def export(matrix_path, au_path, au_gr_path, output, *, resume_path=None):
    rows, scope = collect(matrix_path, au_path, au_gr_path, resume_path=resume_path)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "fig7_cc.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    # Preserve only small receipts/logs; state dumps, graph data and binaries stay external.
    members = {}
    roots = [("remaining", matrix_path.parent), ("au", au_path.parent)]
    paths = (resume_path,) if isinstance(resume_path, Path) else (resume_path or ())
    roots.extend((f"retry-{index}", path.parent) for index, path in enumerate(paths, 1))
    for prefix, root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.stat().st_size <= 8 * 2**20 and (
                    path.suffix == ".json" or path.suffix == ".txt" and path.name != "gr-state.txt"):
                members[prefix + "/" + str(path.relative_to(root))] = path
    reference = json.loads(au_gr_path.read_text())
    members["au-gr/results.json"] = au_gr_path
    gr = reference["arms"]["gr"]
    for pin in (gr["stdout"], gr["stderr"], gr["clock_evidence"]["record"],
                gr["clock_evidence"]["expected"]["info"], gr["clock"]["raw"]):
        path = Path(pin["path"])
        members["au-gr/" + path.name] = path
    for dataset, case in json.loads(matrix_path.read_text())["cases"].items():
        if "inputs" in case:
            members["inputs/" + dataset.lower() + ".json"] = Path(case["inputs"])
    scope["archive_members"] = {name: identity(path) for name, path in members.items()}
    save(output / "scope.json", scope)
    with (output / "receipts.tar.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for name, path in sorted(members.items()):
                    raw = path.read_bytes()
                    info = tarfile.TarInfo(name)
                    info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
    return rows, scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("matrix", "au", "au-gr", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--resume", type=Path, action="append",
                        help="ordered terminal retry; repeat to retain attempts; measured samples cannot be replaced")
    args = parser.parse_args()
    export(args.matrix, args.au, args.au_gr, args.output, resume_path=args.resume)


if __name__ == "__main__":
    main()
