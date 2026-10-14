"""Unit tests for AI client abstractions, prompts, and structured parsing."""

import unittest
from app.ai.client import MockAIClient, get_ai_client
from app.ai.structured_output import clean_markdown_fences, parse_structured_output
from app.config import AppConfig
from app.schemas.plan import PresentationPlan
from app.schemas.spec import DesignSpecSchema


class TestAIClient(unittest.TestCase):
    def setUp(self):
        self.mock_client = MockAIClient()

    def test_mock_generate_plan(self):
        plan = self.mock_client.generate_plan(
            document_text="Test overview content",
            params={"project_name": "Test Deck", "slide_count": 4},
        )
        self.assertIsInstance(plan, PresentationPlan)
        self.assertGreater(len(plan.slides), 0)
        self.assertTrue(plan.title)
        self.assertEqual(plan.slides[0].index, 1)

    def test_mock_generate_design_spec(self):
        plan = self.mock_client.generate_plan("Test content", {})
        spec = self.mock_client.generate_design_spec(plan, {})
        self.assertIsInstance(spec, DesignSpecSchema)
        self.assertEqual(spec.view_box, "0 0 1280 720")
        self.assertTrue(spec.palette.background)

    def test_mock_generate_slide_svg(self):
        plan = self.mock_client.generate_plan("Test content", {})
        spec = self.mock_client.generate_design_spec(plan, {})
        svg = self.mock_client.generate_slide_svg(plan.slides[0], spec, len(plan.slides))
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.strip().endswith("</svg>"))
        self.assertIn("1280", svg)
        self.assertIn("720", svg)

    def test_mock_repair_slide_svg(self):
        repaired = self.mock_client.repair_slide_svg(
            "<svg>invalid</svg>", "XML Parse error"
        )
        self.assertTrue(repaired.startswith("<svg"))
        self.assertTrue(repaired.strip().endswith("</svg>"))

    def test_clean_markdown_fences(self):
        wrapped = "```json\n{\"key\": \"val\"}\n```"
        self.assertEqual(clean_markdown_fences(wrapped), "{\"key\": \"val\"}")
        wrapped_xml = "```xml\n<svg></svg>\n```"
        self.assertEqual(clean_markdown_fences(wrapped_xml), "<svg></svg>")

    def test_factory_returns_mock_when_configured(self):
        cfg = AppConfig(ai_provider="mock")
        client = get_ai_client(cfg)
        self.assertIsInstance(client, MockAIClient)


if __name__ == "__main__":
    unittest.main()
