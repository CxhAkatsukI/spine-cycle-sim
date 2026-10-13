"""Keep every old case and add large conflicts, owner aliases, and cold reuse."""

from ..parallel.preparation import CASES as SEARCH_CASES, segments
from ..preparation import HOT, prepare_segments

CASES = SEARCH_CASES + (
    ("same_key_large", 4096, "conflict"),
    ("same_key_amortized", 65536, "conflict"),
    ("owner_alias", 4096, "alias"),
    ("hot_amortized", 65536, "hot"),
    ("cold_reuse", 4096, "cold"),
)
ARMS = ("original", "current", "parallel", "parallel_hot")


def selected(count, kind):
    # Two global segments share a hot physical bank; stride 32 aliases one owner.
    return [32 * index for index in range(count)] if kind == "alias" else segments(count, kind)


def prepare(root):
    for name, count, kind in CASES:
        values = selected(count, kind)
        if kind in ("hot", "alias", "conflict") and any(value >= HOT * 2 for value in values):
            raise ValueError("declared hot case crossed the hot/cold boundary")
        prepare_segments(root / name, values)
