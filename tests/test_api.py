"""API integration tests for Flask web routes and endpoints."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from app.config import AppConfig
from app.main import create_app
from app.orchestration.state import JobStore


class TestApiEndpoints(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)

        # Configure test environment
        self.config = AppConfig(
            ai_provider="mock",
            data_dir=self.base_path / "data",
            projects_dir=self.base_path / "projects",
        )
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_health_endpoint(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("PPT Master", data["service"])

    def test_config_endpoint_redacts_secrets(self):
        res = self.client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("config", data)
        # Verify no raw api keys exposed
        for k, v in data["config"].items():
            if "key" in k and v:
                self.assertEqual(v, "***REDACTED***")

    def test_stats_endpoint(self):
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("total_jobs", data)

    def test_create_job_via_api(self):
        sample_content = b"# API Test Document\n\nExecutive report content for presentation."
        data = {
            "file": (io.BytesIO(sample_content), "test_api_doc.md"),
            "project_name": "API_Test_Deck",
            "purpose": "Executive Presentation",
            "slide_count": "4",
            "auto_approve": "true",
        }
        res = self.client.post("/api/jobs", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 201)
        job_data = res.get_json()
        self.assertIn("job_id", job_data)
        job_id = job_data["job_id"]

        # Check job status via GET
        status_res = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.get_json()
        self.assertEqual(status_data["job_id"], job_id)

    def test_list_jobs_via_api(self):
        res = self.client.get("/api/jobs")
        self.assertEqual(res.status_code, 200)
        jobs = res.get_json()
        self.assertIsInstance(jobs, list)


if __name__ == "__main__":
    unittest.main()
