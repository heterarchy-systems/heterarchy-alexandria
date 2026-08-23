.PHONY: python_ci rust_rules rust_fmt rust_check rust_test rust_ci ci

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
