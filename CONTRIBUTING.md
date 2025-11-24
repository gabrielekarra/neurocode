# Contributing to NeuroCode

## Setup
- Use Python 3.10–3.12.
- Install dependencies with `pip install -e .[dev]` from the repo root.
- Ensure `neurocode` resolves from your environment (`pip install neurocode-ai` for a user install).

## Development loop
- Format/lint: `ruff check src tests`
- Tests: `pytest`
- Build locally (optional): `python -m build` or `make release`

## Pull requests
- Keep changes focused and include docs/README updates when behavior shifts.
- Add tests for new edge cases and update sample flows if CLI surfaces change.
- Run `ruff check src tests` and `pytest` before opening a PR.
- Describe how you validated the change and any follow-up work needed.
- By contributing, you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
