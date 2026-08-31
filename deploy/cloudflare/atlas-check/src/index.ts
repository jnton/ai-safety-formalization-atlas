import { Container, getRandom } from "@cloudflare/containers";

const INSTANCE_COUNT = 2;
const MAX_BODY_BYTES = 1_048_576;
const BODY_LENGTH_HEADER = "x-atlas-body-length";

export class AtlasCheckContainer extends Container {
  defaultPort = 8080;
  sleepAfter = "15m";
  enableInternet = false;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
    },
  });
}

function preflightResponse(): Response {
  return new Response(null, {
    status: 204,
    headers: {
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type",
      "access-control-max-age": "86400",
    },
  });
}

async function proxyToChecker(request: Request, env: any): Promise<Response> {
  const container = await getRandom(env.ATLAS_CHECK, INSTANCE_COUNT);
  return container.fetch(request);
}

export default {
  async fetch(request: Request, env: any): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS" && url.pathname.startsWith("/api/")) {
      return preflightResponse();
    }

    if (url.pathname === "/api/check") {
      if (request.method !== "POST") {
        return jsonResponse(405, {
          schema: "atlas-check-api/1",
          error: { code: "method_not_allowed", message: "Use POST /api/check." },
        });
      }

      // Buffer once at the Worker boundary so oversized models are rejected
      // before a container is started. The private length header is rewritten
      // here rather than trusted from the public request, so the container can
      // read the body correctly regardless of the HTTP transfer encoding used
      // between Workers and Containers.
      const body = await request.arrayBuffer();
      if (body.byteLength > MAX_BODY_BYTES) {
        return jsonResponse(413, {
          schema: "atlas-check-api/1",
          error: {
            code: "request_too_large",
            message: `Request body exceeds ${MAX_BODY_BYTES} bytes.`,
          },
        });
      }

      const headers = new Headers(request.headers);
      headers.set(BODY_LENGTH_HEADER, String(body.byteLength));

      return proxyToChecker(
        new Request(request.url, {
          method: "POST",
          headers,
          body,
        }),
        env,
      );
    }

    if (url.pathname === "/api/health" || url.pathname === "/api/schema") {
      if (request.method !== "GET") {
        return jsonResponse(405, {
          schema: "atlas-check-api/1",
          error: { code: "method_not_allowed", message: "Use GET for this endpoint." },
        });
      }
      return proxyToChecker(request, env);
    }

    return jsonResponse(404, {
      schema: "atlas-check-api/1",
      error: {
        code: "not_found",
        message: "Available endpoints: GET /api/health, GET /api/schema, POST /api/check.",
      },
    });
  },
};
