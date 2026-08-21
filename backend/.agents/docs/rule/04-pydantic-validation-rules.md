# Pydantic v2 Validation Rules

## Canonical Base Models

Production boundary schemas use only the repository canonical bases in `app.shared.schemas.common_schemas`.

- named-field models inherit `StrictSchemaModel`;
- top-level root/collection contracts inherit `StrictRootSchemaModel`;
- direct `pydantic.BaseModel` / `pydantic.RootModel` inheritance is forbidden outside the canonical base module.

Canonical configuration is not optional:

```python
ConfigDict(
    extra="forbid",
    frozen=True,
    strict=True,
    use_enum_values=True,
    validate_default=True,
)
```

`StrictRootSchemaModel` uses the same contract except `extra`, which RootModel does not support.

Do not introduce a second base-model hierarchy with weaker settings.

## Strict JSON Semantics

Strict Python-mode and strict JSON-mode validation intentionally differ for protocol encodings such as enum strings, UUIDs and datetimes.

FastAPI pre-decodes JSON before ordinary parameter validation. When that would lose Pydantic strict JSON semantics, route bodies must use the shared raw-body dependency and `model_validate_json()`.

Do not solve this by disabling `strict=True` or adding broad before-validators that reintroduce coercion.

Provider/model output that is itself JSON should likewise be validated with `model_validate_json()` rather than `loads_json(...)` followed by Python-mode `model_validate(...)` when JSON-mode semantics are required.

## Field Metadata

Production schema modules do not call `pydantic.Field()` directly.

Externally visible fields use the repository `described_field()` helper and every description must be non-empty and meaningful.

`described_field()` is metadata only. It must not accept `default` or `default_factory`. Domain/API defaults remain explicit assignment values on the model field.

Preferred form:

```python
name: Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=200),
    described_field("Stable display name for the provider."),
]

enabled: Annotated[
    bool,
    described_field("Whether this provider may be selected."),
] = True
```

String constraints belong in `StringConstraints(strict=True, ...)` rather than hidden coercive validators.

## Collection Contracts

Top-level HTTP/MCP collections use named RootModels instead of anonymous `list[Item]`, `tuple[Item, ...]`, or raw mapping contracts. Nested collections may remain normal typed fields when their meaning belongs to the containing schema.

Prefer immutable tuples for internal/read-only collections. If the public JSON contract intentionally uses a list, normalize tuple-to-list explicitly at the mapper/interface boundary rather than relying on Pydantic coercion.

## Extra Fields and Defaults

Unknown named-model fields are rejected through `extra="forbid"`.

Defaults are validated through `validate_default=True`. A default therefore must satisfy the same strict contract as an externally supplied value.

Do not use a default merely to make a required API field convenient for a caller.

## External Raw Mapping

Unknown external mapping data may first be represented by a bounded TypedDict/JSONValue parser, but it must be normalized and validated before entering the application/domain surface.

Do not use `cast()` as a replacement for runtime validation.

## Legacy APIs

The following are forbidden in production code:

- `pydantic.v1` imports;
- Pydantic v1 `@validator` / `@root_validator` APIs;
- direct `BaseModel` / `RootModel` subclasses outside the shared canonical base;
- direct `Field()` calls outside the canonical field helper;
- configuration weakening to silence modernization failures.

## Verification

The mechanical schema verifier must fail closed when canonical base settings, direct Pydantic inheritance, direct `Field()`, field descriptions, or banned legacy APIs violate this contract. Production code must pass the verifier; do not establish a permanent violation baseline.
