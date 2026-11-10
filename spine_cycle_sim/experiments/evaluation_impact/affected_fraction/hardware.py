"""Explicit bindings to the resident FPGA hosts used by the current delivery."""

import argparse
import json
from pathlib import Path

from ...original_regraph_execution.hardware.source_retention import cc_resident_results, spine_cc_input
from ...original_regraph_execution.hardware.source_retention.runtime import identity, save


def freeze(sssp, cc, respr, output):
    documents = [json.loads(path.read_text()) for path in (sssp, cc, respr)]
    first, second, third = documents
    binding = {
        "weighted_sssp": {
            "spine_host": identity(first["case"]["spine_host"]),
            "spine_image": identity(first["case"]["spine_binary"]),
            "gr_host": first["stage_gates"]["host"], "gr_image": first["stage_gates"]["image"],
            "limitation": "reuse current weighted SSSP implementation; no new route"},
        "connected_components": dict(second["artifacts"],
            limitation="current routed CC implementation; raw skew report remains unavailable"),
        "residual_pagerank": {
            "spine_host": identity(third["original_artifacts"]["spine_host"]["path"]),
            "spine_image": third["row"]["rows"]["spine"]["clock"]["binary"],
            "gr_host": third["stage_gates"]["host"], "gr_image": third["stage_gates"]["image"],
            "epsilon": 1e-6, "limitation": "matched derated 140-MHz execution, not nominal timing closure"},
    }
    save(output, dict(source_receipts=[identity(path) for path in (sssp, cc, respr)], hardware=binding))


def commands(binding, manifest, point, output):
    graph, source = point["graph"]["path"], str(manifest["source"])
    gr = [binding["gr_host"]["path"], binding["gr_image"]["path"], graph,
          str(output / "gr-state.txt")]
    if manifest["algorithm"] != "residual_pagerank":
        max_supersteps = manifest.get("gr_max_supersteps", 256)
        if type(max_supersteps) is not int or max_supersteps <= 0:
            raise ValueError("gr_max_supersteps must be a positive integer")
        gr.extend((source, str(max_supersteps)))
    if manifest["algorithm"] == "connected_components":
        data = spine_cc_input.prepare(Path(graph), output / "cc-input")
        spine = [binding["spine_host"]["path"], "--xclbin", binding["spine_image"]["path"],
                 "--hot", "balanced", "--mode", "partial", "--samples", "1",
                 "--slice", data["graph"]["path"], "--update", data["update"]["path"]]
        return {"spine": spine, "gr": gr}, data
    spine = [binding["spine_host"]["path"], binding["spine_image"]["path"],
             "--dynamic-graph", graph, "--source", source, "--resident-benchmark"]
    return {"spine": spine, "gr": gr}, None


def compare(comparator, manifest, point, texts, bdf):
    if manifest["algorithm"] != "connected_components":
        result = comparator.compare(manifest["algorithm"], texts["gr"], texts["spine"], manifest["source"])
        if (result["vertices"], result["logical_updates"]) != (manifest["vertices"], point["updates"]):
            raise ValueError("measured workload differs from CPU-labelled input")
        return result
    data = dict(vertices=manifest["vertices"], edges=manifest["edges"], updates=point["updates"])
    result = cc_resident_results.analyze(data, texts["gr"], texts["spine"], bdf=bdf)
    return dict(result, gr_wall_ms=result["gr_ms"], spine_wall_ms=result["spine_ms"],
                gr_rounds=result["gr_supersteps"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sssp", "cc", "respr", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    freeze(args.sssp, args.cc, args.respr, args.output)


if __name__ == "__main__":
    main()
