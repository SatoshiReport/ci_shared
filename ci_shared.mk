# ci_shared.mk - Shared CI checks for kalshi/zeus
#
# This file contains the common CI pipeline checks used by both repositories.
# Include this in your Makefile with: include ci_shared.mk

# Shared variables (can be overridden in individual Makefiles)
FORMAT_TARGETS ?= src tests
SHARED_SOURCE_ROOT ?= src
SHARED_TEST_ROOT ?= tests
SHARED_DOC_ROOT ?= .
SHARED_CODESPELL_IGNORE ?= config/codespell_ignore_words.txt
SHARED_PYRIGHT_TARGETS ?= $(SHARED_SOURCE_ROOT)
SHARED_PYLINT_TARGETS ?= $(SHARED_SOURCE_ROOT)
SHARED_PYTEST_TARGET ?= $(SHARED_TEST_ROOT)
SHARED_PYTEST_COV_TARGET ?= $(SHARED_SOURCE_ROOT)
SHARED_PYTEST_THRESHOLD ?= 80
SHARED_PYTEST_EXTRA ?=
COMPLEXITY_GUARD_PATH ?= scripts/complexity_guard.py
COMPLEXITY_GUARD_ARGS ?= --root $(SHARED_SOURCE_ROOT) --max-cyclomatic 10 --max-cognitive 15
MODULE_GUARD_ARGS ?= --root $(SHARED_SOURCE_ROOT) --max-module-lines 400
FUNCTION_GUARD_ARGS ?= --root $(SHARED_SOURCE_ROOT) --max-function-lines 80
METHOD_COUNT_GUARD_ARGS ?= --root $(SHARED_SOURCE_ROOT) --max-public-methods 15 --max-total-methods 25
PYLINT_ARGS ?=

PYTEST_NODES ?= 7
PYTHON ?= python
# MAX_CLASS_LINES moved to config/ci_config.json

export PYTHONDONTWRITEBYTECODE=1

# Shared CI check pipeline
.PHONY: shared-checks
shared-checks:
	@echo "Running shared CI checks..."
	isort --profile black $(FORMAT_TARGETS)
	black $(FORMAT_TARGETS)
	codespell --skip=".git,artifacts,models,node_modules,logs,htmlcov,*.json,*.csv" --quiet-level=2 --ignore-words=$(SHARED_CODESPELL_IGNORE)
	vulture $(FORMAT_TARGETS) --min-confidence 80
	deptry --config pyproject.toml $(FORMAT_TARGETS)
	$(PYTHON) -m ci_tools.scripts.policy_guard
	$(PYTHON) -m ci_tools.scripts.data_guard
	$(PYTHON) -m ci_tools.scripts.structure_guard --root $(SHARED_SOURCE_ROOT)
	$(PYTHON) $(COMPLEXITY_GUARD_PATH) $(COMPLEXITY_GUARD_ARGS)
	$(PYTHON) -m ci_tools.scripts.module_guard $(MODULE_GUARD_ARGS)
	$(PYTHON) -m ci_tools.scripts.function_size_guard $(FUNCTION_GUARD_ARGS)
	$(PYTHON) -m ci_tools.scripts.inheritance_guard --root $(SHARED_SOURCE_ROOT) --max-depth 2
	$(PYTHON) -m ci_tools.scripts.method_count_guard $(METHOD_COUNT_GUARD_ARGS)
	$(PYTHON) -m ci_tools.scripts.dependency_guard --root $(SHARED_SOURCE_ROOT) --max-instantiations 5
	$(PYTHON) -m ci_tools.scripts.unused_module_guard --root $(SHARED_SOURCE_ROOT) --strict
	$(PYTHON) -m ci_tools.scripts.documentation_guard --root $(SHARED_DOC_ROOT)
	ruff check --target-version=py310 --fix $(SHARED_SOURCE_ROOT) $(SHARED_TEST_ROOT)
	pyright --warnings $(SHARED_PYRIGHT_TARGETS)
	pylint -j $(PYTEST_NODES) $(PYLINT_ARGS) $(SHARED_PYLINT_TARGETS)
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	pytest -n $(PYTEST_NODES) $(SHARED_PYTEST_TARGET) --cov=$(SHARED_PYTEST_COV_TARGET) --cov-fail-under=$(SHARED_PYTEST_THRESHOLD) $(SHARED_PYTEST_EXTRA)
	$(PYTHON) -m ci_tools.scripts.coverage_guard --threshold 80 --data-file "$(CURDIR)/.coverage"
	$(PYTHON) -m compileall $(SHARED_SOURCE_ROOT) $(SHARED_TEST_ROOT)
	@echo "✅ All shared CI checks passed!"
