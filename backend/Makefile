.PHONY: install-local format_check type_checking cli_smoke test ci benchmark_check mechanical_check

PYTHONPYCACHEPREFIX ?= $(or $(XDG_CACHE_HOME),$(HOME)/.cache)/heterarchy-alexandria/pycache
export PYTHONPYCACHEPREFIX

install-local:
	uv sync --no-editable --reinstall-package heterarchy-alexandria

format_check:
	uv run --no-editable ruff format --check .
	uv run --no-editable ruff check .

type_checking:
	uv run --no-editable pyrefly check

cli_smoke:
	uv run --isolated --with . heterarchy-alexandria --help >/dev/null

benchmark_check:
	uv run --no-editable pytest -q --confcutdir=tests/benchmark_tools tests/benchmark_tools
	uv run --no-editable python -m benchmarks.context_rag_api_benchmark --help >/dev/null
	uv run --no-editable python -m benchmarks.graph_ablation_suite --help >/dev/null
	uv run --no-editable python -m benchmarks.graph_production_closure_suite --help >/dev/null
	uv run --no-editable python -m benchmarks.memory_evaluation_suite --help >/dev/null
	uv run --no-editable python -m benchmarks.mcp_readonly_benchmark --help >/dev/null

test:
	./scripts/run-postgres-tests.sh

mechanical_check:
	uv run python scripts/verification/verify_contracts.py

ci: format_check type_checking cli_smoke test benchmark_check mechanical_check
