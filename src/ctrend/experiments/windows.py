"""The two windows. Every other module imports them from here.

Defining them once is the point: a second definition that drifted by a week would
silently leak tuning data into the evaluation, and nothing downstream would notice.
"""
from __future__ import annotations

#: Parameters are selected here and nowhere else (82 weeks).
TUNE_START, TUNE_END = 202223, 202352
#: Evaluated exactly once, never used for selection (133 weeks).
EVAL_START, EVAL_END = 202401, 202629

assert TUNE_END < EVAL_START, "the windows must not overlap"


def in_tune(week: int) -> bool:
    return TUNE_START <= week <= TUNE_END


def in_eval(week: int) -> bool:
    return EVAL_START <= week <= EVAL_END
