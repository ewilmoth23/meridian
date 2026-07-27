# Meridian — common dev tasks.
.PHONY: help install install-dev install-all test test-fast cov lint typecheck format check clean docs build run-cli run-desktop migration migrate

PY ?= python3
VENV ?= .venv
ACTIVATE = . $(VENV)/bin/activate

help:
	@echo "Meridian dev tasks:"
	@echo "  make install         - Install editable + core deps only"
	@echo "  make install-dev     - Install editable + dev tooling"
	@echo "  make install-all     - Install editable + all extras"
	@echo "  make test            - Run full test suite"
	@echo "  make test-fast       - Run tests, skip slow + integration"
	@echo "  make cov             - Run tests with coverage report"
	@echo "  make lint            - Run ruff"
	@echo "  make typecheck       - Run mypy"
	@echo "  make format          - Format with ruff"
	@echo "  make check           - lint + typecheck + test (CI gate)"
	@echo "  make docs            - Build Sphinx docs"
	@echo "  make migration NAME=description  - Create new alembic migration"
	@echo "  make migrate         - Apply pending migrations"
	@echo "  make run-cli         - Run the CLI"
	@echo "  make run-desktop     - Run the desktop app"
	@echo "  make clean           - Remove build artifacts and caches"

$(VENV)/bin/activate:
	$(PY) -m venv $(VENV)
	$(ACTIVATE) && pip install --upgrade pip wheel setuptools

install: $(VENV)/bin/activate
	$(ACTIVATE) && pip install -e .

install-dev: $(VENV)/bin/activate
	$(ACTIVATE) && pip install -e ".[dev]"

install-all: $(VENV)/bin/activate
	$(ACTIVATE) && pip install -e ".[all]"

test:
	$(ACTIVATE) && pytest

test-fast:
	$(ACTIVATE) && pytest -m "not slow and not integration and not field"

cov:
	$(ACTIVATE) && pytest --cov --cov-report=term-missing --cov-report=html

lint:
	$(ACTIVATE) && ruff check src tests

typecheck:
	$(ACTIVATE) && mypy src

format:
	$(ACTIVATE) && ruff format src tests
	$(ACTIVATE) && ruff check --fix src tests

check: lint typecheck test

docs:
	$(ACTIVATE) && sphinx-build -b html docs docs/_build/html

migration:
	@if [ -z "$(NAME)" ]; then echo "Usage: make migration NAME=description"; exit 1; fi
	$(ACTIVATE) && alembic -c src/meridian/adapters/persistence/alembic.ini revision -m "$(NAME)" --autogenerate

migrate:
	$(ACTIVATE) && alembic -c src/meridian/adapters/persistence/alembic.ini upgrade head

run-cli:
	$(ACTIVATE) && meridian --help

run-desktop:
	$(ACTIVATE) && meridian-desktop

clean:
	rm -rf build/ dist/ *.egg-info/ src/*.egg-info/
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .mypy_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	find . -type d -name htmlcov -prune -exec rm -rf {} +
	find . -name "*.pyc" -delete
