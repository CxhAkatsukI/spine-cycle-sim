"""Read Git objects without checking out or editing accepted author sources."""

from pathlib import Path
import subprocess


def git(checkout: Path, *arguments: str):
    return subprocess.check_output(["git", "-C", str(checkout), *arguments], timeout=60)


def parse_tree(data: bytes, limit: int):
    records = [item for item in data.split(b"\0") if item]
    if len(records) > limit:
        raise ValueError("history tree-entry bound exceeded")
    result = []
    for item in records:
        metadata, path = item.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        if kind not in ("blob", "commit") or len(object_id) != 40:
            raise ValueError("unsupported Git tree record")
        result.append({"mode": mode, "kind": kind, "object": object_id, "path": path.decode("utf-8")})
    return result


def snapshot(checkout: Path, spec: dict, limits: dict):
    if git(checkout, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ValueError("history inspection requires a complete fetched repository")
    head = git(checkout, "rev-parse", "HEAD").decode().strip()
    if head != spec["head"] or git(checkout, "status", "--porcelain"):
        raise ValueError("accepted source checkout must remain pinned and clean")
    revisions = git(checkout, "rev-list", "--all").decode().splitlines()
    if len(revisions) > limits["commits"] or len(revisions) != spec["expected_commits"]:
        raise ValueError("reachable commit set differs from declared history")
    trees = {}
    for revision in revisions:
        trees[revision] = parse_tree(git(checkout, "ls-tree", "-r", "-z", revision), limits["tree_entries"])
    return {"head": head, "revisions": revisions, "refs": git(checkout, "show-ref").decode().splitlines(),
            "trees": trees, "scope": "complete_reachable_local_refs_not_private_or_unreachable_objects"}


def blob(checkout: Path, object_id: str, limit: int):
    size = int(git(checkout, "cat-file", "-s", object_id))
    if size > limit:
        raise ValueError("Git blob read bound exceeded")
    data = git(checkout, "cat-file", "blob", object_id)
    if len(data) != size:
        raise ValueError("short Git blob read")
    return data
