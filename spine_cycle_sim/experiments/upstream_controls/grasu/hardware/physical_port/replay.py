"""Offline replay of author compilation, BD proof and the separate full link."""

from pathlib import Path

from .. import configuration as config, gates, records
from . import delivery, probe, route_inputs

LINK_PASS = "EXTERNAL_PORT_LINK_PASS_AWAITING_CLOCK_TIMING_AND_BOARD"


def bounded(result):
    limits = result.get("containment", {}).get("limits", {})
    if not all(str(limits.get(key, "")).isdigit() and 0 < int(limits[key]) <= bound * 1024**3
               for key, bound in (("memory.max", 40), ("memory.high", 36))) or \
            int(limits["memory.high"]) > int(limits["memory.max"]) or \
            limits.get("memory.swap.max") != "0" or limits.get("memory.oom.group") != "1" or \
            result.get("admission", {}).get("admitted") is not True:
        raise ValueError("external-port finite memory/admission evidence differs")
    events = dict(line.split() for line in result.get("memory_events_after", "").splitlines())
    if any(events.get(key) != "0" for key in ("oom", "oom_kill", "oom_group_kill")):
        raise ValueError("external-port OOM evidence missing or failed")


def validate(root, receipt):
    roots = {name: Path(path) for name, path in receipt["roots"].items()}
    if set(roots) != {"packet", "compiled", "bd", "route", "continuation"} or any(
            not path.is_absolute() or ".." in path.parts for path in roots.values()) or \
            roots["route"] != roots["continuation"] / "link_attempt":
        raise ValueError("exact external-port evidence roots required")
    indexed = {row["member"]: row["source"] for row in receipt["files"]}
    if set(indexed) != delivery.members():
        raise ValueError("complete external-port evidence index required")
    for member, source in indexed.items():
        owner, suffix = member.split("/", 1)
        path = Path(source["path"])
        if member == "route/" + delivery.direct.TIMING:
            valid = path.is_relative_to(roots[owner] / "link/report") and path.name == delivery.direct.TIMING
        elif member.startswith("compiled/hls/"):
            name = suffix.split("/")[1]
            valid = path.is_relative_to(roots[owner] / "compile" / name) and path.name == name + "_csynth.xml"
        else:
            valid = path == roots[owner] / suffix
        if not valid:
            raise ValueError("external-port source origin differs: " + member)
    outer = records.read(root / "continuation", "results.json")
    compiled, compiled_manifest = records.compilations(root / "compiled",
        remote_route=roots["compiled"], remote_packet=roots["packet"])
    if compiled.get("status") != "FAILED_RETAINED" or \
            "All 33 connections" not in (root / "compiled/link.stdout.txt").read_text():
        raise ValueError("retained original HMSS-capacity failure required")
    failed = compiled["steps"][-1]
    if len(compiled["steps"]) != 5 or failed.get("id") != "link" or \
            type(failed.get("exit_code")) is not int or failed["exit_code"] == 0 or \
            failed.get("stop_reason") != "process_exit" or failed.get("cleanup_snapshot_error", True) is not None or \
            failed.get("command") != compiled_manifest["link"] or \
            failed.get("cwd") != str(roots["compiled"]) or \
            {key: value for key, value in failed.items() if key != "id"} != records.read(root / "compiled", "link.resources.json"):
        raise ValueError("retained failed original-link raw record differs")
    compiled_pins = {row["path"]: row["sha256"] for row in compiled_manifest["pins"]}
    for member in ("compiled/environment.json", *[name for name in indexed if name.startswith("packet/")]):
        if compiled_pins.get(indexed[member]["path"]) != indexed[member]["sha256"]:
            raise ValueError("author compilation source/environment closure differs")
    for name, row in zip(config.KERNELS, compiled["xos"]):
        for kind, member, checked, key in (
            ("abi", f"compiled/xo/{name}.hw.xo", gates.inspect_xo(root / f"compiled/xo/{name}.hw.xo", name), "xo"),
            ("hls", f"compiled/hls/{name}/{name}_csynth.xml",
             gates.inspect_hls(root / f"compiled/hls/{name}", name), "report")):
            if row[kind][key] != indexed[member] or any(
                    value != row[kind].get(field) for field, value in checked.items() if field != key):
                raise ValueError("returned author XO/HLS differs from compiled evidence")
    parent = None
    for owner, timeout, status in (("bd", 3600, route_inputs.PASS), ("route", 43200, LINK_PASS)):
        result, manifest, environment = (records.read(root / owner, name) for name in delivery.TEXT)
        if result.get("status") != status or result.get("errors") != [] or any(
                result.get(flag) is not False for flag in config.FLAGS) or \
                result.get("compiled_inputs") != compiled["xos"] or \
                manifest.get("policy") != config.POLICY or manifest.get("timeout_seconds") != timeout:
            raise ValueError("complete external-port BD/link result required")
        bounded(result)
        observed = manifest.get("command", [])
        if observed.count("--platform") != 1 or observed[-1] == "--platform":
            raise ValueError("one external-port platform required")
        platform = Path(observed[observed.index("--platform") + 1])
        pins = {row["path"]: row["sha256"] for row in manifest["pins"]}
        if any(pins[row["path"]] != row["sha256"] for row in manifest["pins"]) or \
                not platform.is_absolute() or str(platform) not in pins:
            raise ValueError("external-port platform/pins closure differs")
        for member in (owner + "/environment.json", *[owner + "/hooks/" + name for name in probe.HOOK_NAMES]):
            if pins.get(indexed[member]["path"]) != indexed[member]["sha256"]:
                raise ValueError("external-port hook/environment closure differs")
        command = probe.link_command(environment["tools"]["v++"]["invocation"], platform,
            roots["packet"], roots["compiled"], roots[owner], bd_only=owner == "bd")
        step = result.get("step", {})
        records.clean_child(step)
        if observed != command or step != records.read(root / owner, "link.resources.json") or \
                step.get("command") != command or step.get("cwd") != str(roots[owner]) or \
                step.get("timeout_seconds") != timeout or step.get("tree_memory_gib") != 40 or step.get("reserve_gib") != 32:
            raise ValueError("external-port raw link execution differs")
        proof = probe.inspect_proof(root / owner / "hooks/physical_port.xml")
        if result.get("physical_port") != dict(proof, proof=indexed[owner + "/hooks/physical_port.xml"]):
            raise ValueError("external-port physical wiring proof differs")
        if owner == "bd":
            if manifest.get("scope") != "external_same_bank_fanin_BD_only_no_synthesis_routing_or_board":
                raise ValueError("BD-only scope differs")
            continue
        parent = manifest.get("bd_parent", {})
        route_inputs.service_identity(parent["unit"], parent["invocation"])
        if parent.get("profile") != route_inputs.PROFILE or parent.get("bd") != str(roots["bd"]) or \
                not route_inputs.route_finished(parent["service"], parent["invocation"]) or \
                parent.get("source_modified") is not False or parent.get("physical_interconnect_changed") is not True or \
                parent.get("publication_performance_match") is not False or \
                manifest.get("scope") != "external_same_bank_fanin_full_link_not_timing_or_board_admission" or \
                manifest.get("source_modified") is not False or manifest.get("physical_interconnect_changed") is not True or \
                result.get("bd_parent") != parent or result.get("xclbin") != indexed["route/original_grasu.hw.xclbin"]:
            raise ValueError("full link must retain its exact distinct physical parent")
        parent_pins = {row["path"]: row["sha256"] for row in parent["pins"]}
        if any(parent_pins.get(source["path"]) != source["sha256"] for member, source in indexed.items()
               if member.startswith("bd/")) or any(
                indexed[f"bd/hooks/{name}"]["sha256"] != indexed[f"route/hooks/{name}"]["sha256"]
                for name in probe.HOOK_NAMES):
            raise ValueError("full link did not retain exact tested BD evidence/hooks")
        preflight = records.read(root / owner, "preflight/results.json")
        if result.get("preflight") != preflight or preflight.get("status") != "PREFLIGHT_PASS_NOT_ROUTED" or \
                tuple(row.get("label") for row in preflight.get("commands", [])) != records.LABELS:
            raise ValueError("six successful full-link environment probes required")
        for row in preflight["commands"]:
            records.clean_child(row)
            if {k: v for k, v in row.items() if k != "label"} != records.read(root / owner,
                    f"preflight/{row['label']}.resources.json"):
                raise ValueError("full-link environment raw record differs")
    if outer.get("status") != LINK_PASS or outer.get("errors") != [] or \
            outer.get("profile") != route_inputs.PROFILE or outer.get("physical_interconnect_changed") is not True or \
            any(outer.get(flag) is not False for flag in config.FLAGS) or \
            outer.get("child_report") != indexed["route/results.json"] or outer.get("bd_parent") != parent:
        raise ValueError("exact full-link continuation closure differs")
    return compiled["xos"]
