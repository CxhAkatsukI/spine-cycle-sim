"""Verify an archived board delivery and reproduce it outside all checkouts."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def normalize_txtt_subset(data):
    # Matplotlib's subset tag is randomized; no drawing or font bytes may differ.
    tags = re.findall(rb"/[A-Z]{6}\+txtt\b", data)
    if len(tags) != 3 or len(set(tags)) != 1:
        raise ValueError("unexpected TX Typewriter subset structure")
    return data.replace(tags[0], b"/SUBSET+txtt")


def review_pdf(original, repeated, output):
    decoded = []
    rasters = []
    for label, path in (("original", original), ("reproduced", repeated)):
        target = output / (label + "-decompressed.pdf")
        subprocess.run(["mutool", "clean", "-d", str(path), str(target)],
                       capture_output=True, check=True, timeout=30)
        decoded.append(normalize_txtt_subset(target.read_bytes()))
        raster = output / (label + "-pdf.png")
        subprocess.run(["mutool", "draw", "-q", "-r", "300", "-o", str(raster), str(path)],
                       capture_output=True, check=True, timeout=30)
        rasters.append(digest(raster))
    if decoded[0] != decoded[1] or rasters[0] != rasters[1]:
        raise ValueError("PDF differs beyond its randomized txtt subset tag")
    return {"equal_after_only_txtt_subset_tag_normalization": True,
            "normalized_decompressed_sha256": hashlib.sha256(decoded[0]).hexdigest(),
            "raster_300dpi_byte_identical": True, "raster_sha256": rasters[0],
            "original_sha256": digest(original), "reproduced_sha256": digest(repeated)}


def review(package, output):
    package = package.resolve(strict=True)
    output = output.resolve()
    if output.exists() or output.is_relative_to(package):
        raise ValueError("use a fresh review directory outside the package")
    manifest = json.loads((package / "manifest.json").read_text())
    if manifest["passed_cases"] != 24 or manifest["paired_runs"] != 96:
        raise ValueError("the final review requires all 24 cases and 96 paired runs")
    records = manifest["archive_members"]
    expected = {row["path"]: row for row in records}
    if len(expected) != len(records) or sum(row["bytes"] for row in records) > 256 * 1024**2:
        raise ValueError("duplicate or oversized archive index")
    archive = package / manifest["archive"]["path"]
    if digest(archive) != manifest["archive"]["sha256"]:
        raise ValueError("archive hash mismatch")
    for row in manifest["readable_artifacts"]:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe readable-artifact path")
        path = package / relative
        if path.is_symlink() or path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError("changed readable artifact: " + str(relative))
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        if len(members) != len(expected) or {member.name for member in members} != set(expected):
            raise ValueError("archive member set differs from index")
        for member in members:
            relative, row = Path(member.name), expected[member.name]
            if relative.is_absolute() or ".." in relative.parts or not member.isfile() or \
                    member.size != row["bytes"]:
                raise ValueError("unsafe or changed archive member: " + member.name)
            with stream.extractfile(member) as payload:
                if hashlib.file_digest(payload, "sha256").hexdigest() != row["sha256"]:
                    raise ValueError("archive payload hash mismatch: " + member.name)
        output.mkdir(parents=True)
        stream.extractall(output / "unpacked", filter="data")
    environment = os.environ | {"PYTHONPATH": str(package / "code")}
    commands = []

    def run(arguments):
        result = subprocess.run(arguments, cwd=output, env=environment, capture_output=True,
                                text=True, check=True, timeout=600)
        commands.append({"command": arguments, "cwd": str(output), "exit_code": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})

    run([sys.executable, "-c", (
        "import sys; from pathlib import Path; from board_review import fpga_plot, fpga_profile; "
        "assert 'spine_cycle_sim' not in sys.modules; "
        "root=Path(sys.argv[1]); "
        "assert all(Path(m.__file__).is_relative_to(root) for m in (fpga_plot, fpga_profile))"
    ), str(package / "code")])
    evidence = output / "unpacked/evidence"
    for name, module in (("figure", "fpga_plot"), ("profile", "fpga_profile")):
        run([sys.executable, "-m", "board_review." + module,
             "--delivery", str(evidence), "--output", str(output / name)])
    names = ("figure/fpga_speedup.png", "profile/profile_medians.csv",
             "profile/wall_variability.csv", "profile/README.md")
    for name in names:
        if digest(package / name) != digest(output / name):
            raise ValueError("nonidentical reproduction: " + name)
    pdf_review = review_pdf(package / "figure/fpga_speedup.pdf",
                            output / "figure/fpga_speedup.pdf", output)
    for name in ("figure/provenance.json", "profile/profile.json"):
        original = json.loads((package / name).read_text())
        repeated = json.loads((output / name).read_text())
        if repeated.pop("source") != str(evidence) or original.pop("source") == str(evidence) or \
                original != repeated:
            raise ValueError("numerical/provenance reproduction mismatch: " + name)
    fonts = subprocess.run(["pdffonts", str(output / "figure/fpga_speedup.pdf")],
                           capture_output=True, text=True, check=True, timeout=30)
    report = {"status": "AUTOMATED_ROUNDTRIP_PASS_VISUAL_REVIEW_PENDING", "passed_cases": 24,
              "paired_runs": 96, "archive_members": len(records), "commands": commands,
              "isolated_import": True, "byte_identical_artifacts": list(names),
              "pdf_review": pdf_review,
              "normalized_json_equal_except_source_path": True, "pdf_fonts": fonts.stdout,
              "package_manifest_sha256": digest(package / "manifest.json"),
              "archive_sha256": digest(archive), "reviewer_sha256": digest(Path(__file__))}
    (output / "review.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "archive_members": len(records),
                      "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    review(args.package, args.output)
