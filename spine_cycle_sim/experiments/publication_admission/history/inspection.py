"""Inspect selected author text and archive members; never execute old code."""

import hashlib
import io
from pathlib import PurePosixPath
import re
import zipfile

from .git_store import blob

GEOMETRY = re.compile(r"(?:#\s*define\s+(?:MAX_)?SEGMENT_SIZE\s+|\bsegment_size\s*=\s*)(\d+)", re.IGNORECASE)


def text_record(name: str, data: bytes, terms: list[str]):
    text = data.decode("utf-8")
    geometry, temporal = [], []
    for number, line in enumerate(text.splitlines(), 1):
        for match in GEOMETRY.finditer(line):
            geometry.append({"line": number, "value": int(match.group(1)), "text": line.strip()})
        if any(term.casefold() in line.casefold() for term in terms):
            temporal.append({"line": number, "text": line.strip()})
    return {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "geometry_declarations": geometry, "temporal_term_hits": temporal}


def inspect_sources(checkout, snapshot, spec, contract):
    observations = {}
    suffixes = set(contract["text_suffixes"])
    for revision, entries in snapshot["trees"].items():
        for entry in entries:
            path = entry["path"]
            if entry["kind"] != "blob" or PurePosixPath(path).suffix not in suffixes:
                continue
            if not any(path.startswith(prefix) for prefix in spec["source_prefixes"]):
                continue
            key = (path, entry["object"])
            if key not in observations:
                data = blob(checkout, entry["object"], contract["limits"]["text_bytes"])
                observations[key] = {**text_record(path, data, contract["temporal_terms"]),
                    "git_blob": entry["object"], "revisions": []}
            observations[key]["revisions"].append(revision)
    return list(observations.values())


def inspect_archive(data: bytes, contract: dict):
    limits = contract["limits"]
    if len(data) > limits["archive_bytes"]:
        raise ValueError("archive compressed-byte bound exceeded")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > limits["archive_members"] or sum(x.file_size for x in members) > limits["archive_expanded_bytes"]:
            raise ValueError("archive expanded/member bound exceeded")
        records = []
        for member in members:
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe archive member path")
            source_text = "/src/" in member.filename and path.suffix in contract["text_suffixes"]
            saved_text = any(member.filename.startswith(prefix) for prefix in contract.get("archive_extra_text_prefixes", []))
            if member.is_dir() or "__MACOSX" in path.parts or not (source_text or saved_text):
                continue
            if member.file_size > limits["text_bytes"]:
                raise ValueError("archive source-text bound exceeded")
            records.append(text_record(member.filename, archive.read(member), contract["temporal_terms"]))
        return {"sha256": hashlib.sha256(data).hexdigest(), "compressed_bytes": len(data),
            "expanded_bytes": sum(x.file_size for x in members), "members": len(members),
            "member_index": [{"path": x.filename, "bytes": x.file_size, "crc32": x.CRC} for x in members],
            "source_text": records, "binary_or_generated_members_executed": False}
