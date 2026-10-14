# Local development: a virtualenv in .venv and shortcuts that run inside it.
# `make help` lists the targets. Override variables on the command line,
# for example `make run PORT=9000`.

PYTHON   ?= python3
VENV     ?= .venv
DATA_DIR ?= data
HOST     ?= 0.0.0.0
PORT     ?= 8080
ARGS     ?=

BIN   := $(VENV)/bin
PY    := $(BIN)/python
STAMP := $(VENV)/.installed

.DEFAULT_GOAL := help
.PHONY: help venv run ui test lint scan scale watch clean

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

# Reinstall whenever requirements.txt changes.
$(STAMP): requirements.txt
	@[ -x $(PY) ] || $(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt
	@touch $@

venv: $(STAMP) ## Create .venv and install requirements.txt

run: $(STAMP) ## Run Open BLE Hub with Bluetooth (UI on PORT, data in DATA_DIR)
	$(PY) -m ble_hub --data-dir $(DATA_DIR) --host $(HOST) --port $(PORT) $(ARGS)

ui: $(STAMP) ## Run Open BLE Hub without Bluetooth, for UI work
	$(PY) -m ble_hub --data-dir $(DATA_DIR) --host $(HOST) --port $(PORT) --no-bluetooth $(ARGS)

test: $(STAMP) ## Run the unit tests
	$(PY) -m unittest discover -s tests

lint: ## Lint and format-check with ruff (python3 -m pip install ruff==0.17.0)
	python3 -m ruff check .
	python3 -m ruff format --check .

scan: $(STAMP) ## Scan for Philips devices (philips_ble scan)
	$(PY) -m philips_ble scan $(ARGS)

scale: $(STAMP) ## Connect to the scale once (philips_ble scale)
	$(PY) -m philips_ble scale $(ARGS)

watch: $(STAMP) ## Keep listening for the scale (philips_ble watch)
	$(PY) -m philips_ble watch $(ARGS)

clean: ## Remove .venv (keeps DATA_DIR)
	rm -rf $(VENV)
