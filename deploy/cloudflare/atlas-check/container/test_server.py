#!/usr/bin/env python3

import json
import os
import stat
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import server


class AtlasCheckHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.TemporaryDirectory(prefix="atlas-check-http-test-")
        checker = Path(cls.tmpdir.name) / "atlas-check-stub"
        checker.write_text(
            "#!/bin/sh\n"
            "if grep -q '\"kind\":\"reject\"' \"$1\"; then\n"
            "  echo 'atlas-check: deliberately rejected' >&2\n"
            "  exit 1\n"
            "fi\n"
            "cat <<'EOF'\n"
            "verdict: NOT KNOWABLE\n"
            "witness: states 0 and 1 share an observation and differ in the property\n"
            "worst ambiguity: 2 (one property value per observation is exact knowledge)\n"
            "certified by: AISafetyAtlas.Knowledge.Check.not_knowable_of_findCollision_eq_some\n"
            "EOF\n",
            encoding="utf-8",
        )
        checker.chmod(checker.stat().st_mode | stat.S_IXUSR)
        server.CHECKER = checker
        server.TIMEOUT_SECONDS = 2

        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.tmpdir.cleanup()

    def request(self, path: str, *, method: str = "GET", body: bytes | None = None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            data=body,
            headers={"content-type": "application/json"} if body is not None else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health(self) -> None:
        status, payload = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["schema"], "atlas-check-api/1")
        self.assertTrue(payload["checkerExecutable"])

    def test_schema(self) -> None:
        status, payload = self.request("/api/schema")
        self.assertEqual(status, 200)
        self.assertEqual(payload["inputSchema"], "atlas-check/1")
        self.assertIn("knowability", payload["kinds"])
        self.assertIn("variety", payload["kinds"])

    def test_successful_check(self) -> None:
        model = {
            "schema": "atlas-check/1",
            "kind": "knowability",
            "states": 2,
            "observation": [0, 0],
            "property": [0, 1],
        }
        status, payload = self.request(
            "/api/check",
            method="POST",
            body=json.dumps(model, separators=(",", ":")).encode(),
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["summary"]["verdict"], "NOT KNOWABLE")
        self.assertEqual(payload["result"]["summary"]["worstAmbiguity"], 2)
        self.assertIn("certifiedBy", payload["result"]["summary"])

    def test_checker_rejection_becomes_422(self) -> None:
        status, payload = self.request(
            "/api/check",
            method="POST",
            body=b'{"schema":"atlas-check/1","kind":"reject"}',
        )
        self.assertEqual(status, 422)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "checker_rejected_model")

    def test_invalid_json_becomes_400(self) -> None:
        status, payload = self.request("/api/check", method="POST", body=b"{")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_json")


if __name__ == "__main__":
    unittest.main()
