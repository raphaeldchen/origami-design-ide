# Single source of truth for build + test. CI runs these same targets.
# Python is overridable: make PYTHON=python3.14 test
PYTHON ?= .venv/bin/python
# Exported so build.sh (which reads $PYTHON, defaulting to python3) uses the
# same interpreter as the tests — critical for CI's `make PYTHON=python test`.
export PYTHON
HARNESS := mcp_harness
PYTEST  := PYTHONPATH=.:tests $(PYTHON) -m pytest

.PHONY: build test bless sweep clean

build: ## Build the C++ extension and the Oriedita linter
	cd $(HARNESS) && ./build.sh
	cd $(HARNESS) && ./build_linter.sh

test: build ## Build, then run the regression suite (the gate)
	cd $(HARNESS) && $(PYTEST) tests/ -v

bless: ## Regenerate verdict baseline + geometry goldens from current engine
	cd $(HARNESS) && PYTHONPATH=.:tests $(PYTHON) tests/bless.py

sweep: build ## Run the broad probe_sweep catalog (exploratory, non-gating)
	cd $(HARNESS) && $(PYTHON) probe_sweep.py

clean: ## Remove build artifacts
	rm -rf $(HARNESS)/headless_treemaker*.so $(HARNESS)/*.dSYM \\
	       $(HARNESS)/OrieditaValidator.class \\
	       $(HARNESS)/__pycache__ $(HARNESS)/tests/__pycache__ \\
	       $(HARNESS)/.pytest_cache
