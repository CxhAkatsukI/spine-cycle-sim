"""Validate a fresh pair using the qualified correction host, without rerunning it."""

import json
from pathlib import Path

from . import correction_matrix, correction_retime, dual_clock_resident, host_correction
from . import resident_board as board
from .follow import unchanged
from .runtime import identity


def validate_result(path, args, dataset):
    report, gate, pins = correction_retime.reference(path, args.comparator)
    qualified = host_correction.admit(args.qualification, args.spine_host)
    row = report["row"]
    if (report["dataset"], report["case"]["dataset"], row["case"], row["status"],
            report.get("qualification"), report.get("spine_host_mode"),
            report.get("fresh_samples"), report.get("gr_sample_reused"),
            report["original_artifacts"]["spine_host"], report["pins"]["spine_host"],
            report["original_artifacts"]["spine_image"]["sha256"],
            [attempt["arm"] for attempt in row["attempts"]]) != (
            dataset, dataset, report["case"], "MEASURED", identity(args.qualification),
            dual_clock_resident.QUALIFIED_HOST, dict(spine=1, gr=1), False,
            identity(args.spine_host), identity(args.spine_host), board.SPINE_IMAGE_SHA256,
            ["spine", "gr"]):
        raise ValueError("fresh resident pair differs from its qualified host or declared sample scope")
    raw_pair = json.loads(Path(row["comparison_log"]["path"]).read_text())
    if row["pair"] != correction_matrix.pair_with_scope(raw_pair, report["case"]):
        raise ValueError("fresh resident pair analysis changed")
    correction = host_correction.validate_correction_log(
        Path(row["rows"]["spine"]["stdout"]["path"]).read_text())
    if report["correction"] != correction:
        raise ValueError("fresh resident pair changed its correction scope")
    unchanged([*pins, *qualified])
    return dict(status=dual_clock_resident.MEASURED, result=identity(path),
                pair=row["pair"], correction=correction, report=report,
                profile_mhz=gate["resident_mhz"])
