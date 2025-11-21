"""Class-heavy module for exercising NeuroCode's IR."""

from package.mod_b import helper_value


class Processor:
    def __init__(self) -> None:
        self._cache: list[int] = []

    def add(self, value: int) -> int:
        result = self._compute(value)
        self._cache.append(result)
        return result

    def _compute(self, value: int) -> int:
        return helper_value(value)


class Derived(Processor):
    def add(self, value: int) -> int:
        parent_result = super().add(value)
        return self._compute(parent_result)


def use_processor(value: int) -> int:
    processor = Processor()
    return processor.add(value)
