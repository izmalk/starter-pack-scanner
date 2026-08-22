# Starter Pack Scanner — common development tasks.
#
# The venv is created on demand in .venv/; override with `PYTHON=...`.

PYTHON ?= .venv/bin/python
PIP = $(PYTHON) -m pip
VENV_FLAGS ?=

.PHONY: help install install-cli install-web run test lint clean serve-web server-web web stop web-stop

help: ## Show this help
	@grep -E '^[a-zA-Z_-][a-zA-Z_ -]*:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.venv/bin/python: ## Create the virtual environment (internal target)
	$(PYTHON) -m venv $(VENV_FLAGS) .venv 2>/dev/null || python3 -m venv .venv
	@touch .venv/bin/python

install: .venv/bin/python ## Install the package (CLI + web GUI) into .venv
	$(PIP) install -e .

install-cli: .venv/bin/python ## Install only what the CLI needs (no web GUI deps)
	$(PIP) install -e '.[cli]'

install-web: .venv/bin/python ## Alias of 'install' (kept for compatibility)
	$(PIP) install -e .

run: install ## Run the CLI scanner (pass REPO=..., e.g. make run REPO=https://github.com/canonical/kafka-operator)
	$(PYTHON) -m starter_pack_scanner

serve-web server-web web: install ## Start the local web GUI at http://127.0.0.1:8765
	$(PYTHON) -m starter_pack_scanner.web.app

stop web-stop: ## Stop the web GUI if it is running in the background (port 8765)
	@pid=$$(ss -tlnp 2>/dev/null | grep ':8765' | grep -oP 'pid=\K[0-9]+' | head -1); \
	if [ -n "$$pid" ]; then \
		echo "Stopping web GUI (PID $$pid)…"; \
		kill $$pid && sleep 1; \
		if ss -tln 2>/dev/null | grep -q ':8765'; then \
			echo "Still running — forcing."; kill -9 $$pid 2>/dev/null; sleep 1; \
		fi; \
		ss -tln 2>/dev/null | grep -q ':8765' && echo "ERROR: port 8765 still busy" || echo "Stopped."; \
	else \
		echo "Web GUI is not running (nothing on port 8765)."; \
	fi

test: install ## Run the test suite (offline; no network required)
	$(PIP) install -q pytest httpx
	$(PYTHON) -m pytest tests/ -v

lint: ## Compile-check all Python sources
	$(PYTHON) -m compileall -q starter_pack_scanner tests

clean: ## Remove caches and build artifacts (keeps .venv)
	rm -rf build dist *.egg-info .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
