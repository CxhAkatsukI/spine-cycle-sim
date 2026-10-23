"""Index one redundant full-repository snapshot without omitting its sources."""

import hashlib
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


INDEX = "before/source-snapshot-index.json"


def layout(report):
    commit = report.get("commit", "")
    if (report.get("status") != "PRECHANGE_GIT_SOURCE_SNAPSHOT" or len(commit) != 40 or
            any(c not in "0123456789abcdef" for c in commit)):
        raise ValueError("explicit prechange Git source identity required")
    names = {}
    for key, suffix in (("full_repository_snapshot", ".tar.gz"),
                        ("code_only_snapshot", "-code-only.tar.gz")):
        item = report[key]
        path = Path(item["path"])
        name = "source-" + commit[:7] + suffix
        if (not path.is_absolute() or ".." in path.parts or path.name != name or
                type(item["bytes"]) is not int or item["bytes"] <= 0 or
                len(item["sha256"]) != 64 or
                any(c not in "0123456789abcdef" for c in item["sha256"])):
            raise ValueError("invalid prechange snapshot identity or path")
        names[key] = "before/" + name
    full = report["full_repository_snapshot"]
    if (full.get("external") is not True or not full.get("reason") or
            Path(full["path"]).parent != Path(report["code_only_snapshot"]["path"]).parent):
        raise ValueError("external snapshot needs a co-located source replacement and reason")
    return names


def collect(attempts):
    index = attempts / INDEX
    if not index.exists():
        return set(), []
    report = json.loads(index.read_text())
    names = layout(report)
    for key, name in names.items():
        path = attempts / name
        item = report[key]
        if (item["path"] != str(path) or path.is_symlink() or not path.is_file() or
                path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]):
            raise ValueError("prechange snapshot file differs or is missing")
    record = dict(index_member=INDEX, omitted_member=names["full_repository_snapshot"],
                  **report["full_repository_snapshot"])
    return {attempts / names["full_repository_snapshot"]}, [record]


def verify(read, members, records):
    if not records:
        if INDEX in members:
            raise ValueError("prechange source index needs an explicit external record")
        return
    if len(records) != 1 or records[0].get("index_member") != INDEX:
        raise ValueError("unexpected external source snapshot")
    report = json.loads(read(INDEX))
    names = layout(report)
    expected = dict(index_member=INDEX, omitted_member=names["full_repository_snapshot"],
                    **report["full_repository_snapshot"])
    if records[0] != expected or names["full_repository_snapshot"] in members:
        raise ValueError("external source record differs or full snapshot was recursively archived")
    blob = read(names["code_only_snapshot"])
    compact = report["code_only_snapshot"]
    if (len(blob), hashlib.sha256(blob).hexdigest()) != (compact["bytes"], compact["sha256"]):
        raise ValueError("archived prechange source replacement differs")
