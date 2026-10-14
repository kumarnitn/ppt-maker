"""Unit tests for configuration validation and secret redaction."""

import unittest
from app.config import AppConfig


class TestAppConfig(unittest.TestCase):
    def test_default_config(self):
        cfg = AppConfig()
        self.assertIsNotNone(cfg.repo_root)
        self.assertIsNotNone(cfg.skill_dir)
        self.assertIsNotNone(cfg.projects_dir)
        self.assertEqual(cfg.max_retries_per_slide, 3)

    def test_secret_redaction(self):
        cfg = AppConfig(
            azure_openai_api_key="super-secret-key-12345",
            openai_api_key="sk-another-secret-key",
        )
        redacted = cfg.redacted_dict()
        self.assertEqual(redacted["azure_openai_api_key"], "***REDACTED***")
        self.assertEqual(redacted["openai_api_key"], "***REDACTED***")

    def test_provider_validation_azure(self):
        cfg = AppConfig(
            ai_provider="azure_openai",
            azure_openai_endpoint="",
            azure_openai_api_key="",
            azure_openai_deployment="",
        )
        errors = cfg.validate_provider_config()
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("AZURE_OPENAI_ENDPOINT" in e for e in errors))

    def test_provider_validation_mock(self):
        cfg = AppConfig(ai_provider="mock")
        errors = cfg.validate_provider_config()
        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
