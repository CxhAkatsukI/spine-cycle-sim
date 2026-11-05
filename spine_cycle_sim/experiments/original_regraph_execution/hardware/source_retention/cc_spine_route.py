"""Validate a replacement Spine CC FPGA image and its host."""

import json
import os
from pathlib import Path
import re

from . import spine_cc_warm_receipt as warm
from .follow import unchanged
from .runtime import identity


def candidate_route(spec):
    files = {key: spec[key] for key in ("host", "image", "manifest", "link", "timing", "skew")}
    unchanged(list(files.values()))
    host, image = (Path(files[key]["path"]) for key in ("host", "image"))
    manifest, link, timing, skew = (Path(files[key]["path"]).read_text()
                                    for key in ("manifest", "link", "timing", "skew"))
    if not os.access(host, os.X_OK) or Path(str(image) + ".weighted-manifest") != Path(files["manifest"]["path"]):
        raise ValueError("candidate image and host must have their own hardware manifest")
    expected = {f"build_sha256 {spec['abi']}", f"image_sha256 {files['image']['sha256']}", "target hw"}
    if not expected <= set(manifest.splitlines()) or files["image"]["sha256"] == warm.IMAGE_SHA256:
        raise ValueError("candidate manifest does not pin a new hardware image")
    linked_image = Path(spec["linked_image"])
    lines = link.splitlines()
    created = f"INFO: [v++ 60-586] Created {linked_image}"
    completed = "INFO: [v++ 60-1307] Run completed. Additional information can be found in:"
    if (not linked_image.is_absolute() or linked_image.name != image.name
            or created not in lines or completed not in lines or lines.index(created) >= lines.index(completed)):
        raise ValueError("Vitis link did not complete for the declared hardware image")
    summary = skew.rsplit("\n2. Bus Skew Report Per Constraint", 1)[0]
    slacks = re.findall(r"^\s*(?:Slow|Fast)(?:\s+[-.\d]+){2}\s+([-.\d]+)\s*$", summary, re.MULTILINE)
    if ("All user specified timing constraints are met." not in timing
            or not slacks or min(map(float, slacks)) < 0):
        raise ValueError("candidate route did not close timing and bus skew")
    unchanged(list(files.values()))
    return files


def pinned_arg(path_and_sha):
    path, sha = path_and_sha
    pin = identity(path)
    if pin["sha256"] != sha:
        raise ValueError(f"declared SHA-256 does not match {path}")
    return pin


def matrix_route(pin):
    unchanged([pin])
    spec = json.loads(Path(pin["path"]).read_text())
    abi = spec["abi"]
    files = candidate_route(spec)
    build = spec["build"]
    unchanged([pin, build])
    log = Path(build["path"]).read_text()
    if (not re.fullmatch(r"[0-9a-f]{64}", abi) or f"SPINE_WEIGHTED_BUILD_SHA256='\"{abi}\"'" not in log
            or f"--expected {abi}" not in log):
        raise ValueError("the captured make log does not bind host and link to the same source ABI")
    unchanged([pin, build])
    return abi, dict(files, build=build)
