.PHONY: format lint type test policy check

# Override shared defaults for this repository
FORMAT_TARGETS = ci_tools scripts
SHARED_SOURCE_ROOT = ci_tools
SHARED_TEST_ROOT = tests
SHARED_DOC_ROOT = .
SHARED_CODESPELL_IGNORE = ci_tools/config/codespell_ignore_words.txt
SHARED_PYRIGHT_TARGETS = ci_tools
SHARED_PYLINT_TARGETS = ci_tools
SHARED_PYTEST_TARGET = tests
SHARED_PYTEST_COV_TARGET = ci_tools
SHARED_PYTEST_THRESHOLD = 80
SHARED_PYTEST_EXTRA = --strict-markers --cov-report=term
COMPLEXITY_GUARD_ARGS = --root $(SHARED_SOURCE_ROOT) --max-cyclomatic 10 --max-cognitive 15
MODULE_GUARD_ARGS = --root $(SHARED_SOURCE_ROOT) --max-module-lines 400
FUNCTION_GUARD_ARGS = --root $(SHARED_SOURCE_ROOT) --max-function-lines 80
METHOD_COUNT_GUARD_ARGS = --root $(SHARED_SOURCE_ROOT) --max-public-methods 15 --max-total-methods 25

include ci_shared.mk

PYLINT_ARGS = --fail-under=9.0
SHARED_PYLINT_TARGETS = ci_tools tests/test_*.py tests/conftest.py

# Convenience passthrough targets (optional for local workflows).
format:
	isort --profile black $(FORMAT_TARGETS)
	black $(FORMAT_TARGETS)

lint:
	$(PYTHON) -m compileall $(FORMAT_TARGETS)
	ruff check $(FORMAT_TARGETS)
	pyright $(SHARED_PYRIGHT_TARGETS)
	pylint -j $(PYTEST_NODES) $(SHARED_PYLINT_TARGETS)

type:
	pyright $(SHARED_PYRIGHT_TARGETS)

test:
	pytest $(SHARED_PYTEST_TARGET) --cov=$(SHARED_PYTEST_COV_TARGET) --cov-fail-under=$(SHARED_PYTEST_THRESHOLD) $(SHARED_PYTEST_EXTRA)

policy:
	$(PYTHON) -m ci_tools.scripts.policy_guard

check: shared-checks ## Run format checks, static analysis, and tests.
