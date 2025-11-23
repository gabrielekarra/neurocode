from package import mod_a


def test_orchestrator_calls_helper_value() -> None:
    assert mod_a.orchestrator(1) == 2
