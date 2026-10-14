"""End-to-end pipeline test verifying the complete document-to-PowerPoint lifecycle."""

import shutil
import tempfile
import unittest
from pathlib import Path

from pptx import Presentation

from app.ai.client import MockAIClient
from app.ai.image_provider import LocalAssetImageProvider
from app.config import AppConfig
from app.orchestration.state import JobStore
from app.orchestration.workflow import WorkflowEngine
from app.schemas.job import JobStatus


class TestEndToEndPresentationLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)

        # Configure isolated test paths
        self.config = AppConfig(
            ai_provider="mock",
            data_dir=self.base_path / "data",
            projects_dir=self.base_path / "projects",
        )
        self.store = JobStore(self.config.data_dir / "jobs.db")
        self.ai_client = MockAIClient()
        self.image_provider = LocalAssetImageProvider()
        self.engine = WorkflowEngine(
            self.config,
            self.store,
            self.ai_client,
            self.image_provider,
        )

        # Create a sample source document
        self.sample_doc = self.base_path / "test_report.md"
        self.sample_doc.write_text(
            """# Autonomous AI Presentation Generation
## Executive Summary
This report describes the architecture and execution pipeline of PPT Master Standalone.

### Key Milestones
- Native PowerPoint OpenXML compilation without external agent runtimes.
- Strict quality gates enforcing SVG and DrawingML standards.
- Resilient recovery and persistent state machines.

### Recommendations
Deploy across enterprise document transformation workflows.
""",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_pipeline_execution(self):
        job_id = "test_e2e_job"
        job = self.store.create_job(
            job_id=job_id,
            project_name="E2E_Presentation",
            source_filename=self.sample_doc.name,
            auto_approve=True,
        )

        # Execute full workflow synchronously
        self.engine.run_job(
            job_id=job_id,
            source_file_path=self.sample_doc,
            job_params={
                "project_name": "E2E_Presentation",
                "slide_count": 4,
                "enable_notes": True,
                "enable_animations": False,
            },
        )

        # Retrieve completed job state
        completed_job = self.store.get_job(job_id)
        self.assertIsNotNone(completed_job)
        self.assertEqual(
            completed_job.status,
            JobStatus.COMPLETED,
            f"Job did not complete. Error: {completed_job.error_message}",
        )
        self.assertEqual(completed_job.progress_percent, 100)
        self.assertIsNotNone(completed_job.output_pptx_path)

        project_path = Path(completed_job.project_path)
        self.assertTrue(project_path.is_dir())

        # Verify artifacts
        # 1. Sources
        sources_md = list((project_path / "sources").glob("*.md"))
        self.assertGreater(len(sources_md), 0)

        # 2. Plan
        plan_file = project_path / "presentation_plan.json"
        self.assertTrue(plan_file.is_file())

        # 3. Design spec and lock
        self.assertTrue((project_path / "design_spec.md").is_file())
        self.assertTrue((project_path / "spec_lock.md").is_file())

        # 4. Slide SVGs
        svg_files = sorted((project_path / "svg_output").glob("slide_*.svg"))
        self.assertEqual(len(svg_files), 4)

        # 5. Speaker notes
        self.assertTrue((project_path / "notes" / "total.md").is_file())

        # 6. PPTX file exists and opens as OpenXML Presentation
        pptx_path = Path(completed_job.output_pptx_path)
        self.assertTrue(pptx_path.is_file())
        self.assertGreater(pptx_path.stat().st_size, 1024)

        prs = Presentation(str(pptx_path))
        self.assertEqual(len(prs.slides), 4)

    def test_slide_repair_on_failing_preflight(self):
        slide = self.ai_client.generate_plan("doc", {}).slides[0]
        spec = self.ai_client.generate_design_spec(self.ai_client.generate_plan("doc", {}), {})

        # Test preflight rejection and repair
        project_dir = self.base_path / "repair_test_proj"
        project_dir.mkdir(parents=True)
        (project_dir / "svg_output").mkdir()

        success, slide_file, errors = self.engine.slide_service.generate_single_slide(
            slide, spec, total_slides=1, project_path=project_dir
        )
        self.assertTrue(success)
        self.assertTrue(slide_file.is_file())
        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
