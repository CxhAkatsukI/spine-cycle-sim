"""Replay whole-line reference and default-off cross-row model, without timing admission."""

from functools import partial

from ..model_contract import BASIS
from ..model_study import ModelStudy, main
from ..model_validation import compare
from .model_contract import PROFILE_ID

CROSS_ROW = ModelStudy(
    PROFILE_ID, BASIS, "unrouted_whole_line_sequential_not_historical_routed_original",
    "test_sharded_k4_cross_row_model*.py",
    partial(compare, profile_id=PROFILE_ID, whole_line_reference=True),
)


if __name__ == "__main__":
    main(CROSS_ROW)
