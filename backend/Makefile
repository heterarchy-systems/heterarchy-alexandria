.PHONY: install-local format_check type_checking cli_smoke guardrails test ci benchmark_check mechanical_check

install-local:
	uv sync --no-editable --reinstall-package heterarchy-alexandria

format_check:
	uv run --no-editable ruff format --check . ../.agents/python_dev_harness
	uv run --no-editable ruff check . ../.agents/python_dev_harness

type_checking:
	uv run --no-editable pyrefly check

cli_smoke:
	uv run --isolated --with . heterarchy-alexandria --help >/dev/null

guardrails:
	uv run --no-editable pytest -q --confcutdir=tests/shared/guardrails tests/shared/guardrails

benchmark_check:
	uv run --no-editable pytest -q --confcutdir=tests/benchmark_tools tests/benchmark_tools
	uv run --no-editable python -m benchmarks.context_rag_api_benchmark --help >/dev/null
	uv run --no-editable python -m benchmarks.mcp_readonly_benchmark --help >/dev/null

test:
	./scripts/run-postgres-tests.sh -q

mechanical_check:
	uv run python ../.agents/python_dev_harness/verify_mechanical_contracts.py

ci: format_check type_checking cli_smoke guardrails test benchmark_check mechanical_check
