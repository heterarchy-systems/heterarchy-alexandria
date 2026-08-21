.PHONY: install-local format_check type_checking cli_smoke guardrails test ci mechanical_check

install-local:
	uv sync --no-editable --reinstall-package heterarchy-alexandria

format_check:
	uv run --no-editable ruff format --check .
	uv run --no-editable ruff check .

type_checking:
	uv run --no-editable pyrefly check

cli_smoke:
	uv run --isolated --with . heterarchy-alexandria --help >/dev/null

guardrails:
	uv run --no-editable pytest -q --confcutdir=tests/shared/guardrails tests/shared/guardrails

test:
	./scripts/run-postgres-tests.sh -q

mechanical_check:
	uv run python .agents/verify_mechanical_contracts.py

ci: format_check type_checking cli_smoke guardrails test mechanical_check
