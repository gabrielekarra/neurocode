# ruff: noqa
"""Sample module used by the test suite."""

import math
import statistics  # noqa: F401  # unused on purpose
from package.mod_b import helper_value, run_task
from package.mod_b import unused_utility  # noqa: F401  # unused on purpose


def orchestrator(value: int) -> int:
    run_task(value)
    helper_value(value)
    helper_local()
    math.sqrt(value)
    task_one()
    task_two()
    task_three()
    task_four()
    task_five()
    task_six()
    task_seven()
    task_eight()
    task_nine()
    task_ten()
    task_eleven()
    return value + 1


def helper_local() -> int:
    return helper_value(1)


def unused_local() -> int:
    return 0


def task_one() -> int:
    return 1


def task_two() -> int:
    return 2


def task_three() -> int:
    return 3


def task_four() -> int:
    return 4


def task_five() -> int:
    return 5


def task_six() -> int:
    return 6


def task_seven() -> int:
    return 7


def task_eight() -> int:
    return 8


def task_nine() -> int:
    return 9


def task_ten() -> int:
    return 10


def task_eleven() -> int:
    return 11
