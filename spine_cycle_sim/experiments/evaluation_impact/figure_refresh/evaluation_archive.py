"""Package a specific admitted Fig. 7 checkpoint with the pinned controls and Figs. 8--11."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import tarfile

from . import review_bundle as frozen


HANDOFF = frozen.HANDOFF
MODULE = frozen.MODULE.with_name("evaluation_archive.py")
GUIDE = HANDOFF / "PORTABLE.md"
INDEX = "evaluation_archive_manifest.json"
RESIDENT = HANDOFF / "current_fpga"
OLD_RESIDENT = RESIDENT / "resident_checkpoint_v2"
CSV = "fig7_resident_checkpoint.csv"
RECEIPTS = "receipts.tar.gz"
CONTROLS = RESIDENT / "gr_controls.csv"
CC_DIRECT = RESIDENT / "cc_direct_board_v1"
CC_TABLE = CC_DIRECT / "data/fig7_cc.csv"
CC_MEASURED = "MEASURED_WITHOUT_RAW_SKEW_REPORT"
COMPLETE_CSV = HANDOFF / "fig7_complete.csv"
FRESH = HANDOFF / "fresh_simulator/fresh_summary.json"
ALGORITHMS = ("weighted_sssp", "cc", "residual_pagerank")
DATASETS = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
BOUNDARIES = {
    "weighted_sssp": "resident_update_to_final_readback_wall_including_host_relaunch",
    "cc": "resident_old_graph_host_pack_to_final_readback",
    "residual_pagerank": "resident_update_to_final_readback_wall_including_host_relaunch",
}


def resident_path(name):
    if not isinstance(name, str) or not re.fullmatch(r"resident_checkpoint_v[1-9][0-9]*", name):
        raise ValueError("select an explicit resident_checkpoint_vN directory")
    return RESIDENT / name


def selection(name, cc_direct=False):
    resident = resident_path(name)
    if cc_direct and name != "resident_checkpoint_v3":
        raise ValueError("direct CC preview is pinned to resident_checkpoint_v3")
    historical = {HANDOFF / "CURRENT.md", HANDOFF / "render_review.py"}
    paths = [MODULE, GUIDE, *(
        resident / path.relative_to(OLD_RESIDENT) if path.is_relative_to(OLD_RESIDENT) else path
        for path in frozen.selected_paths() if path not in historical
    )]
    if cc_direct:
        paths = [path for path in paths if path.parent != resident / "figures"]
        paths += [HANDOFF / "LATEST.md", COMPLETE_CSV, CC_DIRECT / "README.md",
                  CC_TABLE, CC_DIRECT / "data/scope.json", CC_DIRECT / "data/receipts.tar.gz",
                  CC_DIRECT / "figures/fig7_resident_checkpoint.png",
                  CC_DIRECT / "figures/fig7_resident_checkpoint.pdf",
                  RESIDENT / "README.md", resident / "README.md", FRESH.parent / "README.md",
                  FRESH.parent / "portable_fig8_headroom_v1/README.md"]
    return sorted(paths)


def receipt_digests(payload):
    seen, digests = set(), set()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r|gz") as archive:
        for member in archive:
            frozen.safe_name(member.name)
            if not member.isfile() or member.name in seen:
                raise ValueError("invalid or duplicate Fig. 7 receipt member: " + member.name)
            seen.add(member.name)
            with archive.extractfile(member) as stream:
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1 << 16), b""):
                    digest.update(chunk)
            digests.add(digest.hexdigest())
    return digests


def checkpoint(name, read):
    resident = resident_path(name)
    scope = json.loads(read(str(resident / "scope.json")))
    rows = list(csv.DictReader(io.StringIO(read(str(resident / CSV)).decode("utf-8"))))
    expected = {(algorithm, dataset) for algorithm in ALGORITHMS for dataset in DATASETS}
    keys = [(row["algorithm"], row["dataset"]) for row in rows]
    if len(keys) != len(expected) or set(keys) != expected or scope["expected_pairs"] != len(expected):
        raise ValueError("Fig. 7 must retain all twenty-four distinct slots")
    receipt_hashes = receipt_digests(read(str(resident / RECEIPTS)))
    outcomes = {label: [] for label in ("spine_wins", "gr_wins", "ties", "unmeasured")}
    fields = ("spine_wall_ms", "gr_wall_ms", "speedup_gr_over_spine")
    for (algorithm, dataset), row in zip(keys, rows, strict=True):
        case = dict(algorithm=algorithm, dataset=dataset)
        if row["status"] != "MEASURED":
            if not row["status"] or any(row.get(field) for field in fields):
                raise ValueError("unmeasured slot lacks a status or contains a timing")
            outcomes["unmeasured"].append(dict(case, status=row["status"]))
            continue
        spine, gr, ratio = (float(row[field]) for field in fields)
        if (row["boundary"] != BOUNDARIES[algorithm] or not re.fullmatch(r"[0-9a-f]{64}", row["receipt_sha256"])
                or not all(math.isfinite(value) and value > 0 for value in (spine, gr, ratio))
                or not math.isclose(gr / spine, ratio, rel_tol=1e-9, abs_tol=0)):
            raise ValueError("Fig. 7 timing, boundary or receipt pin is invalid")
        if row["receipt_sha256"] not in receipt_hashes:
            raise ValueError(f"Fig. 7 receipt not found in archive: {algorithm}/{dataset}")
        winner = "spine_wins" if gr > spine else "gr_wins" if spine > gr else "ties"
        outcomes[winner].append(dict(case, speedup_gr_over_spine=ratio))
    measured = len(expected) - len(outcomes["unmeasured"])
    if not measured:
        raise ValueError("Fig. 7 needs at least one admitted measurement")
    complete = measured == len(expected)
    status = "MEASURED_CURRENT_FPGA_MATRIX" if complete else "INCOMPLETE_CURRENT_FPGA_CHECKPOINT"
    if scope["measured_pairs"] != measured or scope["status"] != status:
        raise ValueError("Fig. 7 measured count or status differs from scope")
    controls = read(str(CONTROLS))
    pins = [entry for entry in scope["inputs"] if Path(entry["path"]).name == CONTROLS.name]
    if (len(pins) != 1 or pins[0]["sha256"] != frozen.digest(controls)
            or pins[0]["bytes"] != len(controls)):
        raise ValueError("Fig. 7 was not exported against these G/R controls")
    summary = json.loads(read(str(FRESH)))
    if (scope["publication_throughput_reproduced"] is not False
            or summary["fpga_stage_calibrated"] is not False or summary["no_holdout_used_for_fit"] is not True):
        raise ValueError("publication or simulator evidence boundary changed")
    return dict(status=status, fpga_pairs=measured, expected_fpga_pairs=len(expected),
                complete=complete, all_pairs_spine_wins=len(outcomes["spine_wins"]) == len(expected),
                fpga_stage_calibrated=False, publication_throughput_reproduced=False,
                simulator_executions=summary["executions"], **outcomes)


def combined_rows(name, read):
    """Overlay the completed CC campaign without rewriting its frozen checkpoint."""
    resident = resident_path(name)
    rows = list(csv.DictReader(io.StringIO(read(str(resident / CSV)).decode())))
    cc = list(csv.DictReader(io.StringIO(read(str(CC_TABLE)).decode())))
    scope = json.loads(read(str(CC_DIRECT / "data/scope.json")))
    if (len(cc) != 8 or {(row["algorithm"], row["dataset"]) for row in cc} != {
            ("cc", dataset) for dataset in DATASETS} or scope["measured_pairs"] != 8
            or scope["expected_pairs"] != 8 or scope["status"] != "MEASURED"
            or scope["routing_report_complete"] is not False):
        raise ValueError("direct CC overlay must retain eight qualified measurements")
    hashes = receipt_digests(read(str(CC_DIRECT / "data/receipts.tar.gz")))
    if any(pin["sha256"] not in hashes for pin in scope["raw_source_records"]):
        raise ValueError("direct CC source receipt missing from archive")
    controls = json.loads(read(str(RESIDENT / "gr_scope.json")))
    if scope["artifacts"]["gr_image"] not in controls["artifact_index"]:
        raise ValueError("direct CC image differs from G/R controls")
    lookup = {(row["algorithm"], row["dataset"]): row for row in rows}
    for row in cc:
        key = (row["algorithm"], row["dataset"])
        if lookup[key]["status"] == "MEASURED":
            raise ValueError("direct CC cannot replace a measured checkpoint sample")
        pair = scope["pairs"][row["dataset"]]
        spine, gr, ratio = (float(row[field]) for field in (
            "spine_wall_ms", "gr_wall_ms", "speedup_gr_over_spine"))
        if (row["status"] != CC_MEASURED or row["routing_report_complete"] != "False"
                or row["boundary"] != BOUNDARIES["cc"] or pair["boundary"] != row["boundary"]
                or not all(math.isfinite(value) and value > 0 for value in (spine, gr, ratio))
                or not math.isclose(gr / spine, ratio, rel_tol=1e-9)
                or (spine, gr, ratio) != (pair["spine_ms"], pair["gr_ms"], pair["gr_over_spine"])):
            raise ValueError("direct CC timing or qualification differs from exported scope")
        lookup[key] = row
    combined = [lookup[(algorithm, dataset)] for algorithm in ALGORITHMS for dataset in DATASETS]
    for row in combined:
        source = CC_TABLE if row["algorithm"] == "cc" else resident / CSV
        row["source_csv"] = str(source.relative_to(HANDOFF))
    return combined


def complete_csv(name, read):
    rows = combined_rows(name, read)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(dict.fromkeys(key for row in rows for key in row)),
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def selected_checkpoint(name, read, cc_direct=False):
    summary = checkpoint(name, read)
    if not cc_direct:
        return summary
    rows = combined_rows(name, read)
    if any(row["status"] not in ("MEASURED", CC_MEASURED) for row in rows):
        raise ValueError("complete selection still has unmeasured FPGA rows")
    outcomes = {label: [] for label in ("spine_wins", "gr_wins", "ties", "unmeasured")}
    for row in rows:
        ratio = float(row["speedup_gr_over_spine"])
        label = "spine_wins" if ratio > 1 else "gr_wins" if ratio < 1 else "ties"
        outcomes[label].append(dict(algorithm=row["algorithm"], dataset=row["dataset"],
                                    speedup_gr_over_spine=ratio))
    return dict(summary, status="MEASURED_CURRENT_FPGA_MATRIX", fpga_pairs=24, complete=True,
                all_pairs_spine_wins=len(outcomes["spine_wins"]) == 24,
                cc_routing_report_complete=False, **outcomes)


def verify(read, names=None):
    manifest = json.loads(read(INDEX))
    if manifest.get("schema") != "evaluation-archive-v1":
        raise ValueError("unsupported evaluation archive")
    cc_direct = manifest.get("cc_direct", False)
    if not isinstance(cc_direct, bool):
        raise ValueError("CC selection must be explicit boolean")
    expected = [str(path) for path in selection(manifest["resident_checkpoint"], cc_direct)]
    members = manifest["members"]
    if [row["path"] for row in members] != expected or (
            names is not None and names != {INDEX, *expected}):
        raise ValueError("archive inventory differs from selection")
    for row in members:
        payload = read(row["path"])
        if len(payload) != row["bytes"] or frozen.digest(payload) != row["sha256"]:
            raise ValueError("changed evaluation member: " + row["path"])
    if cc_direct and read(str(COMPLETE_CSV)) != complete_csv(manifest["resident_checkpoint"], read):
        raise ValueError("combined Fig. 7 CSV differs from its source tables")
    if selected_checkpoint(manifest["resident_checkpoint"], read, cc_direct) != manifest["checkpoint"]:
        raise ValueError("archive summary differs from selected evidence")
    return manifest


def verify_archive(path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        if len(names) != len(members) or INDEX not in names:
            raise ValueError("duplicate members or missing manifest")
        for member in members:
            frozen.safe_name(member.name)
            if not member.isfile():
                raise ValueError("archive contains non-file member")
        return verify(lambda name: archive.extractfile(name).read(), names)


def read_file(root, name):
    path = root / name
    if not path.is_file() or path.resolve() != path:
        raise ValueError("not a regular source inside the review root: " + name)
    return path.read_bytes()


def build(root, name, destination, cc_direct=False):
    paths = selection(name, cc_direct)
    root = root.resolve()
    payloads = {str(path): read_file(root, str(path)) for path in paths
                if not (cc_direct and path == COMPLETE_CSV)}
    if cc_direct:
        payloads[str(COMPLETE_CSV)] = complete_csv(name, payloads.__getitem__)
        payloads = dict(sorted(payloads.items()))
    manifest = dict(schema="evaluation-archive-v1", resident_checkpoint=name,
                    checkpoint=selected_checkpoint(name, payloads.__getitem__, cc_direct),
                    members=[dict(path=path, bytes=len(blob), sha256=frozen.digest(blob))
                             for path, blob in payloads.items()])
    if cc_direct:
        manifest["cc_direct"] = True
    index = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("ascii")
    with destination.open("xb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path, payload in [(INDEX, index), *payloads.items()]:
                    member = tarfile.TarInfo(path)
                    member.size, member.mode = len(payload), 0o644
                    archive.addfile(member, io.BytesIO(payload))
    return verify_archive(destination)


def render(root, output):
    root = root.resolve()
    manifest = verify(lambda name: read_file(root, name))
    handoff = root / HANDOFF
    sys.path.insert(0, str(handoff))
    try:
        import render as style
        import render_current as current
    finally:
        sys.path.pop(0)

    output.mkdir(parents=True, exist_ok=False)
    reference = style.prior_renderer()
    reference.configure_matplotlib()
    current.draw(current.checked_rows(root / CONTROLS), output)
    current.draw_resident(root / resident_path(manifest["resident_checkpoint"]) / CSV, output,
                          root / CC_TABLE if manifest.get("cc_direct") else None)
    style.fig8_headroom(output)
    fresh = root / FRESH.parent
    style.fig9(output, fresh, "fig9_memory_hbm_prediction", fresh=True)
    style.fig10(output, reference, fresh)
    style.fig11(output, fresh)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    package = commands.add_parser("build")
    package.add_argument("--resident", required=True)
    package.add_argument("--cc-direct", action="store_true",
                         help="include the completed direct CC overlay without changing the checkpoint")
    package.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("archive", type=Path)
    redraw = commands.add_parser("render")
    redraw.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        result = build(Path.cwd(), args.resident, args.output, args.cc_direct)
    elif args.command == "verify":
        result = verify_archive(args.archive)
    else:
        result = render(Path.cwd(), args.output)
    print(json.dumps(result["checkpoint"], indent=2))


if __name__ == "__main__":
    main()
