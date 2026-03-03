# ============================================================
#  LexAudit — Multi-stage Docker build
#  Stage 1: Build Rust WASM applets
#  Stage 2: Python runtime (FastAPI + agent)
# ============================================================

# --- Stage 1: Rust WASM builder ---
FROM rust:1.82-slim AS wasm-builder

RUN rustup target add wasm32-unknown-unknown

WORKDIR /build
COPY rust_applets/ ./rust_applets/

# wadk-sdk Rust deps are referenced via relative path in Cargo.toml
# In Docker, we copy them alongside
COPY wadk-sdk/ ./wadk-sdk/

WORKDIR /build/rust_applets
RUN cargo build --release --target wasm32-unknown-unknown \
    && mkdir -p /wasm \
    && cp target/wasm32-unknown-unknown/release/clause_extractor.wasm /wasm/ \
    && cp target/wasm32-unknown-unknown/release/risk_scorer.wasm /wasm/


# --- Stage 2: Python runtime ---
FROM python:3.13-slim AS runtime

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Weilchain SDK (if bundled)
COPY wadk-sdk/adk/python/weil_wallet /tmp/weil_wallet
COPY wadk-sdk/adk/python/weil_ai /tmp/weil_ai
RUN pip install --no-cache-dir /tmp/weil_wallet /tmp/weil_ai && rm -rf /tmp/weil_*

# Application code
COPY src/ ./src/
COPY main.py server.py ./
COPY web/ ./web/
COPY contracts/ ./contracts/
COPY docs/ ./docs/
COPY scripts/ ./scripts/

# WASM artifacts from builder stage
COPY --from=wasm-builder /wasm/ ./src/applets/wasm/

# WIDL definitions
COPY src/applets/*.widl ./src/applets/

# Create runs directory
RUN mkdir -p .runs

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

EXPOSE 8000

# Default: run FastAPI server
CMD ["python", "server.py"]
