"""Unit tests for SVG validation service and quality gates."""

import unittest
from app.config import AppConfig
from app.services.validation_service import ValidationService


class TestValidationService(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        self.val_service = ValidationService(self.config)

    def test_preflight_valid_svg(self):
        clean_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
          <rect id="bg" x="0" y="0" width="1280" height="720" fill="#0F172A"/>
          <text x="80" y="90" font-family="Arial" font-size="36" fill="#FFFFFF">Valid Title</text>
        </svg>"""
        errors = self.val_service.preflight_svg_text(clean_svg)
        self.assertEqual(len(errors), 0)

    def test_preflight_detects_html_entities(self):
        invalid_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
          <text x="80" y="90">Bullet &bull; point and dash &mdash; here</text>
        </svg>"""
        errors = self.val_service.preflight_svg_text(invalid_svg)
        self.assertTrue(any("&bull;" in e for e in errors))
        self.assertTrue(any("&mdash;" in e for e in errors))

    def test_preflight_detects_forbidden_tags(self):
        invalid_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
          <style> .red { fill: red; } </style>
          <foreignObject width="100" height="100"><p>test</p></foreignObject>
        </svg>"""
        errors = self.val_service.preflight_svg_text(invalid_svg)
        self.assertTrue(any("<style" in e for e in errors))
        self.assertTrue(any("<foreignobject" in e for e in errors))

    def test_preflight_detects_xml_syntax_error(self):
        broken_xml = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
          <rect x="0" y="0" width="100">
        </svg>"""
        errors = self.val_service.preflight_svg_text(broken_xml)
        self.assertTrue(any("XML Parse Error" in e for e in errors))

    def test_preflight_detects_class_attribute(self):
        with_class = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">
          <rect class="card-bg" x="0" y="0" width="100" height="100"/>
        </svg>"""
        errors = self.val_service.preflight_svg_text(with_class)
        self.assertTrue(any("class" in e for e in errors))

    def test_normalize_svg_viewbox_bounds_transformed_group(self):
        raw_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
          <g id="card-2" transform="translate(720, 200)">
            <rect x="0" y="0" width="560" height="480"/>
            <text x="20" y="80" font-size="20">Two-column layout with sustainability metrics and images of green design elements.</text>
          </g>
        </svg>"""
        normalized = self.val_service.normalize_svg_viewbox_bounds(raw_svg)
        self.assertIn("<tspan", normalized)
        self.assertIn('x="20"', normalized)
        self.assertIn('width="500"', normalized)

    def test_normalize_svg_viewbox_bounds_clamps_vertical_baseline(self):
        raw_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
          <text x="80" y="720" font-size="16">Footer text right on bottom edge</text>
        </svg>"""
        normalized = self.val_service.normalize_svg_viewbox_bounds(raw_svg)
        self.assertIn('y="660"', normalized)


if __name__ == "__main__":
    unittest.main()

