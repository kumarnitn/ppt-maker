"""Unit tests for Nano Banana and Image Provider integration."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.ai.image_provider import (
    BaseImageProvider,
    FluxImageProvider,
    LocalAssetImageProvider,
    NanoBananaImageProvider,
    get_image_provider,
)
from app.config import AppConfig


class TestImageProvider(unittest.TestCase):
    def test_local_provider_fallback(self):
        cfg = AppConfig(image_provider="local", gemini_api_key=None)
        provider = get_image_provider(cfg)
        self.assertIsInstance(provider, LocalAssetImageProvider)

    def test_nano_banana_provider_gemini_resolution(self):
        cfg = AppConfig(
            image_provider="nano_banana",
            gemini_api_key="test-gemini-key",
            nano_banana_backend="gemini",
            gemini_model="gemini-nano-banana-2.1",
        )
        provider = get_image_provider(cfg)
        self.assertIsInstance(provider, NanoBananaImageProvider)
        self.assertEqual(provider.backend, "gemini")
        self.assertEqual(provider.model, "gemini-nano-banana-2.1")
        self.assertEqual(provider.api_key, "test-gemini-key")

    def test_nano_banana_provider_fal_resolution(self):
        cfg = AppConfig(
            image_provider="nano_banana",
            nano_banana_backend="fal",
            fal_key="fal-test-key",
        )
        provider = get_image_provider(cfg)
        self.assertIsInstance(provider, NanoBananaImageProvider)
        self.assertEqual(provider.backend, "fal")
        self.assertEqual(provider.model, "google/nano-banana-2.1")
        self.assertEqual(provider.api_key, "fal-test-key")

    def test_nano_banana_redacted_config(self):
        cfg = AppConfig(
            gemini_api_key="secret-gemini-key",
            nano_banana_backend="gemini",
        )
        redacted = cfg.redacted_dict()
        self.assertTrue(redacted["nano_banana_ready"])
        self.assertEqual(redacted["gemini_api_key"], "***REDACTED***")
        self.assertEqual(redacted["nano_banana_backend"], "gemini")

    @patch("app.ai.image_provider.run_command_safe")
    def test_nano_banana_acquire_image_invocation(self, mock_run):
        mock_run.return_value = MagicMock(is_success=True, returncode=0)
        cfg = AppConfig(
            image_provider="nano_banana",
            gemini_api_key="dummy-key",
            nano_banana_backend="gemini",
            gemini_model="gemini-nano-banana-2.1",
        )
        provider = NanoBananaImageProvider(
            config=cfg,
            backend="gemini",
            model="gemini-nano-banana-2.1",
            api_key="dummy-key",
        )

        test_dest = Path("/tmp/test_slide_image.png")
        # is_file returns False initially (needs gen), then True after gen
        with patch.object(Path, "is_file", side_effect=[False, True]):
            res = provider.acquire_image("A futuristic city skyline", test_dest, "16:9")
            self.assertTrue(res)
            self.assertTrue(mock_run.called)
            args, kwargs = mock_run.call_args
            cmd = args[0]
            self.assertIn("image_gen.py", cmd[1])
            self.assertIn("A futuristic city skyline", cmd[2])
            self.assertIn("--backend", cmd)
            self.assertIn("gemini", cmd)
            self.assertIn("--model", cmd)
            self.assertIn("gemini-nano-banana-2.1", cmd)


    def test_flux_provider_resolution(self):
        cfg = AppConfig(
            image_provider="flux",
            flux_api_key="test-flux-key-123",
            flux_model="flux-2-pro",
        )
        provider = get_image_provider(cfg)
        self.assertIsInstance(provider, FluxImageProvider)
        self.assertEqual(provider.model, "flux-2-pro")
        self.assertEqual(provider.api_key, "test-flux-key-123")

    def test_flux_auto_provider_resolution_with_key(self):
        cfg = AppConfig(
            image_provider="auto",
            flux_api_key="test-flux-key-auto",
        )
        provider = get_image_provider(cfg)
        self.assertIsInstance(provider, FluxImageProvider)

    def test_flux_redacted_config(self):
        cfg = AppConfig(
            flux_api_key="secret-flux-key",
            flux_model="flux-2-pro",
        )
        redacted = cfg.redacted_dict()
        self.assertTrue(redacted["flux_ready"])
        self.assertEqual(redacted["flux_model"], "flux-2-pro")
        self.assertEqual(redacted["flux_api_key"], "***REDACTED***")

    @patch("requests.post")
    @patch("requests.get")
    def test_flux_acquire_image_direct_api(self, mock_get, mock_post):
        mock_post_resp = MagicMock(status_code=200)
        mock_post_resp.json.return_value = {
            "id": "bfl-task-abc123",
            "polling_url": "https://api.bfl.ai/v1/get_result?id=bfl-task-abc123",
        }
        mock_post.return_value = mock_post_resp

        mock_poll_resp = MagicMock(status_code=200)
        mock_poll_resp.json.return_value = {
            "status": "Ready",
            "result": {"sample": "https://delivery.bfl.ai/image.png"},
        }
        mock_img_resp = MagicMock(status_code=200, content=b"\x89PNG\r\n\x1a\nfakeimage")
        mock_get.side_effect = [mock_poll_resp, mock_img_resp]

        cfg = AppConfig(flux_api_key="test-key")
        provider = FluxImageProvider(config=cfg, api_key="test-key", model="flux-2-pro")

        target_file = Path("/tmp/flux_test_image.png")
        with patch.object(Path, "is_file", return_value=False), patch.object(Path, "write_bytes") as mock_wb:
            res = provider.acquire_image("A futuristic smart factory", target_file, "16:9")
            self.assertTrue(res)
            self.assertTrue(mock_wb.called)
            self.assertEqual(mock_wb.call_args[0][0], b"\x89PNG\r\n\x1a\nfakeimage")


if __name__ == "__main__":
    unittest.main()
