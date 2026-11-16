#!/usr/bin/env python3
"""Join verified LJ08 FPGA samples to the frozen software results."""

import csv
import sys


def keyed(rows):
    result = {}
    for row in rows:
        share = int(row["deletion_pct"])
        if share in result:
            raise ValueError(f"duplicate deletion share: {share}")
        result[share] = row
    return result


def main(board_path, software_path, manifest_path):
    with open(board_path, newline="") as stream:
        board = keyed(csv.DictReader(stream))
    with open(software_path, newline="") as stream:
        software = keyed(
            row for row in csv.DictReader(stream)
            if (row["graph"], row["algorithm"], row["batch_size"], row["sssp_source"])
            == ("LJ08", "SSSP", "512", "26")
        )
    with open(manifest_path, newline="") as stream:
        inputs = keyed(csv.DictReader(stream, delimiter="\t"))

    expected = {0, 25, 50, 75, 100}
    if set(software) != expected or set(inputs) != expected or not set(board) <= expected:
        raise ValueError("unexpected LJ08 deletion shares")
    frozen_fields = {
        "graph_sha256": "base_bin_sha256",
        "batch_sha256": "batch_sha256",
        "before_state_sha256": "oracle_before_sha256",
        "after_state_sha256": "oracle_after_sha256",
    }
    software_fields = ("ligra_I_median_ms", "ligra_R_median_ms",
                       "gunrock_I_median_ms", "gunrock_R_median_ms")
    fields = ("deletion_pct", "deletions", "insertions", "delta_wall_ms",
              "delta_publication_ms", *software_fields, "batch_sha256")
    rows = []
    for share, fpga in sorted(board.items()):
        reference, source = software[share], inputs[share]
        for old, frozen in frozen_fields.items():
            if not source[frozen] or source[frozen] != reference[old]:
                raise ValueError(f"{share}%: different input fingerprint ({old})")
        for key in ("deletions", "insertions"):
            if int(fpga[key]) != int(source[key]):
                raise ValueError(f"{share}%: unexpected count for {key}")
        rows.append({
            "deletion_pct": share, "deletions": fpga["deletions"],
            "insertions": fpga["insertions"], "delta_wall_ms": fpga["wall_ms"],
            "delta_publication_ms": fpga["publication_ms"],
            **{field: reference[field] for field in software_fields},
            "batch_sha256": source["batch_sha256"],
        })
    writer = csv.DictWriter(sys.stdout, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main(*sys.argv[1:])
