# ci_shared.mk - Shared CI checks for kalshi/zeus
#
# This file contains the common CI pipeline checks used by both repositories.
# Include this in your Makefile with: include ci_shared.mk

# Shared variables (can be overridden in individual Makefiles)
FORMAT_TARGETS ?= src tests
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
	$(PYTHON) -m compileall src tests
	codespell --skip=".git,artifacts,models,node_modules,logs,htmlcov,*.json,*.csv" --quiet-level=2 --ignore-words=ci_shared/config/codespell_ignore_words.txt
	vulture $(FORMAT_TARGETS) --min-confidence 80
	deptry --config pyproject.toml $(FORMAT_TARGETS)
	$(PYTHON) -m ci_tools.scripts.policy_guard
	$(PYTHON) -m ci_tools.scripts.data_guard
	$(PYTHON) -m ci_tools.scripts.structure_guard
	$(PYTHON) ci_shared/scripts/complexity_guard.py --root src --max-cyclomatic 10 --max-cognitive 15
	$(PYTHON) -m ci_tools.scripts.module_guard --root src --max-module-lines 400
	$(PYTHON) -m ci_tools.scripts.function_size_guard --root src --max-function-lines 80
	$(PYTHON) -m ci_tools.scripts.inheritance_guard --root src --max-depth 2
	$(PYTHON) -m ci_tools.scripts.method_count_guard
	$(PYTHON) -m ci_tools.scripts.dependency_guard --root src --max-instantiations 5
	$(PYTHON) -m ci_tools.scripts.unused_module_guard --root src --strict
	$(PYTHON) -m ci_tools.scripts.documentation_guard --root .
	ruff check --target-version=py310 --fix src tests
	pyright src
	pylint -j $(PYTEST_NODES) src tests
	pytest -n $(PYTEST_NODES) tests/ --cov=src --cov-fail-under=80 --strict-markers --cov-report=term -W error
	$(PYTHON) -m ci_tools.scripts.coverage_guard --threshold 80 --data-file "$(CURDIR)/.coverage"
	@echo "✅ All shared CI checks passed!"
