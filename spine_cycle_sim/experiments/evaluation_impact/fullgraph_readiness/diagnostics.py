"""Admit only the reviewed OpenCL header-rename compiler note."""

import json
from pathlib import Path

RENAME_MESSAGE = ("'#pragma message: cl2.hpp has been renamed to opencl.hpp to make it clear that it "
                  "supports all versions of OpenCL. Please include opencl.hpp directly.'")


def review(stdout, stderr):
    if stdout.strip():
        raise ValueError("unexpected host compilation stdout")
    try:
        records = json.loads(stderr)
    except (TypeError, ValueError) as error:
        raise ValueError("structured compiler diagnostics required") from error
    if not isinstance(records, list) or len(records) > 1:
        raise ValueError("unexpected host compilation diagnostics")
    for record in records:
        if (not isinstance(record, dict) or record.get("kind") != "note" or
                record.get("message") != RENAME_MESSAGE or record.get("children") != []):
            raise ValueError("unreviewed host compilation diagnostic")
        locations = record.get("locations")
        if not isinstance(locations, list) or len(locations) != 1 or not isinstance(locations[0], dict):
            raise ValueError("OpenCL rename note location required")
        caret = locations[0].get("caret", {})
        if (not isinstance(caret, dict) or not isinstance(caret.get("file"), str) or
                Path(caret["file"]).parts[-2:] != ("CL", "cl2.hpp") or
                type(caret.get("line")) is not int or caret["line"] <= 0):
            raise ValueError("OpenCL rename note must originate from CL/cl2.hpp")
    return records
