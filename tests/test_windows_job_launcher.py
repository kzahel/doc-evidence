from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from doc_evidence.windows_job_launcher import run


class WindowsJobLauncherTest(unittest.TestCase):
    def test_launcher_reports_ready_before_waiting_for_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gate = root / "gate"
            ready = root / "ready"
            pid_file = root / "pid"
            result: list[int] = []
            thread = threading.Thread(
                target=lambda: result.append(
                    run(
                        gate=gate,
                        ready_file=ready,
                        pid_file=pid_file,
                        command=(sys.executable, "-c", "pass"),
                    )
                )
            )

            thread.start()
            deadline = time.monotonic() + 5
            while not ready.is_file() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.is_file())
            self.assertFalse(pid_file.exists())
            gate.write_text("release\n", encoding="ascii")
            thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(result, [0])
            self.assertGreater(int(pid_file.read_text(encoding="ascii")), 0)
            self.assertFalse(gate.exists())

    def test_launcher_files_must_share_an_absolute_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(ValueError, "gate is invalid"):
                run(
                    gate=root / "gate",
                    ready_file=root / "other" / "ready",
                    pid_file=root / "pid",
                    command=(sys.executable, "-c", "pass"),
                )


if __name__ == "__main__":
    unittest.main()
