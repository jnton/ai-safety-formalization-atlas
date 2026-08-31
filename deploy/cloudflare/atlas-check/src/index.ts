import { Container, getRandom } from "@cloudflare/containers";

const INSTANCE_COUNT = 2;
const MAX_BODY_BYTES = 1_048_576;

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
      headers.set("content-length", String(body.byteLength));

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
