"""Unit tests for SQLite state management and checkpoint recovery."""

import tempfile
import unittest
from pathlib import Path

from app.orchestration.checkpoints import CheckpointManager
from app.orchestration.recovery import JobRecoveryManager
from app.orchestration.state import JobStore
from app.schemas.job import JobPhase, JobStatus


class TestOrchestrationState(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_jobs.db"
        self.store = JobStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_get_job(self):
        job = self.store.create_job(
            job_id="test_job_1",
            project_name="Demo Project",
            source_filename="sample.pdf",
            auto_approve=True,
        )
        self.assertEqual(job.job_id, "test_job_1")
        self.assertEqual(job.status, JobStatus.CREATED)
        self.assertEqual(job.phase, JobPhase.INTAKE)
        self.assertEqual(job.progress_percent, 0)
        self.assertEqual(len(job.logs), 1)

    def test_update_job_status_and_progress(self):
        self.store.create_job("job_update", "Test Update")
        self.store.update_job(
            "job_update",
            status=JobStatus.GENERATING_SLIDES,
            phase=JobPhase.CONSTRUCTION,
            progress_percent=60,
            current_slide=3,
            total_slides=5,
        )
        job = self.store.get_job("job_update")
        self.assertIsNotNone(job)
        self.assertEqual(job.status, JobStatus.GENERATING_SLIDES)
        self.assertEqual(job.phase, JobPhase.CONSTRUCTION)
        self.assertEqual(job.progress_percent, 60)
        self.assertEqual(job.current_slide, 3)
        self.assertEqual(job.total_slides, 5)

    def test_add_and_retrieve_logs(self):
        self.store.create_job("job_log", "Test Log")
        self.store.add_log(
            "job_log",
            phase="Phase 1",
            step_name="AIPlanner",
            status="SUCCESS",
            message="Plan authored.",
        )
        job = self.store.get_job("job_log")
        self.assertEqual(len(job.logs), 2)  # 1 initial + 1 added
        self.assertEqual(job.logs[1].step_name, "AIPlanner")
        self.assertEqual(job.logs[1].message, "Plan authored.")

    def test_checkpoint_verification(self):
        with tempfile.TemporaryDirectory() as proj_tmp:
            proj = Path(proj_tmp)
            self.assertFalse(CheckpointManager.verify_intake_checkpoint(proj))

            # Simulate intake
            sources = proj / "sources"
            sources.mkdir()
            (sources / "doc.md").write_text("# Test")
            self.assertTrue(CheckpointManager.verify_intake_checkpoint(proj))

            # Simulate plan
            self.assertFalse(CheckpointManager.verify_plan_checkpoint(proj))
            (proj / "presentation_plan.json").write_text('{"slides": [{"index": 1}]}')
            self.assertTrue(CheckpointManager.verify_plan_checkpoint(proj))

            # Simulate design spec
            self.assertFalse(CheckpointManager.verify_design_checkpoint(proj))
            (proj / "design_spec.md").write_text("# Spec")
            (proj / "spec_lock.md").write_text("# Lock")
            self.assertTrue(CheckpointManager.verify_design_checkpoint(proj))

    def test_recovery_resume_point_calculation(self):
        with tempfile.TemporaryDirectory() as proj_tmp:
            proj = Path(proj_tmp)
            (proj / "sources").mkdir()
            (proj / "sources" / "doc.md").write_text("# Test")
            (proj / "presentation_plan.json").write_text('{"slides": [{"index": 1}, {"index": 2}]}')
            (proj / "design_spec.md").write_text("# Spec")
            (proj / "spec_lock.md").write_text("# Lock")

            svg_dir = proj / "svg_output"
            svg_dir.mkdir()
            (svg_dir / "slide_01.svg").write_text("<svg>1</svg>" * 10)

            status, phase, resume_slide = JobRecoveryManager.determine_resume_point(
                proj, total_slides=2
            )
            self.assertEqual(status, JobStatus.GENERATING_SLIDES)
            self.assertEqual(phase, JobPhase.CONSTRUCTION)
            self.assertEqual(resume_slide, 2)


if __name__ == "__main__":
    unittest.main()
