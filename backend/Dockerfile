ARG ALEXANDRIA_BUILD_REVISION
ARG ALEXANDRIA_BUILD_TIMESTAMP=unknown

FROM rust:1.97-slim-trixie AS native-builder

WORKDIR /src

# FastEmbed/ORT and onig include native C/C++ components. ORT's downloaded
# static Linux archive requires glibc 2.38+ symbols, so keep builder/runtime on
# Debian Trixie and install the minimal C++ toolchain required by the final
# PyO3 shared-library link.
RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*

# The runtime image is CPython 3.13. PyO3 can configure Unix extension-module
# cross builds without a target libpython when the target Python version is explicit.
ENV PYO3_CROSS=1 \
    PYO3_CROSS_PYTHON_VERSION=3.13 \
    PYO3_BUILD_EXTENSION_MODULE=1

COPY native/Cargo.toml native/Cargo.lock ./native/
COPY native/crates ./native/crates
COPY native/xtask ./native/xtask

# Warm the complete native dependency graph, including the downloaded ORT artifact,
# without tying expensive dependency layers to deployment provenance.
RUN cargo build \
    --release \
    --locked \
    --manifest-path native/Cargo.toml \
    -p heterarchy-alexandria-py

# Only the final PyO3 crate relink depends on the source/deployment revision.
# Missing provenance is a build failure instead of silently producing an unsealed image.
ARG ALEXANDRIA_BUILD_REVISION
RUN case "${ALEXANDRIA_BUILD_REVISION}" in \
        ""|unknown|unset|none) echo "ALEXANDRIA_BUILD_REVISION must identify the built source tree" >&2; exit 2 ;; \
    esac \
    && ALEXANDRIA_BUILD_REVISION="${ALEXANDRIA_BUILD_REVISION}" cargo build \
        --release \
        --locked \
        --manifest-path native/Cargo.toml \
        -p heterarchy-alexandria-py

FROM python:3.13-slim-trixie AS runtime

ARG ALEXANDRIA_BUILD_REVISION
ARG ALEXANDRIA_BUILD_TIMESTAMP

LABEL org.opencontainers.image.revision=${ALEXANDRIA_BUILD_REVISION}
LABEL org.opencontainers.image.created=${ALEXANDRIA_BUILD_TIMESTAMP}

ENV SERVICE_RUNTIME_REVISION=${ALEXANDRIA_BUILD_REVISION} \
    SERVICE_RUNTIME_EXPECTED_REVISION=${ALEXANDRIA_BUILD_REVISION} \
    SERVICE_RUNTIME_BUILD_TIMESTAMP=${ALEXANDRIA_BUILD_TIMESTAMP}

WORKDIR /app

# Install uv without pip.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates libstdc++6 \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:$PATH"

COPY backend/pyproject.toml backend/uv.lock* ./
COPY backend/alembic.ini ./alembic.ini
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY --from=native-builder \
    /src/native/target/release/libheterarchy_alexandria_native.so \
    /tmp/heterarchy_alexandria_native.so

RUN uv sync --locked \
    && native_site="$('/app/.venv/bin/python' -c 'import sysconfig; print(sysconfig.get_paths()["platlib"])')" \
    && cp /tmp/heterarchy_alexandria_native.so "${native_site}/heterarchy_alexandria_native.so" \
    && /app/.venv/bin/python -c "import heterarchy_alexandria_native as native; assert native.compute_contract_version() == 1"

CMD ["sh", "-c", "/app/.venv/bin/alembic upgrade head && exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"]
