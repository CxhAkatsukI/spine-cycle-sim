"""Audit charged metadata copies, fixed bases and connected bank intervals."""

REPLICA_CHANNELS = (3, 9, 15, 20)
LANE_RANGES = ((0, 6), (6, 12), (12, 18), (18, 23))
BASE_NAMES = tuple(name + str(i) for name in ("pma", "update") for i in range(4)) + ("row", "binary")
COPY_NAMES = tuple(name + "-cu" + str(i) for name in ("row", "binary") for i in range(4))


def check_resources(value, replicated):
    regions = value["regions"]
    expected = {(shard, name) for shard in range(3)
                for name in BASE_NAMES + (COPY_NAMES if replicated else ())}
    if (len(regions) != len(expected)
            or {(r["shard"], r["name"]) for r in regions} != expected
            or any(not 0 <= r["channel"] < 23 for r in regions)):
        raise ValueError("resident region set or channel differs")
    originals = {(r["shard"], r["name"]): r for r in regions if "-cu" not in r["name"]}
    for shard in range(3):
        for name in ("row", "binary"):
            copies = [r for r in regions if r["shard"] == shard and r["name"].startswith(name + "-cu")]
            source = originals[shard, name]
            if copies and (len({r["base"] for r in copies}) != 1 or any(
                    (r["logical_bytes"], r["allocated_bytes"])
                    != (source["logical_bytes"], source["allocated_bytes"]) for r in copies)):
                raise ValueError("resident replica base or table size differs")
    allocated, extra, upload, spans = 0, 0, 0, []
    for bank in range(23):
        end = 0
        for region in sorted((r for r in regions if r["channel"] == bank), key=lambda r: r["base"]):
            if (region["base"] < end or region["base"] % 4096
                    or region["allocated_bytes"] % 4096 or region["allocated_bytes"] <= 0):
                raise ValueError("resident region overlaps or is unaligned")
            end = region["base"] + region["allocated_bytes"]
            if end > 512 * 1024**2 or not 0 < region["logical_bytes"] <= region["allocated_bytes"]:
                raise ValueError("resident capacity or logical bytes differ")
            allocated += region["allocated_bytes"]
            if region["name"].startswith(("row", "binary")):
                upload += region["logical_bytes"]
            if "-cu" in region["name"]:
                extra += region["allocated_bytes"]
                if region["channel"] != REPLICA_CHANNELS[int(region["name"][-1])]:
                    raise ValueError("resident replica channel differs")
            if region["name"].startswith(("pma", "update")):
                lo, hi = LANE_RANGES[int(region["name"][-1])]
                if not lo <= bank < hi:
                    raise ValueError("resident lane connectivity differs")
        spans.append(end)
    required = {"allocated_bytes": allocated, "channel_span_bytes": sum(spans),
        "used_channels": sum(bool(n) for n in spans), "extra_metadata_bytes": extra,
        "initial_metadata_upload_bytes": upload, "interbatch_metadata_upload_bytes": 0,
        "metadata_reservations_fixed": True}
    if any(value[key] != expected for key, expected in required.items()) or (extra > 0) != replicated:
        raise ValueError("resident physical resource ledger differs")
