"""Pin the reviewed arithmetic, not a claim about a routed implementation."""

import subprocess

from .. import artifact


def unique_literals(path, literals):
    text = path.read_text()
    if any(text.count(literal) != 1 for literal in literals):
        raise ValueError("reviewed PR arithmetic source anchors changed: " + str(path))
    return artifact.identity(path)


def review(original, production):
    paths = (
        (original / "acc_udfs/pr/l2.h", (
            "#define prop_t int", "#define kDampFixPoint       108",
            "prop_t new_score = arg  + ((kDampFixPoint * tProp) >> 7);",
            "tmp = (1 << 16 ) / outDeg;", "prop_t update = (new_score * tmp) >> 16;")),
        (production / "include/regraph_pagerank/l2.h", (
            "typedef ap_uint<32> prop_t;",
            "regraph_word_to_float(original) + regraph_word_to_float(update)")),
        (production / "kernels/regraph_pagerank_apply/regraph_pagerank_apply.cpp", (
            "#if GRASU_REGRAPH_PAGERANK_MODE == 1",
            "next_rank = base + dangling_share + incoming;", "next_value = next_rank;",
            "const unsigned degree = lane(degree_beat, lane_index).to_uint();",
            "const float payload = active && degree != 0",
            "? damping * next_value / degree", "source_words[lane_index] = float_to_word(payload);")),
    )
    pins = [unique_literals(path, literals) for path, literals in paths]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=production, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=production, text=True).splitlines()
    if dirty:
        raise ValueError("clean production source required for an explicit arithmetic profile")
    return {"pins": pins, "production_revision": revision,
            "literal_review_only_not_compiler_or_routed_implementation_proof": True}
