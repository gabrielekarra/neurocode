PYTHON := python

.PHONY: install-dev lint test check release

install-dev:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e .[dev]

lint:
	$(PYTHON) -m ruff check src tests

test:
	$(PYTHON) -m pytest

check: lint test

release:
	./scripts/release.sh
