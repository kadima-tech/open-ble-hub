# Local development: a virtualenv in .venv with every package installed
# editable, and shortcuts that run inside it. `make help` lists the targets.
# Override variables on the command line, for example `make run PORT=9000`.

PYTHON   ?= python3
VENV     ?= .venv
DATA_DIR ?= data
HOST     ?= 0.0.0.0
PORT     ?= 8080
ARGS     ?=

BIN       := $(VENV)/bin
PY        := $(BIN)/python
STAMP     := $(VENV)/.installed
PROJECTS  := $(wildcard packages/* apps/*)
# tests/ holds the Bluetooth suite that drives both apps against bleak;
# deploy/tests the updater that installs the hubs on a Pi.
TEST_DIRS := $(wildcard $(addsuffix /tests,$(PROJECTS))) tests deploy/tests

.DEFAULT_GOAL := help
.PHONY: help venv run ui test lint build scan scale watch clean

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

# Reinstall whenever requirements-dev.txt or a pyproject.toml changes.
$(STAMP): requirements-dev.txt $(addsuffix /pyproject.toml,$(PROJECTS))
	@[ -x $(PY) ] || $(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements-dev.txt
	@touch $@

venv: $(STAMP) ## Create .venv and install every package editable

run: $(STAMP) ## Run Bathroom Hub with Bluetooth (UI on PORT, data in DATA_DIR)
	$(PY) -m bathroom_hub --data-dir $(DATA_DIR) --host $(HOST) --port $(PORT) $(ARGS)

ui: $(STAMP) ## Run Bathroom Hub without Bluetooth, for UI work
	$(PY) -m bathroom_hub --data-dir $(DATA_DIR) --host $(HOST) --port $(PORT) --no-bluetooth $(ARGS)

test: $(STAMP) ## Run the unit tests of every package and app
	@set -e; for dir in $(TEST_DIRS); do echo "== $$dir"; $(PY) -m unittest discover -s $$dir; done

lint: ## Lint and format-check with ruff (python3 -m pip install ruff==0.17.0)
	python3 -m ruff check .
	python3 -m ruff format --check .

build: $(STAMP) ## Build sdists and wheels of the libraries into dist/
	$(PY) -m pip install -q build
	@set -e; for dir in $(wildcard packages/*); do $(PY) -m build -q --outdir dist $$dir; done

scan: $(STAMP) ## Scan for supported devices (ble_probe scan)
	$(PY) -m ble_probe scan $(ARGS)

scale: $(STAMP) ## Connect to the scale once (ble_probe scale)
	$(PY) -m ble_probe scale $(ARGS)

watch: $(STAMP) ## Keep listening for the scale (ble_probe watch)
	$(PY) -m ble_probe watch $(ARGS)

clean: ## Remove .venv and dist/ (keeps DATA_DIR)
	rm -rf $(VENV) dist
