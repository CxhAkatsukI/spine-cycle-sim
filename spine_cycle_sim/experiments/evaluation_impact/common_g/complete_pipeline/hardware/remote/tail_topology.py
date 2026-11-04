"""Compare routed weighted-tail topology without conflating AXIS IDs and HBM ports."""

GATHER_CUS = {f"lksg_stream:lksg_stream_{lane}" for lane in range(1, 5)}
STREAM_TYPE = "MEM_STREAMING_CONNECTION"
PROFILE = "weighted-tail-publication-rows"


def signature(topology, *, tail):
    streams = {tag: (kind, used, size) for tag, kind, used, size in topology["memory"]
               if kind == STREAM_TYPE}
    endpoints = {tag: [] for tag in streams}
    physical = []
    gather = set()
    for cu, arg, tag in topology["connections"]:
        if tag not in streams:
            physical.append((cu, arg, tag))
            continue
        if cu in GATHER_CUS and arg != 0:
            first = 6 if tail else 5
            if arg not in range(first, first + 3):
                raise ValueError("unexpected weighted Gather stream argument ID")
            arg = arg - 1 if tail else arg
            gather.add((cu, arg))
        endpoints[tag].append((cu, arg))
    if gather != {(cu, arg) for cu in GATHER_CUS for arg in (5, 6, 7)}:
        raise ValueError("expected three shifted AXIS ports per weighted Gather CU")
    if any(len(ends) != 2 or len(set(ends)) != 2 for ends in endpoints.values()):
        raise ValueError("expected point-to-point streams in weighted routed topology")
    return {**topology,
            "memory": [row for row in topology["memory"] if row[1] != STREAM_TYPE],
            "connections": physical,
            "streams": sorted((tuple(sorted(ends)), streams[tag]) for tag, ends in endpoints.items())}


def verify(original, candidate):
    if signature(original, tail=False) != signature(candidate, tail=True):
        raise ValueError("weighted tail changes an AXIS endpoint, clock, CU or physical memory mapping")
