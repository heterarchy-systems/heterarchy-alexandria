.PHONY: python_ci rust_rules rust_fmt rust_check rust_test rust_ci ci runtime_revision runtime_rebuild

python_ci:
	cargo xtask python-ci

rust_rules:
	cargo xtask rules

rust_fmt:
	cargo xtask fmt

rust_check:
	cargo xtask check

rust_test:
	cargo xtask test

rust_ci:
	cargo xtask ci

ci: python_ci rust_ci


runtime_revision:
	@set -eu; \
	paths="backend/Dockerfile backend/pyproject.toml backend/uv.lock backend/alembic.ini backend/app backend/migrations native/Cargo.toml native/Cargo.lock native/crates native/xtask"; \
	untracked="$$(git ls-files --others --exclude-standard -- $$paths)"; \
	if git diff --quiet HEAD -- $$paths && [ -z "$$untracked" ]; then \
		git rev-parse HEAD; \
		exit 0; \
	fi; \
	{ \
		git rev-parse HEAD; \
		git diff --binary HEAD -- $$paths; \
		for path in $$untracked; do printf '%s\n' "$$path"; git hash-object "$$path"; done; \
	} | shasum -a 256 | awk '{print "worktree-" substr($$1, 1, 24)}'

runtime_rebuild:
	@set -eu; \
	revision="$$( $(MAKE) --no-print-directory runtime_revision )"; \
	timestamp="$$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
	echo "runtime revision: $$revision"; \
	ALEXANDRIA_BUILD_REVISION="$$revision" ALEXANDRIA_BUILD_TIMESTAMP="$$timestamp" \
		docker compose build alexandria-backend alexandria-maintenance-worker; \
	docker compose up -d --no-build --force-recreate alexandria-backend alexandria-maintenance-worker
