# syntax=docker/dockerfile:1.7

FROM docker.io/library/debian:bookworm-slim AS builder

ARG DEBIAN_FRONTEND=noninteractive
ENV HOME=/root
ENV PATH=/root/.elan/bin:${PATH}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        python3 \
        zstd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY . .

# The repository itself pins Lean in lean-toolchain and all package revisions in
# lake-manifest.json. Do not run `lake update`: that would change the environment
# being deployed instead of reproducing the committed one.
RUN curl -fsSL https://elan.lean-lang.org/elan-init.sh \
      | sh -s -- -y --default-toolchain none \
    && lake --version \
    && lake exe cache get \
    && lake build atlas-check \
    && test -x .lake/build/bin/atlas-check

# Lake executables use the Lean toolchain shared runtime on Linux. Copy only the
# shared objects needed at runtime rather than shipping the source tree, Mathlib
# cache, compiler, or .olean files in the production image.
RUN set -eux; \
    lean_bin="$(elan which lean)"; \
    lean_prefix="$(dirname "$(dirname "$lean_bin")")"; \
    mkdir -p /runtime/lean-lib; \
    find "$lean_prefix/lib/lean" -maxdepth 1 -type f \( -name '*.so' -o -name '*.so.*' \) \
      -exec cp -a {} /runtime/lean-lib/ \; \
    ldd .lake/build/bin/atlas-check


FROM docker.io/library/debian:bookworm-slim AS runtime

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgcc-s1 \
        libgmp10 \
        libstdc++6 \
        libuv1 \
        python3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home atlas

COPY --from=builder /workspace/.lake/build/bin/atlas-check /usr/local/bin/atlas-check
COPY --from=builder /runtime/lean-lib/ /usr/local/lib/lean/
COPY deploy/cloudflare/atlas-check/container/server.py /opt/atlas/server.py
COPY lean-toolchain /opt/atlas/lean-toolchain

ENV LD_LIBRARY_PATH=/usr/local/lib/lean
ENV PORT=8080
ENV ATLAS_CHECK_BINARY=/usr/local/bin/atlas-check
ENV ATLAS_CHECK_MAX_BODY_BYTES=1048576
ENV ATLAS_CHECK_TIMEOUT_SECONDS=20

# Fail the image build if the stripped-down runtime image cannot actually run
# the compiled checker and its Lean shared libraries.
RUN printf '%s\n' \
      '{"schema":"atlas-check/1","kind":"knowability","states":2,"observation":[0,0],"property":[0,1]}' \
      > /tmp/smoke.json \
    && /usr/local/bin/atlas-check /tmp/smoke.json | grep -q 'verdict: NOT KNOWABLE' \
    && rm /tmp/smoke.json

USER atlas
EXPOSE 8080
ENTRYPOINT ["python3", "/opt/atlas/server.py"]
