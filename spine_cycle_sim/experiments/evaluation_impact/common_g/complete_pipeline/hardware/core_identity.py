"""Allow only the documented non-synthesizable concurrent-host report change."""

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity

GUARD = '#ifndef __SYNTHESIS__\n#include "finite_host.hpp"\n#endif'
REPORT = "static HostReport report;"
THREAD_REPORT = "static thread_local HostReport report;"


def check(composition, search, cache):
    source = composition / "source/hls"
    exported = search / "source/cpp/tests/evaluation_impact/common_g/hls"
    differences = []
    for folder in ("search_binding", "search_pipeline"):
        left, right = source / folder, exported / folder
        included = {path.name for path in left.iterdir()}
        excluded = {"control.cpp", "rtl_control.cpp"}
        if folder == "search_binding":
            if included != {"top.cpp", "top.hpp"}:
                raise ValueError("composition search binding file set differs")
        else:
            excluded.add("top.cpp")
            if any(path.suffix != ".hpp" for path in left.iterdir()):
                raise ValueError("composition search pipeline must contain shared headers only")
        if included != {path.name for path in right.iterdir()} - excluded:
            raise ValueError("composition and exported search file sets differ")
        for path in sorted(left.iterdir()):
            reference = right / path.name
            actual, expected = path.read_bytes(), reference.read_bytes()
            if actual == expected:
                continue
            if (folder != "search_pipeline" or path.name != "finite_host.hpp" or
                    expected.count(REPORT.encode()) != 1 or
                    actual != expected.replace(REPORT.encode(), THREAD_REPORT.encode()) or
                    GUARD not in (left / "network.hpp").read_text() or
                    GUARD not in (right / "network.hpp").read_text()):
                raise ValueError("composition and exported search core differ")
            differences.append({"composition": identity(path), "exported": identity(reference),
                "scope": "host_only_excluded_by_network_synthesis_guard",
                "change": "HostReport static to thread_local for concurrent C simulation"})
    for name in ("cache_pipeline.hpp", "cache_bank.hpp", "cache_lane.hpp"):
        if (source / name).read_bytes() != (cache / "source" / name).read_bytes():
            raise ValueError("composition and exported cache core differ")
    return {"synthesizable_core_identical": True, "host_only_differences": differences}
