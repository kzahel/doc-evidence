from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from doc_evidence.adapters.local_jobs import LocalExtractionJobs
from doc_evidence.app_home import legacy_library_id
from doc_evidence.attempts import AttemptSupervisor
from doc_evidence.config import load_config
from doc_evidence.errors import CatalogError, RequestError
from doc_evidence.inventory import run_inventory
from doc_evidence.persistence import ensure_library_database
from doc_evidence.scheduler import LibraryScheduler, ResourceLimits
from tests.helpers import write_minimal_pdf


def _write_config(root: Path) -> Path:
    config = root / "case.yaml"
    config.write_text(
        """
schema_version: 1
collections:
  - id: sample
    source: documents
store:
  path: derived
""".lstrip(),
        encoding="utf-8",
    )
    return config


@unittest.skipUnless(
    shutil.which("pdfinfo") and shutil.which("pdftotext"),
    "Poppler tools are required for durable job integration",
)
class ExtractionJobApplicationTest(unittest.TestCase):
    def application(self, root: Path) -> tuple[LocalExtractionJobs, str, Path]:
        documents = root / "documents"
        documents.mkdir()
        source = documents / "one.pdf"
        write_minimal_pdf(source, "durable job evidence")
        config = load_config(_write_config(root))
        result = run_inventory(config)
        library_id = legacy_library_id(config.path)
        database = ensure_library_database(config, library_id=library_id)
        return (
            LocalExtractionJobs(
                library_id=library_id,
                config=config,
                database=database,
            ),
            result.documents[0].document_id,
            source,
        )

    def test_cache_hit_idempotency_and_active_coalescing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, document_id, _source = self.application(
                Path(temporary_directory)
            )

            cached = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                idempotency_key="cached-request",
            )
            repeated = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                idempotency_key="cached-request",
            )
            fresh = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                execution_mode="fresh_verification",
            )
            coalesced = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                execution_mode="fresh_verification",
            )

            self.assertEqual(cached.disposition, "cache_hit")
            self.assertEqual(cached.job.outcome, "cache_hit")
            self.assertEqual(repeated.disposition, "idempotent")
            self.assertEqual(repeated.job.job_id, cached.job.job_id)
            self.assertEqual(fresh.disposition, "created")
            self.assertEqual(coalesced.disposition, "coalesced")
            self.assertEqual(coalesced.job.job_id, fresh.job.job_id)
            with self.assertRaisesRegex(RequestError, "different request"):
                application.enqueue(
                    document_id=document_id,
                    extractor_id="poppler",
                    execution_mode="fresh_verification",
                    idempotency_key="cached-request",
                )

    def test_scheduler_executes_fresh_attempt_and_persists_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, document_id, _source = self.application(
                Path(temporary_directory)
            )
            created = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                execution_mode="fresh_verification",
            )
            scheduler = LibraryScheduler(
                application,
                resource_limits=ResourceLimits(light=1, ocr=1, model_heavy=1),
                poll_seconds=0.02,
                heartbeat_seconds=0.05,
            )
            self.assertTrue(scheduler.start())
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    job = application.get(created.job.job_id)
                    if job.state in {"succeeded", "failed", "cancelled"}:
                        break
                    time.sleep(0.02)
                else:
                    self.fail("durable extraction job did not finish")
            finally:
                scheduler.stop()

            job = application.get(created.job.job_id)
            events = application.events(job.job_id)
            connection = application.database.connect(readonly=True)
            try:
                attempts = connection.execute(
                    "SELECT * FROM job_attempts WHERE job_id = ?", (job.job_id,)
                ).fetchall()
                lease = connection.execute(
                    "SELECT scheduler_instance_id FROM scheduler_lease"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(job.state, "succeeded")
            self.assertEqual(job.outcome, "verified_cache_match")
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0]["state"], "succeeded")
            self.assertIsNone(lease)
            self.assertEqual(events[0].event_type, "queued")
            self.assertEqual(events[-1].event_type, "verified_cache_match")

    def test_recovery_promotes_valid_publication_and_flags_missing_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, document_id, _source = self.application(
                Path(temporary_directory)
            )
            fresh = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                execution_mode="fresh_verification",
            )
            repository = application.repository
            self.assertTrue(
                repository.acquire_lease("lost-scheduler", stale_after_seconds=0)
            )
            claimed = repository.claim_next(
                scheduler_instance_id="lost-scheduler",
                resource_classes={"light"},
            )
            self.assertIsNotNone(claimed)
            repository.release_lease("lost-scheduler")

            recovered = application.reconcile()

            self.assertTrue(recovered)
            job = application.get(fresh.job.job_id)
            self.assertEqual(job.state, "succeeded")
            self.assertEqual(job.outcome, "recovered_published")

            assert job.result_artifact_path is not None
            run_dir = application.config.store / job.result_artifact_path
            hidden = run_dir.with_name(run_dir.name + ".hidden")
            run_dir.rename(hidden)
            try:
                application.reconcile()
            finally:
                hidden.rename(run_dir)
            failed = application.get(job.job_id)
            self.assertEqual(failed.state, "failed")
            self.assertEqual(failed.outcome, "integrity_failed")

    def test_source_hash_is_rechecked_before_enqueue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, document_id, source = self.application(
                Path(temporary_directory)
            )
            write_minimal_pdf(source, "changed after inventory")

            with self.assertRaisesRegex(RequestError, "source cannot be verified"):
                application.enqueue(
                    document_id=document_id,
                    extractor_id="poppler",
                )

    def test_batch_preflight_idempotency_and_coalesced_membership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, document_id, _source = self.application(
                Path(temporary_directory)
            )
            active = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                execution_mode="fresh_verification",
            )
            with self.assertRaisesRegex(RequestError, "confirmation"):
                application.enqueue_batch(
                    document_ids=[document_id],
                    extractor_ids=["poppler"],
                    execution_mode="fresh_verification",
                    confirmed=False,
                )

            created = application.enqueue_batch(
                document_ids=[document_id],
                extractor_ids=["poppler"],
                execution_mode="fresh_verification",
                confirmed=True,
                idempotency_key="batch-request",
            )
            repeated = application.enqueue_batch(
                document_ids=[document_id],
                extractor_ids=["poppler"],
                execution_mode="fresh_verification",
                confirmed=True,
                idempotency_key="batch-request",
            )

            self.assertEqual(created.disposition, "created")
            self.assertEqual(repeated.disposition, "idempotent")
            self.assertEqual(created.batch.batch_id, repeated.batch.batch_id)
            self.assertEqual(created.jobs[0].job_id, active.job.job_id)
            self.assertEqual(created.batch.child_count, 1)
            self.assertEqual(created.batch.status, "queued")

    def test_process_lock_rejects_a_second_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, _document_id, _source = self.application(
                Path(temporary_directory)
            )
            first = LibraryScheduler(application, poll_seconds=0.02)
            second = LibraryScheduler(application, poll_seconds=0.02)

            self.assertTrue(first.start())
            try:
                self.assertFalse(second.start())
            finally:
                first.stop()

    def test_queue_pause_blocks_claim_until_resumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, document_id, _source = self.application(
                Path(temporary_directory)
            )
            created = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                execution_mode="fresh_verification",
            )
            application.set_queue_paused(True)
            scheduler = LibraryScheduler(
                application,
                poll_seconds=0.02,
                heartbeat_seconds=0.05,
            )
            self.assertTrue(scheduler.start())
            try:
                time.sleep(0.15)
                self.assertEqual(application.get(created.job.job_id).state, "queued")
                self.assertTrue(application.queue_state().paused)
                application.set_queue_paused(False)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    job = application.get(created.job.job_id)
                    if job.state in {"succeeded", "failed"}:
                        break
                    time.sleep(0.02)
                else:
                    self.fail("resumed queue did not dispatch work")
            finally:
                scheduler.stop()
            self.assertEqual(job.state, "succeeded")

    def test_image_only_ocr_batch_preflight_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, document_id, _source = self.application(
                Path(temporary_directory)
            )
            connection = application.database.connect()
            try:
                connection.execute(
                    "UPDATE content_objects SET extraction_status = 'image_only'"
                )
                connection.commit()
            finally:
                connection.close()

            preflight = application.preflight_image_only_ocr()

            self.assertEqual(preflight.candidate_count, 1)
            self.assertEqual(preflight.document_ids, (document_id,))
            self.assertEqual(preflight.resource_class, "ocr")
            self.assertEqual(preflight.concurrency_limit, 1)
            self.assertEqual(preflight.maximum_batch_size, 200)
            self.assertEqual(
                preflight.execution_count + preflight.missing_dependency_count,
                1,
            )

    def test_transient_worker_launch_gets_only_one_automatic_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base, document_id, _source = self.application(Path(temporary_directory))
            application = LocalExtractionJobs(
                library_id=base.library_id,
                config=base.config,
                database=base.database,
                supervisor=AttemptSupervisor(
                    worker_command=(str(Path(temporary_directory) / "missing-worker"),),
                    minimum_free_bytes=0,
                ),
            )
            created = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                execution_mode="fresh_verification",
            )
            scheduler = LibraryScheduler(
                application,
                poll_seconds=0.02,
                heartbeat_seconds=0.05,
            )
            self.assertTrue(scheduler.start())
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    job = application.get(created.job.job_id)
                    if job.state == "failed" and job.automatic_retry_count == 1:
                        connection = application.database.connect(readonly=True)
                        try:
                            attempts = int(
                                connection.execute(
                                    "SELECT COUNT(*) FROM job_attempts WHERE job_id = ?",
                                    (job.job_id,),
                                ).fetchone()[0]
                            )
                        finally:
                            connection.close()
                        if attempts == 2:
                            break
                    time.sleep(0.05)
                else:
                    self.fail("bounded automatic retry did not settle")
            finally:
                scheduler.stop()

            self.assertEqual(job.failure_class, "worker_launch_failed")
            self.assertEqual(job.automatic_retry_count, 1)
            self.assertEqual(attempts, 2)

    def test_projection_failure_preserves_artifact_logs_and_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, document_id, _source = self.application(
                Path(temporary_directory)
            )
            created = application.enqueue(
                document_id=document_id,
                extractor_id="poppler",
                execution_mode="fresh_verification",
            )
            scheduler = LibraryScheduler(
                application,
                poll_seconds=0.02,
                heartbeat_seconds=0.05,
            )
            with patch.object(
                application.database,
                "register_run_sidecars",
                side_effect=CatalogError("simulated projection failure"),
            ):
                self.assertTrue(scheduler.start())
                try:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        job = application.get(created.job.job_id)
                        if job.state == "failed":
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("projection failure did not settle")
                finally:
                    scheduler.stop()

            self.assertEqual(job.outcome, "published_projection_failed")
            self.assertIsNotNone(job.result_artifact_path)
            attempts = application.attempts(job.job_id)
            self.assertEqual(len(attempts), 1)
            self.assertFalse(attempts[0].process_alive)
            diagnostics = application.attempt_diagnostics(
                job.job_id, attempts[0].attempt_id
            )
            self.assertTrue(diagnostics.retained)
            self.assertEqual(diagnostics.projection_status, "repair required")
            self.assertLessEqual(len(diagnostics.stdout_tail.encode()), 16_384)
            self.assertLessEqual(len(diagnostics.stderr_tail.encode()), 16_384)

            repaired = application.repair_projection(job.job_id)
            self.assertEqual(repaired.state, "succeeded")
            self.assertEqual(repaired.outcome, "projection_repaired")
            self.assertEqual(
                application.events(job.job_id)[-1].event_type,
                "projection_repaired",
            )

    def test_temporary_database_contention_waits_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            application, document_id, _source = self.application(
                Path(temporary_directory)
            )
            blocker = application.database.connect()
            blocker.execute("BEGIN IMMEDIATE")
            results: list[str] = []
            failures: list[Exception] = []

            def enqueue() -> None:
                try:
                    results.append(
                        application.enqueue(
                            document_id=document_id,
                            extractor_id="poppler",
                            idempotency_key="contended-enqueue",
                        ).job.state
                    )
                except (CatalogError, RequestError) as error:
                    failures.append(error)

            thread = threading.Thread(target=enqueue)
            thread.start()
            time.sleep(0.1)
            blocker.commit()
            blocker.close()
            thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(results, ["succeeded"])


if __name__ == "__main__":
    unittest.main()
