# Cloudflare `atlas-check` backend

This deployment exposes the existing `atlas-check` executable as a narrow HTTP API on Cloudflare Containers. The repository remains the source of truth: the Docker image is built from the checked-out Atlas tree, uses the committed `lean-toolchain` and `lake-manifest.json`, downloads the Mathlib cache, and builds the existing `atlas-check` target.

## Architecture

```text
client
  |
  v
Cloudflare Worker
  |
  | getRandom(ATLAS_CHECK, 2)
  v
Cloudflare Container
  |
  v
Python stdlib HTTP wrapper
  |
  v
/usr/local/bin/atlas-check <temporary-model.json>
```

The production container has outbound internet disabled. The HTTP wrapper never accepts a command or Lean source: the only executable it starts is the fixed `atlas-check` binary.

## API

### `GET /api/health`

Checks that the compiled checker exists and is executable.

### `GET /api/schema`

Returns API version, accepted Atlas input schema, supported checker kinds, and backend limits.

### `POST /api/check`

Send the same JSON document that the CLI accepts.

```bash
curl -sS https://YOUR-WORKER.workers.dev/api/check \
  -H 'content-type: application/json' \
  --data '{
    "schema": "atlas-check/1",
    "kind": "knowability",
    "states": 4,
    "observation": [0,0,1,1],
    "property": [0,1,0,1]
  }'
```

A successful response is wrapped in `atlas-check-api/1` while preserving the checker's complete stdout:

```json
{
  "schema": "atlas-check-api/1",
  "inputSchema": "atlas-check/1",
  "kind": "knowability",
  "ok": true,
  "result": {
    "summary": {
      "verdict": "NOT KNOWABLE",
      "worstAmbiguity": 2,
      "certifiedBy": "AISafetyAtlas.Knowledge.Check.not_knowable_of_findCollision_eq_some"
    },
    "lines": ["..."],
    "text": "..."
  }
}
```

The `summary` is convenience metadata parsed from the human-readable CLI output. `lines` and `text` are the authoritative backend representation of what the current `atlas-check` executable printed; this avoids silently inventing a second checker semantics in the web layer.

Invalid models that the CLI rejects return HTTP `422`. Invalid HTTP/JSON input returns `4xx`. A checker run exceeding the backend timeout returns `504`.

## Backend limits

Defaults:

- request body: 1 MiB
- checker wall-clock timeout: 20 seconds
- two stateless Cloudflare Container instances
- `basic` container instance type

The container-side limits can be changed with `ATLAS_CHECK_MAX_BODY_BYTES` and `ATLAS_CHECK_TIMEOUT_SECONDS` if the deployment later needs different operational policy.

## Local development

Cloudflare Container local development requires Docker or another Docker-compatible engine.

```bash
cd deploy/cloudflare/atlas-check
npm install
npm run typecheck
npm run dev
```

Then:

```bash
curl http://localhost:8787/api/health
```

`wrangler dev` builds the Dockerfile using the repository root as its build context (`image_build_context: "../../.."`).

## Deploy

Cloudflare Containers require a Workers Paid plan.

```bash
cd deploy/cloudflare/atlas-check
npm install
npx wrangler login
npm run deploy
```

On deployment Wrangler builds and pushes the container image and deploys the Worker. The first container-backed request may be slower while an instance starts.

## Why this is separate from a future Lean server

This service deliberately exposes only `atlas-check`. It is stateless and accepts a constrained data format. A future interactive Lean/LSP service should use a separate Container class and stronger sandbox/session controls rather than broadening this endpoint into arbitrary code execution.
