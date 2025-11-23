import sys
from pathlib import Path

# Ensure sample repo package is importable when running from project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from package import mod_a


def test_orchestrator_calls_helper_value() -> None:
    assert mod_a.orchestrator(1) == 2
