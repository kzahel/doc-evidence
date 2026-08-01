from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from doc_evidence.api.app import create_app
from doc_evidence.contracts.desktop import (
    DESKTOP_ORIGIN,
    DESKTOP_PROTOCOL_VERSION,
    DesktopControlHandshake,
    DesktopReady,
    create_desktop_handshake,
)
from doc_evidence.desktop_sidecar import (
    DESKTOP_HOME_ENV,
    HOST_CONTROL_TOKEN_ENV,
    RUNTIME_TOKEN_ENV,
    DesktopCredentials,
)
from doc_evidence.errors import RequestError

RUNTIME_TOKEN = "1" * 64
CONTROL_TOKEN = "2" * 64


class DesktopContractTest(unittest.TestCase):
    def test_credentials_are_consumed_and_independent(self) -> None:
        values = {
            RUNTIME_TOKEN_ENV: RUNTIME_TOKEN,
            HOST_CONTROL_TOKEN_ENV: CONTROL_TOKEN,
        }
        credentials = DesktopCredentials.consume(values)
        self.assertEqual(credentials.runtime_token, RUNTIME_TOKEN)
        self.assertEqual(credentials.host_control_token, CONTROL_TOKEN)
        self.assertNotIn(RUNTIME_TOKEN_ENV, values)
        self.assertNotIn(HOST_CONTROL_TOKEN_ENV, values)
        with self.assertRaisesRegex(RequestError, "independent"):
            DesktopCredentials.consume(
                {
                    RUNTIME_TOKEN_ENV: RUNTIME_TOKEN,
                    HOST_CONTROL_TOKEN_ENV: RUNTIME_TOKEN,
                }
            )

    def test_ready_contract_rejects_extra_fields_and_bad_ports(self) -> None:
        handshake = create_desktop_handshake(
            application_home_source="desktop_host",
            baseline_pack=None,
        )
        value = {
            "schema_version": "doc-evidence.desktop-ready.v1",
            "protocol_version": DESKTOP_PROTOCOL_VERSION,
            "application_version": handshake.application_version,
            "api_version": 1,
            "host": "127.0.0.1",
            "port": 43111,
            "platform": "macos",
            "architecture": "arm64",
            "application_home_source": "desktop_host",
            "baseline_pack": None,
        }
        self.assertEqual(DesktopReady.model_validate(value).port, 43111)
        with self.assertRaises(ValidationError):
            DesktopReady.model_validate({**value, "token": RUNTIME_TOKEN})
        with self.assertRaises(ValidationError):
            DesktopReady.model_validate({**value, "port": 0})

    def test_runtime_and_host_control_credentials_cannot_be_swapped(self) -> None:
        handshake = create_desktop_handshake(
            application_home_source="desktop_host",
            baseline_pack=None,
        )
        client = TestClient(
            create_app(
                None,
                launch_token=RUNTIME_TOKEN,
                allowed_origins={DESKTOP_ORIGIN},
                desktop_handshake=handshake,
                host_control_token=CONTROL_TOKEN,
                desktop_control_handshake=DesktopControlHandshake(capabilities=[]),
            )
        )
        runtime_headers = {
            "Authorization": f"Bearer {RUNTIME_TOKEN}",
            "Origin": DESKTOP_ORIGIN,
        }
        control_headers = {"Authorization": f"Bearer {CONTROL_TOKEN}"}
        runtime = client.get("/api/v1/desktop/handshake", headers=runtime_headers)
        self.assertEqual(runtime.status_code, 200)
        self.assertEqual(runtime.json()["protocol_version"], DESKTOP_PROTOCOL_VERSION)
        self.assertEqual(
            client.get(
                "/desktop-control/v1/handshake",
                headers={"Authorization": f"Bearer {RUNTIME_TOKEN}"},
            ).status_code,
            401,
        )
        control = client.get(
            "/desktop-control/v1/handshake",
            headers=control_headers,
        )
        self.assertEqual(control.status_code, 200)
        self.assertEqual(
            client.get(
                "/desktop-control/v1/handshake",
                headers={**control_headers, "Origin": DESKTOP_ORIGIN},
            ).status_code,
            403,
        )
        evidence = runtime.text + control.text
        self.assertNotIn(RUNTIME_TOKEN, evidence)
        self.assertNotIn(CONTROL_TOKEN, evidence)


class DesktopSidecarProcessTest(unittest.TestCase):
    def test_real_sidecar_handshake_and_parent_eof_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = os.environ.copy()
            environment.pop("DOC_EVIDENCE_HOME", None)
            environment.update(
                {
                    RUNTIME_TOKEN_ENV: RUNTIME_TOKEN,
                    HOST_CONTROL_TOKEN_ENV: CONTROL_TOKEN,
                    DESKTOP_HOME_ENV: str(root / "app-home"),
                }
            )
            process = subprocess.Popen(
                [sys.executable, "-m", "doc_evidence.desktop_sidecar"],
                cwd=root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert process.stdout is not None
                ready_streams, _, _ = select.select([process.stdout], [], [], 10)
                self.assertTrue(ready_streams, "sidecar did not emit a ready record")
                ready_line = process.stdout.readline()
                ready = DesktopReady.model_validate_json(ready_line)
                self.assertEqual(ready.application_home_source, "desktop_host")
                self.assertNotIn(str(root), ready_line)
                self.assertNotIn(RUNTIME_TOKEN, ready_line)
                self.assertNotIn(CONTROL_TOKEN, ready_line)

                request = urllib.request.Request(
                    f"http://127.0.0.1:{ready.port}/api/v1/desktop/handshake",
                    headers={
                        "Authorization": f"Bearer {RUNTIME_TOKEN}",
                        "Origin": DESKTOP_ORIGIN,
                    },
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read())
                self.assertEqual(payload["protocol_version"], DESKTOP_PROTOCOL_VERSION)

                wrong = urllib.request.Request(
                    f"http://127.0.0.1:{ready.port}/desktop-control/v1/handshake",
                    headers={"Authorization": f"Bearer {RUNTIME_TOKEN}"},
                )
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    urllib.request.urlopen(wrong, timeout=10)
                self.assertEqual(rejected.exception.code, 401)

                assert process.stdin is not None
                process.stdin.close()
                process.wait(timeout=10)
                self.assertEqual(process.returncode, 0)
                assert process.stderr is not None
                errors = process.stderr.read()
                self.assertNotIn(RUNTIME_TOKEN, errors)
                self.assertNotIn(CONTROL_TOKEN, errors)
                self.assertNotIn(str(root), errors)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()


if __name__ == "__main__":
    unittest.main()
