from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from doc_evidence.attempts import (
    AttemptPlan,
    AttemptRetention,
    AttemptSupervisor,
    validate_run,
)
from doc_evidence.errors import RequestError
from doc_evidence.extractor_registry import ExtractorExecution, ExtractorRegistry
from doc_evidence.windows_job import process_is_alive as windows_process_is_alive
from tests.helpers import write_minimal_pdf

FAKE_WORKER = Path(__file__).parent / "fixtures" / "fake_extraction_worker.py"


def _plan(
    root: Path,
    *,
    attempt_id: str,
    settings: dict[str, object],
    fresh: bool = False,
    extractor_id: str = "fixture-extractor",
    timeout: int = 10,
    expected_run_key: str | None = None,
) -> AttemptPlan:
    source = root / "source.txt"
    if not source.exists():
        source.write_text("source evidence", encoding="utf-8")
    stat = source.stat()
    store = root / "store"
    store.mkdir(exist_ok=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    blob = store / "blobs" / digest[:2] / digest
    planned_run_key = expected_run_key or str(
        settings.get("run_key", "fixture-run-key")
    )
    return AttemptPlan(
        attempt_id=attempt_id,
        execution=ExtractorExecution(
            extractor_id=extractor_id,
            settings=settings,
            timeout_seconds=timeout,
            resource_class="light",
            deterministic=True,
        ),
        expected_run_id=f"{extractor_id}:{planned_run_key}",
        expected_run_key=planned_run_key,
        source_path=source,
        source_sha256=digest,
        expected_size_bytes=stat.st_size,
        expected_modified_ns=stat.st_mtime_ns,
        store_root=store,
        blob_dir=blob,
        extraction_config_hash="fixture-config",
        fresh_verification=fresh,
    )


def _process_alive(process_id: int) -> bool:
    if os.name == "posix":
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return False
        return True
    if os.name == "nt":
        return windows_process_is_alive(process_id)
    raise RuntimeError("process liveness is unsupported")


class AttemptSupervisorTest(unittest.TestCase):
    def supervisor(self, **values: object) -> AttemptSupervisor:
        return AttemptSupervisor(
            worker_command=(sys.executable, str(FAKE_WORKER)),
            minimum_free_bytes=0,
            **values,  # type: ignore[arg-type]
        )

    def test_atomic_publication_concurrent_win_and_nondeterminism(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_plan = _plan(
                root,
                attempt_id="first",
                settings={"text": "canonical output"},
            )
            first = self.supervisor().execute(first_plan)
            self.assertEqual(first.outcome, "executed", first.value())
            canonical = (
                first_plan.blob_dir / "runs" / "fixture-extractor" / "fixture-run-key"
            )
            before = (canonical / "normalized.json").read_bytes()

            concurrent = self.supervisor().execute(
                _plan(
                    root,
                    attempt_id="second",
                    settings={"text": "canonical output"},
                )
            )
            nondeterministic_plan = _plan(
                root,
                attempt_id="fresh",
                settings={"text": "different output"},
                fresh=True,
            )
            nondeterministic = self.supervisor().execute(nondeterministic_plan)

            self.assertTrue(
                (
                    first_plan.blob_dir / "attempts" / "first" / "publication.json"
                ).is_file()
            )
            self.assertEqual(concurrent.outcome, "concurrent_cache_win")
            self.assertEqual(nondeterministic.outcome, "nondeterministic")
            self.assertEqual((canonical / "normalized.json").read_bytes(), before)
            self.assertTrue(
                (
                    nondeterministic_plan.blob_dir
                    / "attempts"
                    / "fresh"
                    / "runs"
                    / "fixture-extractor"
                    / "fixture-run-key"
                ).is_dir()
            )

    def test_malformed_output_is_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = _plan(
                root,
                attempt_id="corrupt",
                settings={"behavior": "corrupt"},
            )

            result = self.supervisor().execute(plan)

            self.assertEqual(result.outcome, "failed")
            self.assertEqual(result.failure_class, "validation_or_publication")
            self.assertFalse(
                (
                    plan.blob_dir / "runs" / "fixture-extractor" / "fixture-run-key"
                ).exists()
            )

    def test_unplanned_worker_identity_is_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = _plan(
                root,
                attempt_id="wrong-identity",
                settings={"run_key": "worker-selected-key"},
                expected_run_key="planned-key",
            )

            result = self.supervisor().execute(plan)

            self.assertEqual(result.outcome, "failed")
            self.assertEqual(result.failure_class, "validation_or_publication")
            self.assertIn("planned run", result.message or "")
            self.assertFalse((plan.blob_dir / "runs").exists())
            self.assertTrue(
                (
                    plan.blob_dir
                    / "attempts"
                    / "wrong-identity"
                    / "runs"
                    / "fixture-extractor"
                    / "worker-selected-key"
                ).is_dir()
            )

    def test_crash_incomplete_timeout_and_write_failure_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            crash_plan = _plan(root, attempt_id="crash", settings={"behavior": "crash"})
            crash = self.supervisor().execute(crash_plan)
            incomplete = self.supervisor().execute(
                _plan(
                    root,
                    attempt_id="incomplete",
                    settings={"behavior": "incomplete", "run_key": "incomplete"},
                )
            )
            timeout = self.supervisor(cancellation_grace_seconds=0.1).execute(
                _plan(
                    root,
                    attempt_id="timeout",
                    settings={"behavior": "hang"},
                    timeout=1,
                )
            )
            write_plan = _plan(
                root,
                attempt_id="write-failure",
                settings={"run_key": "write-failure"},
            )
            with patch.object(
                Path, "rename", side_effect=OSError("simulated write failure")
            ):
                write_failure = self.supervisor().execute(write_plan)

            self.assertEqual(crash.outcome, "failed")
            self.assertEqual(crash.exit_code, 23)
            self.assertIn(
                "simulated immediate worker crash",
                (
                    crash_plan.blob_dir / "attempts" / "crash" / "worker.stderr.log"
                ).read_text(encoding="utf-8"),
            )
            self.assertEqual(incomplete.failure_class, "validation_or_publication")
            self.assertEqual(timeout.outcome, "timeout")
            self.assertEqual(write_failure.failure_class, "validation_or_publication")
            self.assertFalse(
                (
                    write_plan.blob_dir / "runs" / "fixture-extractor" / "write-failure"
                ).exists()
            )

    def test_insufficient_staging_space_fails_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = _plan(root, attempt_id="no-space", settings={})
            with self.assertRaisesRegex(RequestError, "enough free staging space"):
                AttemptSupervisor(minimum_free_bytes=2**63).execute(plan)
            self.assertFalse((plan.blob_dir / "attempts" / "no-space").exists())

    def test_worker_launch_failure_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = _plan(root, attempt_id="launch-failed", settings={})

            result = AttemptSupervisor(
                worker_command=(str(root / "missing-worker"),),
                minimum_free_bytes=0,
            ).execute(plan)

            self.assertEqual(result.outcome, "failed")
            self.assertEqual(result.failure_class, "worker_launch_failed")
            self.assertIsNone(result.worker_pid)
            self.assertTrue(
                (
                    plan.blob_dir / "attempts" / "launch-failed" / "attempt.json"
                ).is_file()
            )

    @unittest.skipUnless(
        shutil.which("pdfinfo") and shutil.which("pdftotext"),
        "Poppler is required for source-verification integration",
    )
    def test_worker_rejects_changed_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.pdf"
            write_minimal_pdf(source, "first source")
            stat = source.stat()
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            store = root / "store"
            store.mkdir()
            blob = store / "blobs" / digest[:2] / digest
            prepared = ExtractorRegistry().prepare(
                extractor_id="poppler",
                media_type="application/pdf",
                settings={},
                extraction_config_hash="fixture-config",
            )
            write_minimal_pdf(source, "changed source")
            plan = AttemptPlan(
                attempt_id="changed-source",
                execution=prepared.execution,
                expected_run_id=prepared.run_id,
                expected_run_key=prepared.run_key,
                source_path=source,
                source_sha256=digest,
                expected_size_bytes=stat.st_size,
                expected_modified_ns=stat.st_mtime_ns,
                store_root=store,
                blob_dir=blob,
                extraction_config_hash="fixture-config",
            )

            result = AttemptSupervisor(minimum_free_bytes=0).execute(plan)

            self.assertEqual(result.outcome, "failed")
            self.assertIn("changed", result.message or "")
            self.assertFalse((blob / "runs").exists())

    def test_retention_is_separate_and_never_removes_active_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_plan = _plan(root, attempt_id="old", settings={})
            active_plan = _plan(root, attempt_id="active", settings={})
            self.supervisor().execute(first_plan)
            self.supervisor().execute(active_plan)

            result = AttemptRetention().cleanup(
                blob_dir=first_plan.blob_dir,
                active_attempt_ids={"active"},
                max_bytes=0,
                max_age_days=0,
                now=datetime.now(UTC),
            )

            self.assertEqual(result.removed_attempt_ids, ("old",))
            self.assertFalse((first_plan.blob_dir / "attempts" / "old").exists())
            self.assertTrue((first_plan.blob_dir / "attempts" / "active").is_dir())

    def test_cancellation_kills_process_group_and_bounds_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = _plan(
                root,
                attempt_id="cancelled",
                settings={"behavior": "block"},
                timeout=20,
            )
            cancel = threading.Event()

            def request_cancel() -> None:
                child_path = plan.blob_dir / "attempts" / "cancelled" / "child.pid"
                deadline = time.monotonic() + 5
                while not child_path.is_file() and time.monotonic() < deadline:
                    time.sleep(0.02)
                cancel.set()

            thread = threading.Thread(target=request_cancel)
            thread.start()
            result = self.supervisor(
                log_limit_bytes=4_096,
                cancellation_grace_seconds=0.2,
            ).execute(plan, cancel=cancel)
            thread.join(timeout=5)
            attempt = plan.blob_dir / "attempts" / "cancelled"
            child_pid = int((attempt / "child.pid").read_text(encoding="ascii"))

            self.assertEqual(result.outcome, "cancelled")
            self.assertLessEqual((attempt / "worker.stdout.log").stat().st_size, 4_096)
            self.assertLessEqual((attempt / "worker.stderr.log").stat().st_size, 4_096)
            self.assertGreater(result.stdout_truncated_bytes, 0)
            self.assertGreater(result.stderr_truncated_bytes, 0)
            worker = json.loads((attempt / "worker.json").read_text(encoding="utf-8"))
            self.assertEqual(
                worker["process_tree"],
                (
                    "windows_job_kill_on_close"
                    if os.name == "nt"
                    else "posix_process_group"
                ),
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if not _process_alive(child_pid):
                    break
                time.sleep(0.05)
            else:
                self.fail("worker descendant remained alive after cancellation")

    def test_ignored_cancellation_escalates_and_kills_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plan = _plan(
                root,
                attempt_id="ignored-cancel",
                settings={"behavior": "ignore-cancel"},
                timeout=20,
            )
            cancel = threading.Event()

            def request_cancel() -> None:
                child_path = plan.blob_dir / "attempts" / "ignored-cancel" / "child.pid"
                deadline = time.monotonic() + 5
                while not child_path.is_file() and time.monotonic() < deadline:
                    time.sleep(0.02)
                cancel.set()

            thread = threading.Thread(target=request_cancel)
            thread.start()
            result = self.supervisor(cancellation_grace_seconds=0.1).execute(
                plan, cancel=cancel
            )
            thread.join(timeout=5)
            child_pid = int(
                (plan.blob_dir / "attempts" / "ignored-cancel" / "child.pid").read_text(
                    encoding="ascii"
                )
            )

            self.assertEqual(result.outcome, "cancelled")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if not _process_alive(child_pid):
                    break
                time.sleep(0.05)
            else:
                self.fail("ignored-cancellation descendant remained alive")

    @unittest.skipUnless(
        shutil.which("pdfinfo") and shutil.which("pdftotext"),
        "Poppler is required for worker integration",
    )
    def test_real_poppler_worker_stages_validates_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.pdf"
            write_minimal_pdf(source, "worker evidence")
            stat = source.stat()
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            store = root / "store"
            blob = store / "blobs" / digest[:2] / digest
            store.mkdir()
            prepared = ExtractorRegistry().prepare(
                extractor_id="poppler",
                media_type="application/pdf",
                settings={},
                extraction_config_hash="fixture-config",
            )
            plan = AttemptPlan(
                attempt_id="poppler-worker",
                execution=prepared.execution,
                expected_run_id=prepared.run_id,
                expected_run_key=prepared.run_key,
                source_path=source,
                source_sha256=digest,
                expected_size_bytes=stat.st_size,
                expected_modified_ns=stat.st_mtime_ns,
                store_root=store,
                blob_dir=blob,
                extraction_config_hash="fixture-config",
            )

            result = AttemptSupervisor(minimum_free_bytes=0).execute(plan)

            self.assertEqual(result.outcome, "executed")
            assert result.run_key is not None
            canonical = blob / "runs" / "poppler" / result.run_key
            manifest = validate_run(
                canonical,
                extractor_id="poppler",
                source_sha256=digest,
                run_key=result.run_key,
            )
            self.assertIn("pages.json", manifest)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)


class ExtractorRegistryTest(unittest.TestCase):
    def test_shared_dependency_versions_are_probed_once(self) -> None:
        registry = ExtractorRegistry()
        with (
            patch(
                "doc_evidence.extractor_registry.DependencySpec.resolve",
                return_value=Path("/resolved/tool"),
            ),
            patch(
                "doc_evidence.extractor_registry.command_version",
                return_value="tool 1.0",
            ) as version,
        ):
            registry.capabilities()

        self.assertEqual(version.call_count, 6)

    def test_registry_validates_media_settings_and_dependency_capabilities(
        self,
    ) -> None:
        registry = ExtractorRegistry()
        capability = registry.capability("poppler")
        execution = registry.execution(
            extractor_id="poppler",
            media_type="application/pdf",
            settings={},
        )

        self.assertEqual(capability.spec.resource_class, "light")
        self.assertTrue(capability.available)
        self.assertEqual(execution.settings, {})
        self.assertIn("normalized_page_text", capability.spec.output_kinds)
        with self.assertRaisesRegex(RequestError, "does not support"):
            registry.execution(
                extractor_id="poppler",
                media_type="image/png",
                settings={},
            )
        with self.assertRaisesRegex(RequestError, "unsupported fields"):
            registry.execution(
                extractor_id="poppler",
                media_type="application/pdf",
                settings={"executable": "/tmp/not-allowed"},
            )


if __name__ == "__main__":
    unittest.main()
