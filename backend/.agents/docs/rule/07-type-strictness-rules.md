# Type Strictness Rules

## Production Type Policy

Every production function and method declares a return type. Every parameter except `self` and `cls` has an explicit annotation. Public class fields are explicitly typed.

Bare `list`, `dict`, `tuple`, `set`, and other unparameterized collection annotations are forbidden.

## Any

`Any` is forbidden by default in production code.

A genuinely untyped third-party/framework seam may retain the narrowest possible use only when the exact source line is marked with:

```text
type-contract: allow-any
```

The marker is an explicit exceptional contract, not a debt-baseline mechanism. The value must be normalized immediately into TypedDict, Pydantic, dataclass, protocol, or another bounded type and must not propagate into application/repository public APIs.

Do not replace `Any` with `object` or `dict[str, object]` merely to evade the verifier.

## Optional and Omission

`T | None` means the domain value can actually be absent/null. It is not a convenience default.

For mapping shapes distinguish:

- absent key: `NotRequired[T]`;
- present nullable value: `T | None`;
- either: `NotRequired[T | None]`.

## Keyword-only Separators

Bare keyword-only separators (`*`) are forbidden by default. Functions should use normal positional-or-keyword parameters while callers may still pass them by name.

If Python signature ordering or an external/public protocol makes keyword-only semantics genuinely necessary, retain it only with the narrow marker:

```text
type-contract: allow-keyword-only
```

Do not create hundreds of exception markers as a modernization baseline. Refactor safe signatures and reserve the marker for real language/protocol constraints.

## Strict Boundary Types

Pydantic boundary models are strict globally through the canonical shared bases. Do not reintroduce implicit coercion to accommodate old callers.

Protocol discriminators, lifecycle states, scope/event kinds, booleans, numbers, UUID/datetime encodings and enums must cross boundaries according to the declared schema semantics. JSON-specific encodings use strict JSON-mode validation where appropriate.

## TypedDict and Dynamic JSON

Known mapping shapes use explicit TypedDict/Pydantic/dataclass contracts.

Truly dynamic JSON is limited to the repository `JSONValue` family and remains at transport/metadata seams. It does not spread into core service or repository APIs.

## cast

`cast()` is not a validator and must not be used to hide an unresolved type mismatch.

Acceptable uses are limited to cases where a runtime check or library typing defect already proves the invariant. Prefer explicit mappers/parsers when converting between boundary, domain and persistence representations.

## type: ignore and Suppressions

Broad ignores are forbidden. A necessary suppression is as narrow as possible, includes the concrete checker code when supported, and documents the external typing defect/invariant.

Do not weaken Pyrefly or Ruff settings to make modernization pass.

## Collections

- immutable/read-only sequence owned by the model: `tuple[T, ...]`;
- mutation required: `list[T]`;
- uniqueness semantic: `set[T]` or a named root schema;
- read-only mapping interface: `Mapping[K, V]`;
- mutation required: `dict[K, V]`.

Top-level API/MCP collections are named Pydantic root schemas.

## Verification

The mechanical type verifier scans production code and fails on missing parameter/return annotations, bare collection annotations, unapproved `Any`, and unapproved bare keyword-only separators.

No permanent violation count or baseline file is allowed. Production source must become green under the rule itself.
