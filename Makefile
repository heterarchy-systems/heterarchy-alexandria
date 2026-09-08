.PHONY: rust_toolchain python_ci rust_rules rust_fmt rust_check rust_test rust_ci ci runtime_revision runtime_rebuild

PYTHONPYCACHEPREFIX ?= $(or $(XDG_CACHE_HOME),$(HOME)/.cache)/heterarchy-alexandria/pycache
export PYTHONPYCACHEPREFIX

RUST_TOOLCHAIN ?= 1.98.0
RUSTUP := $(shell command -v rustup 2>/dev/null)
ifeq ($(strip $(RUSTUP)),)
RUSTUP := $(wildcard $(HOME)/.cargo/bin/rustup)
endif

ifneq ($(strip $(RUSTUP)),)
RUST_CARGO := env -u RUSTC -u RUSTC_WRAPPER -u RUSTC_WORKSPACE_WRAPPER -u CARGO_BUILD_RUSTC -u CARGO_BUILD_RUSTC_WRAPPER PATH="$$(dirname "$$( $(RUSTUP) which --toolchain $(RUST_TOOLCHAIN) rustc )"):$${PATH}" RUSTC="$$( $(RUSTUP) which --toolchain $(RUST_TOOLCHAIN) rustc )" $(RUSTUP) run $(RUST_TOOLCHAIN) cargo

rust_toolchain:
	@if ! $(RUSTUP) run $(RUST_TOOLCHAIN) rustc --version >/dev/null 2>&1; then \
		$(RUSTUP) toolchain install $(RUST_TOOLCHAIN) --profile minimal; \
	fi
	@$(RUSTUP) component add --toolchain $(RUST_TOOLCHAIN) rustfmt clippy >/dev/null
else
RUST_CARGO := cargo

rust_toolchain:
	@set -eu; \
	version="$$(rustc --version | awk '{print $$2}')"; \
	major="$${version%%.*}"; \
	rest="$${version#*.}"; \
	minor="$${rest%%.*}"; \
	if [ "$$major" -lt 1 ] || { [ "$$major" -eq 1 ] && [ "$$minor" -lt 98 ]; }; then \
		echo "Rust >= 1.98.0 is required; found rustc $$version and rustup is unavailable." >&2; \
		exit 2; \
	fi
endif

python_ci: rust_toolchain
	$(RUST_CARGO) xtask python-ci

rust_rules: rust_toolchain
	$(RUST_CARGO) xtask rules

rust_fmt: rust_toolchain
	$(RUST_CARGO) xtask fmt

rust_check: rust_toolchain
	$(RUST_CARGO) xtask check

rust_test: rust_toolchain
	$(RUST_CARGO) xtask test

rust_ci: rust_toolchain
	$(RUST_CARGO) xtask ci

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
