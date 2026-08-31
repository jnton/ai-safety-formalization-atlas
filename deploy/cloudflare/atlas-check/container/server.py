#!/usr/bin/env python3

import json
import os
import re
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

API_SCHEMA = "atlas-check-api/1"
INPUT_SCHEMA = "atlas-check/1"
CHECKER = Path(os.getenv("ATLAS_CHECK_BINARY", "/usr/local/bin/atlas-check"))
PORT = int(os.getenv("PORT", "8080"))
MAX_BODY_BYTES = int(os.getenv("ATLAS_CHECK_MAX_BODY_BYTES", "1048576"))
TIMEOUT_SECONDS = float(os.getenv("ATLAS_CHECK_TIMEOUT_SECONDS", "20"))


def compact_error(message: str) -> str:
    return " ".join(message.strip().split())


def summarize_output(lines: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {}

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("verdict:"):
            summary["verdict"] = stripped.removeprefix("verdict:").strip()
        elif stripped.startswith("witness:"):
            summary["witness"] = stripped.removeprefix("witness:").strip()
        elif stripped.startswith("worst ambiguity:"):
            match = re.match(r"worst ambiguity:\s*(\d+)", stripped)
            if match:
                summary["worstAmbiguity"] = int(match.group(1))
        elif stripped.startswith("certified by:"):
            summary["certifiedBy"] = stripped.removeprefix("certified by:").strip()
        elif stripped.startswith("certified by "):
            summary["certifiedBy"] = stripped.removeprefix("certified by ").strip()
        elif stripped.startswith("weak inference (Definition 3):"):
            summary["weakInference"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("blockwise collision at value"):
            summary["blockwiseCollision"] = stripped

    return summary


class Handler(BaseHTTPRequestHandler):
    server_version = "AtlasCheckHTTP/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"atlas-check-http: {self.address_string()} - {fmt % args}")

    def _send_json(self, status: int, payload: dict[str, Any], *, cache: str = "no-store") -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", cache)
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if not self.path.startswith("/api/"):
            self._send_json(404, {"schema": API_SCHEMA, "error": {"code": "not_found", "message": "Not found."}})
            return

        self.send_response(204)
        self.send_header("content-length", "0")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET,POST,OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("access-control-max-age", "86400")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/health":
            executable = CHECKER.is_file() and os.access(CHECKER, os.X_OK)
            self._send_json(
                200 if executable else 503,
                {
                    "schema": API_SCHEMA,
                    "status": "ok" if executable else "unavailable",
                    "checkerExecutable": executable,
                    "inputSchema": INPUT_SCHEMA,
                },
            )
            return

        if self.path == "/api/schema":
            self._send_json(
                200,
                {
                    "schema": API_SCHEMA,
                    "inputSchema": INPUT_SCHEMA,
                    "kinds": ["knowability", "coalition", "device", "variety"],
                    "endpoints": {
                        "health": {"method": "GET", "path": "/api/health"},
                        "schema": {"method": "GET", "path": "/api/schema"},
                        "check": {"method": "POST", "path": "/api/check"},
                    },
                    "limits": {
                        "maxBodyBytes": MAX_BODY_BYTES,
                        "timeoutSeconds": TIMEOUT_SECONDS,
                    },
                },
                cache="public, max-age=300",
            )
            return

        self._send_json(
            404,
            {
                "schema": API_SCHEMA,
                "error": {
                    "code": "not_found",
                    "message": "Available endpoints: GET /api/health, GET /api/schema, POST /api/check.",
                },
            },
        )

    def do_POST(self) -> None:
        if self.path != "/api/check":
            self._send_json(404, {"schema": API_SCHEMA, "error": {"code": "not_found", "message": "Not found."}})
            return

        content_type = self.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json" and not content_type.endswith("+json"):
            self._send_json(
                415,
                {
                    "schema": API_SCHEMA,
                    "error": {"code": "unsupported_media_type", "message": "Use Content-Type: application/json."},
                },
            )
            return

        length_header = self.headers.get("content-length")
        if length_header is None:
            self._send_json(
                411,
                {"schema": API_SCHEMA, "error": {"code": "length_required", "message": "Content-Length is required."}},
            )
            return

        try:
            content_length = int(length_header)
        except ValueError:
            self._send_json(400, {"schema": API_SCHEMA, "error": {"code": "invalid_length", "message": "Invalid Content-Length."}})
            return

        if content_length < 0 or content_length > MAX_BODY_BYTES:
            self._send_json(
                413,
                {
                    "schema": API_SCHEMA,
                    "error": {
                        "code": "request_too_large",
                        "message": f"Request body exceeds {MAX_BODY_BYTES} bytes.",
                    },
                },
            )
            return

        raw = self.rfile.read(content_length)
        try:
            model = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(
                400,
                {"schema": API_SCHEMA, "error": {"code": "invalid_json", "message": compact_error(str(exc))}},
            )
            return

        if not isinstance(model, dict):
            self._send_json(
                400,
                {"schema": API_SCHEMA, "error": {"code": "invalid_model", "message": "The request body must be a JSON object."}},
            )
            return

        if not CHECKER.is_file() or not os.access(CHECKER, os.X_OK):
            self._send_json(
                503,
                {"schema": API_SCHEMA, "error": {"code": "checker_unavailable", "message": "atlas-check is not executable."}},
            )
            return

        with tempfile.TemporaryDirectory(prefix="atlas-check-") as tmpdir:
            model_path = Path(tmpdir) / "model.json"
            model_path.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")

            try:
                completed = subprocess.run(
                    [str(CHECKER), str(model_path)],
                    text=True,
                    capture_output=True,
                    timeout=TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                self._send_json(
                    504,
                    {
                        "schema": API_SCHEMA,
                        "inputSchema": INPUT_SCHEMA,
                        "kind": model.get("kind"),
                        "error": {
                            "code": "checker_timeout",
                            "message": f"atlas-check exceeded the {TIMEOUT_SECONDS:g}s backend limit.",
                        },
                    },
                )
                return
            except OSError as exc:
                self._send_json(
                    500,
                    {"schema": API_SCHEMA, "error": {"code": "checker_start_failed", "message": compact_error(str(exc))}},
                )
                return

        stdout = completed.stdout.rstrip("\n")
        stderr = completed.stderr.replace(str(model_path), "<model>").strip()

        if completed.returncode == 0:
            lines = stdout.splitlines() if stdout else []
            self._send_json(
                200,
                {
                    "schema": API_SCHEMA,
                    "inputSchema": INPUT_SCHEMA,
                    "kind": model.get("kind"),
                    "ok": True,
                    "result": {
                        "summary": summarize_output(lines),
                        "lines": lines,
                        "text": stdout,
                    },
                },
            )
            return

        if completed.returncode == 1:
            message = compact_error(stderr) or "atlas-check rejected the model."
            if message.startswith("atlas-check:"):
                message = message.removeprefix("atlas-check:").strip()
            self._send_json(
                422,
                {
                    "schema": API_SCHEMA,
                    "inputSchema": INPUT_SCHEMA,
                    "kind": model.get("kind"),
                    "ok": False,
                    "error": {"code": "checker_rejected_model", "message": message},
                },
            )
            return

        self._send_json(
            500,
            {
                "schema": API_SCHEMA,
                "ok": False,
                "error": {
                    "code": "checker_failed",
                    "message": compact_error(stderr) or f"atlas-check exited with status {completed.returncode}.",
                },
            },
        )


if __name__ == "__main__":
    print(f"atlas-check-http: listening on 0.0.0.0:{PORT}; checker={CHECKER}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
