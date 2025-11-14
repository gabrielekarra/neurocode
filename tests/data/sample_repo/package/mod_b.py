"""Auxiliary module for tests."""


def helper_value(value: int) -> int:
    return value + 1


def run_task(value: int) -> int:
    return helper_value(value)


def unused_utility(value: int = 0) -> int:
    return value - 1
