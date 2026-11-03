"""Derive only the two Little frontend edits for a pinned weighted A4 control."""

import argparse
import hashlib
import json
from pathlib import Path


AUTHOR = "365456826cef495285383d939907f847e05ad74b"
UDF_SHA256 = "264965570ce0d0d202eca3c50e1f95aafbba72654761601f24bf9ab78edeed50"
LITTLE = Path("acc_template/kernel_little_gs")
EDIT = {
    "kernel_scatter_gather.cpp": (
        "d98718b86ae37c312bca5228ed391f62335675a91956de06a10072203dc21947",
        "            for (int u = 0; u < NUM_EDGE_PER_BURST; u ++){\n"
        "        #pragma HLS UNROLL\n"
        "                ap_uint<20> dst = one_edge_burst.edges[u].dst.range(30,0) - part_dst_offset;\n"
        "                dst.range(19,19) = one_edge_burst.edges[u].dst.range(31,31);\n"
        "                one_edge_burst.edges[u].dst = dst;\n"
        "            }",
        "            // The compact host input already holds partition-local destinations.",
    ),
    "acc_scatter.h": (
        "0c44fbded2c02c516856c073d937fc1016c1a1d8740bbf137906bb2150c9951b",
        "                ap_uint<32> update = PROP_COMPUTE_STAGE0(src_prop);\n"
        "\n"
        "                // ap_uint<32> update = uram_row.range(31 + (uram_row_offset << 5), (uram_row_offset << 5));\n"
        "                \n"
        "                an_update_set.tuples[u].update = update;\n"
        "                an_update_set.tuples[u].dst = an_edge_burst.edges[u].dst;",
        "                const auto dst_word = an_edge_burst.edges[u].dst.to_uint();\n"
        "                an_update_set.tuples[u].update =\n"
        "                    PROP_COMPUTE_STAGE1(PROP_COMPUTE_STAGE0(src_prop), a4_weighted::weight(dst_word));\n"
        "                an_update_set.tuples[u].dst = a4_weighted::gather_destination(dst_word);",
    ),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned(path, expected):
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError(f"unreviewed input: {path}")
    return data


def prepare(author, udf, output):
    derived = {}
    pins = {}
    for name, (sha, old, new) in EDIT.items():
        source = author / LITTLE / name
        content = pinned(source, sha).decode("ascii")
        if content.count(old) != 1:
            raise ValueError(f"ambiguous weighted edit: {source}")
        content = content.replace(old, new)
        if name == "acc_scatter.h":
            content = content.replace('#include "fpga_application.h"',
                                      '#include "fpga_application.h"\n#include "edge_word.hpp"', 1)
        derived[name] = content.encode("ascii")
        pins[str(source)] = sha
    derived["l2.h"] = pinned(udf, UDF_SHA256)
    pins[str(udf)] = UDF_SHA256
    edge = Path(__file__).with_name("edge_word.hpp")
    derived[edge.name] = edge.read_bytes()
    pins[str(edge)] = digest(derived[edge.name])
    output.mkdir()
    for name, data in derived.items():
        (output / name).write_bytes(data)
    manifest = {
        "status": "WEIGHTED_LITTLE_SOURCE_ONLY_NOT_FPGA",
        "author_revision_for_little_files": AUTHOR,
        "input_sha256": pins,
        "output_sha256": {name: digest(data) for name, data in derived.items()},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("author", type=Path)
    parser.add_argument("udf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.author.resolve(), args.udf.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
