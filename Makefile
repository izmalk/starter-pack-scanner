# Starter Pack Scanner — common development tasks.
#
# The venv is created on demand in .venv/; override with `PYTHON=...`.

PYTHON ?= .venv/bin/python
PIP = $(PYTHON) -m pip
VENV_FLAGS ?=

.PHONY: help install install-web run test lint clean serve-web server-web web

help: ## Show this help
	@grep -E '^[a-zA-Z_-][a-zA-Z_ -]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.venv/bin/python: ## Create the virtual environment (internal target)
	$(PYTHON) -m venv $(VENV_FLAGS) .venv 2>/dev/null || python3 -m venv .venv
	@touch .venv/bin/python

install: .venv/bin/python ## Install the package (CLI only) into .venv
	$(PIP) install -e .

install-web: .venv/bin/python ## Install the package with the web GUI extras
	$(PIP) install -e '.[web]'

run: install ## Run the CLI scanner (pass REPO=..., e.g. make run REPO=https://github.com/canonical/kafka-operator)
	$(PYTHON) -m starter_pack_scanner $(REPO)

serve-web server-web web: install-web ## Start the local web GUI at http://127.0.0.1:8765
	$(PYTHON) -m starter_pack_scanner.web.app

test: install-web ## Run the test suite (offline; no network required)
	$(PIP) install -q pytest httpx
	$(PYTHON) -m pytest tests/ -v

lint: ## Compile-check all Python sources
	$(PYTHON) -m compileall -q starter_pack_scanner tests

clean: ## Remove caches and build artifacts (keeps .venv)
	rm -rf build dist *.egg-info .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
