from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from doc_evidence.app_home import legacy_library_id
from doc_evidence.application.jobs import ExtractionJobApplication
from doc_evidence.attempts import AttemptSupervisor
from doc_evidence.config import load_config
from doc_evidence.errors import RequestError
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
    def application(self, root: Path) -> tuple[ExtractionJobApplication, str, Path]:
        documents = root / "documents"
        documents.mkdir()
        source = documents / "one.pdf"
        write_minimal_pdf(source, "durable job evidence")
        config = load_config(_write_config(root))
        result = run_inventory(config)
        library_id = legacy_library_id(config.path)
        database = ensure_library_database(config, library_id=library_id)
        return (
            ExtractionJobApplication(
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

    def test_transient_worker_launch_gets_only_one_automatic_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base, document_id, _source = self.application(Path(temporary_directory))
            application = ExtractionJobApplication(
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


if __name__ == "__main__":
    unittest.main()
