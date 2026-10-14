"""Comprehensive verification suite covering the 12 required test cases
and behavioral regressions for Scenario 1 and Scenario 2.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
from pptx import Presentation

from app.ai.client import MockAIClient, OpenAIClient, get_ai_client
from app.ai.image_provider import LocalAssetImageProvider, NanoBananaImageProvider
from app.config import AppConfig
from app.orchestration.state import JobStore
from app.orchestration.workflow import WorkflowEngine
from app.schemas.job import JobPhase, JobStatus
from app.schemas.plan import PresentationPlan, SlidePlan
from app.schemas.spec import ColorPalette, DesignSpecSchema, TypographyHierarchy
from app.services.document_service import DocumentService
from app.services.validation_service import ValidationService


def _create_minimal_docx(text_paragraphs: list[str]) -> bytes:
    """Helper to create a valid minimal .docx byte buffer without external binary tools."""
    docx_io = io.BytesIO()
    with zipfile.ZipFile(docx_io, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        body_xml = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in text_paragraphs)
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body_xml}</w:body></w:document>',
        )
    return docx_io.getvalue()


def _create_minimal_pdf(content_text: str) -> bytes:
    """Helper to create a valid PDF with PyMuPDF."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), content_text, fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class TestScenariosAndCases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)

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

    def tearDown(self):
        self.temp_dir.cleanup()

    # ─────────────────────────────────────────────────────────────
    # Case 1: A normal DOCX-to-PPTX generation task
    # ─────────────────────────────────────────────────────────────
    def test_case_1_docx_to_pptx_pipeline(self):
        docx_data = _create_minimal_docx(
            [
                "Cloud Computing Modernization Proposal",
                "Executive Summary: Migrate on-premises workloads to secure cloud infrastructure.",
                "Strategic Goals: High availability, zero downtime, and SOC2 compliance.",
                "Budget and Timeline: Phased migration across Q1-Q4.",
            ]
        )
        docx_file = self.base_path / "proposal.docx"
        docx_file.write_bytes(docx_data)

        job_id = "test_case_1_job"
        self.store.create_job(job_id=job_id, project_name="Cloud_Proposal", auto_approve=True)

        self.engine.run_job(
            job_id=job_id,
            source_file_path=docx_file,
            job_params={"project_name": "Cloud_Proposal", "slide_count": 3},
        )

        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertTrue(Path(job.output_pptx_path).is_file())
        prs = Presentation(job.output_pptx_path)
        self.assertGreaterEqual(len(prs.slides), 3)

    # ─────────────────────────────────────────────────────────────
    # Case 2: A PDF containing headings, paragraphs, and tables
    # ─────────────────────────────────────────────────────────────
    def test_case_2_pdf_headings_paragraphs_and_tables(self):
        pdf_text = (
            "# Financial Audit & Compliance Report 2026\n\n"
            "## 1. Operating Performance\n"
            "Revenue expanded by 18.4% with gross margins stabilizing across core product lines.\n\n"
            "## 2. Infrastructure Inventory Table\n"
            "| Asset Category | Nodes | Redundancy | Status |\n"
            "| Compute Clusters | 48 | N+2 Active | Passed |\n"
            "| Storage Volumes | 120 | Geo-Replicated | Passed |\n"
            "| Edge Gateways | 16 | Distributed | Active |\n\n"
            "## 3. Compliance Summary\n"
            "Zero material deficiencies observed during statutory testing."
        )
        pdf_bytes = _create_minimal_pdf(pdf_text)
        pdf_file = self.base_path / "audit_report.pdf"
        pdf_file.write_bytes(pdf_bytes)

        # Verify DocumentService converts PDF to markdown preserving content
        doc_service = DocumentService(self.config)
        md_file, err = doc_service.convert_to_markdown(pdf_file)
        self.assertIsNone(err)
        self.assertTrue(md_file.is_file())
        extracted_text = doc_service.extract_text_for_planning(md_file)
        self.assertIn("Financial Audit", extracted_text)

        # Run through workflow
        job_id = "test_case_2_job"
        self.store.create_job(job_id=job_id, project_name="Audit_Report", auto_approve=True)
        self.engine.run_job(
            job_id=job_id,
            source_file_path=pdf_file,
            job_params={"project_name": "Audit_Report", "slide_count": 4},
        )
        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertTrue(Path(job.output_pptx_path).is_file())

    # ─────────────────────────────────────────────────────────────
    # Case 3: A long document requiring substantial summarization
    # ─────────────────────────────────────────────────────────────
    def test_case_3_long_document_summarization(self):
        # Generate 40 paragraphs of technical whitepaper text
        paragraphs = []
        for i in range(1, 41):
            paragraphs.append(
                f"### Section {i}: Distributed Consensus & Fault Tolerance\n"
                f"In distributed systems, partition tolerance guarantees consistency under network partitions. "
                f"Subsystem {i} utilizes Raft consensus with heartbeat intervals of 150ms. "
                f"Evaluation demonstrates throughput of {1000 * i} ops/sec with p99 latency under 12ms."
            )
        long_text = "\n\n".join(paragraphs)
        long_doc = self.base_path / "long_whitepaper.md"
        long_doc.write_text(long_text, encoding="utf-8")

        # Request a condensed 4-slide executive brief
        job_id = "test_case_3_job"
        self.store.create_job(job_id=job_id, project_name="Whitepaper_Brief", auto_approve=True)
        self.engine.run_job(
            job_id=job_id,
            source_file_path=long_doc,
            job_params={"project_name": "Whitepaper_Brief", "slide_count": 4},
        )
        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED)
        prs = Presentation(job.output_pptx_path)
        self.assertEqual(len(prs.slides), 4)

    # ─────────────────────────────────────────────────────────────
    # Case 4: A document with charts, figures, or relevant images
    # ─────────────────────────────────────────────────────────────
    def test_case_4_document_with_figures_and_images(self):
        sample_doc = self.base_path / "system_architecture.md"
        sample_doc.write_text(
            "# System Architecture Review\n\n"
            "Slide 1 Cover features hero trading visual.\n"
            "Slide 3 Explanatory workflow contains 3D isometric diagram.\n",
            encoding="utf-8",
        )
        job_id = "test_case_4_job"
        self.store.create_job(job_id=job_id, project_name="Arch_Review", auto_approve=True)

        self.engine.run_job(
            job_id=job_id,
            source_file_path=sample_doc,
            job_params={"project_name": "Arch_Review", "slide_count": 4},
        )
        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED)

        # Verify asset analysis was executed
        proj_path = Path(job.project_path)
        self.assertTrue((proj_path / "icons").is_dir())

    # ─────────────────────────────────────────────────────────────
    # Case 5: A document with insufficient content for a requested slide
    # ─────────────────────────────────────────────────────────────
    def test_case_5_insufficient_content_handled_gracefully(self):
        sparse_doc = self.base_path / "sparse.txt"
        sparse_doc.write_text("Project Phoenix is an initiative to upgrade legacy servers.")

        job_id = "test_case_5_job"
        self.store.create_job(job_id=job_id, project_name="Sparse_Doc", auto_approve=True)

        # Requested 5 slides despite only 1 sentence
        self.engine.run_job(
            job_id=job_id,
            source_file_path=sparse_doc,
            job_params={"project_name": "Sparse_Doc", "slide_count": 5},
        )
        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertIsNotNone(job.output_pptx_path)

    # ─────────────────────────────────────────────────────────────
    # Case 6: Invalid or unsupported input
    # ─────────────────────────────────────────────────────────────
    def test_case_6_invalid_or_unsupported_input(self):
        doc_service = DocumentService(self.config)

        # 1. Nonexistent file
        valid, err = doc_service.validate_file(self.base_path / "nonexistent.pdf")
        self.assertFalse(valid)
        self.assertIn("does not exist", err)

        # 2. Unsupported extension
        unsupported = self.base_path / "binary.bin"
        unsupported.write_bytes(b"\x00\x01\x02")
        valid, err = doc_service.validate_file(unsupported)
        self.assertFalse(valid)
        self.assertIn("Unsupported file format", err)

    # ─────────────────────────────────────────────────────────────
    # Case 7: Missing or incorrect API credentials
    # ─────────────────────────────────────────────────────────────
    def test_case_7_missing_or_incorrect_api_credentials(self):
        # Azure OpenAI missing credentials
        cfg = AppConfig(
            ai_provider="azure_openai",
            azure_openai_endpoint="",
            azure_openai_api_key="",
        )
        errors = cfg.validate_provider_config()
        self.assertTrue(any("AZURE_OPENAI_ENDPOINT" in e for e in errors))

        # Standard OpenAI missing key
        cfg_openai = AppConfig(
            ai_provider="openai",
            openai_api_key=None,
        )
        errors_openai = cfg_openai.validate_provider_config()
        self.assertTrue(any("OPENAI_API_KEY" in e for e in errors_openai))

    # ─────────────────────────────────────────────────────────────
    # Case 8: API timeout, rate limiting, and malformed responses
    # ─────────────────────────────────────────────────────────────
    def test_case_8_api_timeout_and_retry_handling(self):
        from app.ai.client import AIError, OpenAIClient

        client = OpenAIClient(api_key="sk-test", max_retries=2)
        # Mock completions.create to simulate rate limit / timeout error
        client.client.chat.completions.create = MagicMock(
            side_effect=Exception("Error 429: Rate limit reached or timeout")
        )

        with patch("time.sleep"):  # Speed up test execution
            with self.assertRaises(AIError) as ctx:
                client.generate_text("System", "User")
            self.assertIn("failed after 2 attempts", str(ctx.exception))

    # ─────────────────────────────────────────────────────────────
    # Case 9: Invalid storyboard JSON
    # ─────────────────────────────────────────────────────────────
    def test_case_9_invalid_storyboard_json_handling(self):
        from pydantic import ValidationError
        from app.ai.structured_output import parse_structured_output

        malformed_json = '{"title": "Missing Slides Key"}'
        # Verify schema validation rejected the incomplete data
        with self.assertRaises(ValidationError):
            parse_structured_output(malformed_json, PresentationPlan)

    # ─────────────────────────────────────────────────────────────
    # Case 10: A slide-generation or rendering failure
    # ─────────────────────────────────────────────────────────────
    def test_case_10_unrecoverable_slide_failure_sets_failed_status(self):
        # Create a mock AI client that always produces unrepairable broken XML
        failing_client = MockAIClient()
        failing_client.generate_slide_svg = MagicMock(return_value="<svg><unclosed tag>")
        failing_client.repair_slide_svg = MagicMock(return_value="<svg><still unclosed tag>")

        failing_engine = WorkflowEngine(
            self.config,
            self.store,
            failing_client,
            self.image_provider,
        )

        job_id = "test_case_10_job"
        self.store.create_job(job_id=job_id, project_name="Failing_Job", auto_approve=True)
        doc = self.base_path / "simple.md"
        doc.write_text("# Test\nContent.")

        failing_engine.run_job(job_id=job_id, source_file_path=doc)
        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertIn("failed", job.error_message.lower())

    # ─────────────────────────────────────────────────────────────
    # Case 11: A quality-validation failure followed by repair
    # ─────────────────────────────────────────────────────────────
    def test_case_11_quality_validation_failure_followed_by_repair(self):
        val_service = ValidationService(self.config)

        # SVG with HTML entity &bull; and forbidden <foreignObject>
        broken_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
            '<rect width="1280" height="720" fill="#0F172A"/>'
            "<text x='80' y='90'>Point &bull; One</text>"
            "<foreignObject width='100' height='100'>bad</foreignObject>"
            "</svg>"
        )

        preflight_errors = val_service.preflight_svg_text(broken_svg)
        self.assertGreater(len(preflight_errors), 0)

        # Sanitization & repair
        sanitized = val_service.sanitize_svg_content(broken_svg)
        self.assertNotIn("<foreignObject", sanitized)
        self.assertNotIn("&bull;", sanitized)

        # Repaired version is valid
        repaired_errors = val_service.preflight_svg_text(sanitized)
        self.assertEqual(len(repaired_errors), 0)

    # ─────────────────────────────────────────────────────────────
    # Case 12: A second presentation with a different structure & design
    # ─────────────────────────────────────────────────────────────
    def test_case_12_second_presentation_with_distinct_design(self):
        doc_2 = self.base_path / "creative_strategy.md"
        doc_2.write_text(
            "# Minimalist Product Design Strategy\n\n"
            "Core Values: Simplicity, Typography, and Whitespace.\n"
            "Audience: Industrial Designers & Creative Directors.\n",
            encoding="utf-8",
        )

        job_id = "test_case_12_job"
        self.store.create_job(job_id=job_id, project_name="Creative_Strategy", auto_approve=True)

        # Use 3 slides, Light theme aesthetic
        self.engine.run_job(
            job_id=job_id,
            source_file_path=doc_2,
            job_params={
                "project_name": "Creative_Strategy",
                "slide_count": 3,
                "style_direction": "Swiss Minimal Light",
                "purpose": "Design Pitch",
            },
        )

        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED)
        prs = Presentation(job.output_pptx_path)
        self.assertEqual(len(prs.slides), 3)

    # ─────────────────────────────────────────────────────────────
    # Regression: Scenario 1 (Stock Market Prediction Using LSTM)
    # ─────────────────────────────────────────────────────────────
    def test_scenario_1_stock_market_lstm_prediction_regression(self):
        """Reproduce Scenario 1: Stock Market Prediction LSTM (10 slides, Fintech Navy theme)."""
        source_content = (
            "# Stock Market Prediction Using Deep Learning\n\n"
            "Authors: Subradip Manna, Yashraj Kastode, Urvija Palaskar, Nitin Kumar Shukla (22MIM10087), Divyansh Rathore\n"
            "Supervisor: Dr. A. Sirajudeen, VIT Bhopal University\n\n"
            "## 1. System Overview\n"
            "Time-series financial forecasting using Long Short-Term Memory (LSTM) recurrent networks.\n\n"
            "## 2. 8-Layer Architecture\n"
            "Ingestion, Min-Max Normalization, Moving Averages (MA50/100/200), LSTM Cell Gating, Dropout, Dense Layer.\n\n"
            "## 3. Empirical Results\n"
            "Evaluation on TSLA and AAPL equities achieved MSE of 0.0142 with sub-1.8s inference."
        )
        doc = self.base_path / "stock_market_report.md"
        doc.write_text(source_content, encoding="utf-8")

        job_id = "job_scenario_1_lstm"
        self.store.create_job(
            job_id=job_id,
            project_name="stock_market_lstm_prediction",
            auto_approve=True,
        )

        self.engine.run_job(
            job_id=job_id,
            source_file_path=doc,
            job_params={
                "project_name": "stock_market_lstm_prediction",
                "slide_count": 10,
                "style_direction": "High-Tech Financial Navy",
                "purpose": "Academic Defense & Technical Presentation",
                "enable_notes": True,
            },
        )

        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertTrue(Path(job.output_pptx_path).is_file())

        # Verify 10 slides generated
        prs = Presentation(job.output_pptx_path)
        self.assertEqual(len(prs.slides), 10)

        # Verify project structure matches Scenario 1 expectations
        proj_dir = Path(job.project_path)
        self.assertTrue((proj_dir / "design_spec.md").is_file())
        self.assertTrue((proj_dir / "spec_lock.md").is_file())
        self.assertTrue((proj_dir / "notes" / "total.md").is_file())
        svgs = list((proj_dir / "svg_output").glob("slide_*.svg"))
        self.assertEqual(len(svgs), 10)

    # ─────────────────────────────────────────────────────────────
    # Regression: Scenario 2 (SECL Medical Bill Scrutiny System)
    # ─────────────────────────────────────────────────────────────
    def test_scenario_2_secl_medical_bill_scrutiny_regression(self):
        """Reproduce Scenario 2: SECL Medical Bill Scrutiny (10 slides, Healthcare AI theme)."""
        source_content = (
            "# Medical Bill Scrutiny System\n"
            "Organization: South Eastern Coalfields Limited (SECL) / Techno Planner LLP\n"
            "Candidate: Nitin Kumar Shukla (22MIM10087, Integrated M.Tech AI, VIT Bhopal)\n"
            "Guides: Pravin Kumar (Manager Systems), Shantanu Mishra (GM Systems)\n\n"
            "## 1. Executive Summary\n"
            "Automated audit pipeline reducing claim processing latency from days to <3.5s.\n\n"
            "## 2. Core Modules\n"
            "Ingestion, Tesseract OCR, Clinical NER, Rule Verification, Perceptual Hashing Duplicate Screening.\n\n"
            "## 3. Financial Impact\n"
            "18.4% leakage prevented across statutory CGHS tariff benchmarks."
        )
        doc = self.base_path / "secl_internship_report.md"
        doc.write_text(source_content, encoding="utf-8")

        job_id = "job_scenario_2_secl"
        self.store.create_job(
            job_id=job_id,
            project_name="secl_medical_bill_scrutiny",
            auto_approve=True,
        )

        self.engine.run_job(
            job_id=job_id,
            source_file_path=doc,
            job_params={
                "project_name": "secl_medical_bill_scrutiny",
                "slide_count": 10,
                "style_direction": "Enterprise Healthcare AI",
                "purpose": "Industrial Project Presentation",
                "enable_notes": True,
            },
        )

        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertTrue(Path(job.output_pptx_path).is_file())

        prs = Presentation(job.output_pptx_path)
        self.assertEqual(len(prs.slides), 10)

        proj_dir = Path(job.project_path)
        self.assertTrue((proj_dir / "design_spec.md").is_file())
        self.assertTrue((proj_dir / "spec_lock.md").is_file())
        svgs = list((proj_dir / "svg_output").glob("slide_*.svg"))
        self.assertEqual(len(svgs), 10)


if __name__ == "__main__":
    unittest.main()
