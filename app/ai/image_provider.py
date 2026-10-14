"""Image provider abstraction for presentation asset generation and resolution."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from app.utils.subprocess_runner import run_command_safe

logger = logging.getLogger("ppt_master.image_provider")


class BaseImageProvider(ABC):
    """Abstract interface for presentation image asset providers."""

    @abstractmethod
    def acquire_image(
        self,
        prompt: str,
        target_path: Path,
        aspect_ratio: str = "16:9",
    ) -> bool:
        """Acquire or generate an image for the slide.

        Args:
            prompt: Visual description or search query.
            target_path: Destination path in project images/ directory.
            aspect_ratio: Preferred aspect ratio.

        Returns:
            True if image was acquired and written to target_path, False otherwise.
        """
        pass


class LocalAssetImageProvider(BaseImageProvider):
    """Provider that uses existing project assets or gracefully skips."""

    def acquire_image(
        self,
        prompt: str,
        target_path: Path,
        aspect_ratio: str = "16:9",
    ) -> bool:
        if target_path.is_file():
            logger.info("Reusing existing image asset: %s", target_path)
            return True
        logger.info("Local provider: skipping external generation for %s", target_path.name)
        return False


class AzureOpenAIImageProvider(BaseImageProvider):
    """Generates images via Azure OpenAI DALL-E if configured."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        api_version: str,
        deployment: str,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.api_version = api_version
        self.deployment = deployment

    def acquire_image(
        self,
        prompt: str,
        target_path: Path,
        aspect_ratio: str = "16:9",
    ) -> bool:
        try:
            import requests

            url = f"{self.endpoint}/openai/deployments/{self.deployment}/images/generations?api-version={self.api_version}"
            headers = {
                "api-key": self.api_key,
                "Content-Type": "application/json",
            }
            # Map aspect ratio to supported DALL-E 3 size
            size = "1792x1024" if aspect_ratio == "16:9" else "1024x1024"
            payload = {
                "prompt": prompt,
                "n": 1,
                "size": size,
                "quality": "standard",
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                image_url = data["data"][0]["url"]
                img_data = requests.get(image_url, timeout=30).content
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(img_data)
                logger.info("Successfully generated image with Azure OpenAI: %s", target_path)
                return True
            else:
                logger.warning(
                    "Azure OpenAI image gen returned status %d: %s",
                    resp.status_code,
                    resp.text,
                )
                return False
        except Exception as exc:
            logger.warning("Azure OpenAI image gen failed: %s", exc)
            return False


class NanoBananaImageProvider(BaseImageProvider):
    """Generates images using the project's Nano Banana model (Gemini / Fal / OpenRouter)."""

    def __init__(
        self,
        config: Any,
        backend: str = "gemini",
        model: str = "gemini-nano-banana-2.1",
        api_key: Optional[str] = None,
    ) -> None:
        self.config = config
        self.backend = backend
        self.model = model
        self.api_key = api_key
        self.script_path = (
            getattr(config, "skill_dir", Path(__file__).resolve().parent.parent.parent / "skills" / "ppt-master")
            / "scripts"
            / "image_gen.py"
        )

    def acquire_image(
        self,
        prompt: str,
        target_path: Path,
        aspect_ratio: str = "16:9",
    ) -> bool:
        """Generate an image using the Nano Banana image model."""
        if target_path.is_file():
            logger.info("Reusing existing image asset: %s", target_path)
            return True

        target_path.parent.mkdir(parents=True, exist_ok=True)
        ratio = aspect_ratio if aspect_ratio in ["16:9", "4:3", "1:1", "3:4", "9:16"] else "16:9"

        cmd = [
            self.config.python_executable,
            str(self.script_path),
            prompt,
            "--backend",
            self.backend,
            "--model",
            self.model,
            "--aspect_ratio",
            ratio,
            "--output",
            str(target_path.parent),
            "--filename",
            target_path.stem,
        ]

        env = dict(os.environ)
        if self.api_key:
            if self.backend == "gemini":
                env["GEMINI_API_KEY"] = self.api_key
            elif self.backend == "fal":
                env["FAL_KEY"] = self.api_key
            elif self.backend == "openrouter":
                env["OPENROUTER_API_KEY"] = self.api_key

        logger.info(
            "Generating image via Nano Banana (%s / %s): %s",
            self.backend,
            self.model,
            target_path.name,
        )
        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            env=env,
            timeout=120,
        )

        if not res.is_success:
            logger.warning("Nano Banana generation failed: %s %s", res.stderr, res.stdout)
            return False

        if target_path.is_file():
            return True
        for candidate in target_path.parent.glob(f"{target_path.stem}.*"):
            if candidate.is_file() and candidate.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
                return True

        return False

    def process_manifest(self, manifest_path: Path) -> bool:
        """Run batch generation for an image_prompts.json manifest using Nano Banana."""
        if not manifest_path.is_file():
            return False

        cmd = [
            self.config.python_executable,
            str(self.script_path),
            "--manifest",
            str(manifest_path),
            "--backend",
            self.backend,
            "--model",
            self.model,
        ]

        env = dict(os.environ)
        if self.api_key:
            if self.backend == "gemini":
                env["GEMINI_API_KEY"] = self.api_key
            elif self.backend == "fal":
                env["FAL_KEY"] = self.api_key
            elif self.backend == "openrouter":
                env["OPENROUTER_API_KEY"] = self.api_key

        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            env=env,
            timeout=300,
        )
        return res.is_success


class FluxImageProvider(BaseImageProvider):
    """Generates high-fidelity contextual images using Flux 2 Pro / Black Forest Labs API."""

    def __init__(
        self,
        config: Any,
        api_key: Optional[str] = None,
        model: str = "flux-2-pro",
        base_url: str = "https://api.bfl.ai",
        endpoint: Optional[str] = None,
    ) -> None:
        self.config = config
        self.api_key = (
            api_key
            or getattr(config, "flux_api_key", None)
            or os.getenv("FLUX_API_KEY")
            or os.getenv("FLUX_2_PRO_API_KEY")
            or os.getenv("BFL_API_KEY")
        )
        self.model = (
            model
            or getattr(config, "flux_model", None)
            or os.getenv("FLUX_MODEL")
            or "flux-2-pro"
        )
        self.endpoint = (
            endpoint
            or getattr(config, "flux_endpoint", None)
            or os.getenv("FLUX_ENDPOINT")
        )
        self.base_url = (
            base_url
            or getattr(config, "flux_base_url", None)
            or os.getenv("FLUX_BASE_URL")
            or "https://api.bfl.ai"
        ).rstrip("/")
        self.script_path = (
            getattr(config, "skill_dir", Path(__file__).resolve().parent.parent.parent / "skills" / "ppt-master")
            / "scripts"
            / "image_gen.py"
        )

    def acquire_image(
        self,
        prompt: str,
        target_path: Path,
        aspect_ratio: str = "16:9",
    ) -> bool:
        """Generate one image with Flux 2 Pro and save to target_path."""
        if target_path.is_file():
            logger.info("Reusing existing image asset: %s", target_path)
            return True

        if not self.api_key:
            logger.warning("Flux 2 Pro API key is not configured. Skipping image generation.")
            return False

        target_path.parent.mkdir(parents=True, exist_ok=True)
        ratio = aspect_ratio if aspect_ratio in ["16:9", "4:3", "1:1", "3:2", "2:3", "9:16"] else "16:9"
        aspect_dimensions = {
            "1:1": (1024, 1024),
            "16:9": (1024, 576),
            "4:3": (1024, 768),
            "3:2": (1024, 683),
            "2:3": (683, 1024),
            "9:16": (576, 1024),
        }
        w, h = aspect_dimensions.get(ratio, (1024, 576))

        # Attempt 1: Azure AI Studio MaaS endpoint (if configured or URL points to azure.com)
        active_azure_url = None
        if self.endpoint and "services.ai.azure.com" in self.endpoint:
            active_azure_url = self.endpoint
        elif "services.ai.azure.com" in self.base_url:
            active_azure_url = self.base_url

        if active_azure_url:
            try:
                import base64
                import requests

                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                }
                payload = {
                    "prompt": prompt,
                    "model": "FLUX.2-pro",
                    "width": w,
                    "height": h,
                    "n": 1,
                }
                logger.info("Submitting Flux 2 Pro request to Azure AI Studio (%s, %dx%d)...", active_azure_url, w, h)
                resp = requests.post(active_azure_url, headers=headers, json=payload, timeout=90)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data", [])
                    if items and "b64_json" in items[0]:
                        raw_bytes = base64.b64decode(items[0]["b64_json"])
                        if target_path.suffix.lower() == ".png" and not raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                            try:
                                import io
                                from PIL import Image
                                img = Image.open(io.BytesIO(raw_bytes))
                                img.save(target_path, format="PNG")
                            except Exception:
                                target_path.write_bytes(raw_bytes)
                        else:
                            target_path.write_bytes(raw_bytes)
                        logger.info("Successfully generated Flux 2 Pro image via Azure AI Studio: %s (%d bytes)", target_path, target_path.stat().st_size)
                        return True
                    elif items and "url" in items[0]:
                        raw_bytes = requests.get(items[0]["url"], timeout=60).content
                        if target_path.suffix.lower() == ".png" and not raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                            try:
                                import io
                                from PIL import Image
                                img = Image.open(io.BytesIO(raw_bytes))
                                img.save(target_path, format="PNG")
                            except Exception:
                                target_path.write_bytes(raw_bytes)
                        else:
                            target_path.write_bytes(raw_bytes)
                        logger.info("Successfully downloaded Flux 2 Pro image via Azure AI Studio URL: %s", target_path)
                        return True
                else:
                    logger.warning("Azure AI Studio Flux 2 Pro request returned %d: %s", resp.status_code, resp.text)
            except Exception as exc:
                logger.warning("Azure AI Studio Flux 2 Pro request failed: %s", exc)

        # Attempt 2: Direct BFL HTTP API with async polling
        try:
            import requests

            headers = {
                "x-key": self.api_key,
                "accept": "application/json",
                "Content-Type": "application/json",
            }
            payload: dict[str, Any] = {
                "prompt": prompt,
                "prompt_upsampling": False,
                "output_format": "png",
            }
            aspect_dimensions = {
                "1:1": (1024, 1024),
                "16:9": (1024, 576),
                "4:3": (1024, 768),
                "3:2": (1024, 683),
                "2:3": (683, 1024),
                "9:16": (576, 1024),
            }
            if "ultra" in self.model.lower():
                payload["aspect_ratio"] = ratio
            else:
                w, h = aspect_dimensions.get(ratio, (1024, 576))
                payload["width"] = w
                payload["height"] = h

            endpoint = f"/v1/{self.model.replace('_', '-')}"
            submit_url = f"{self.base_url}{endpoint}"

            logger.info("Submitting Flux 2 Pro request to %s (%s, ratio=%s)...", submit_url, self.model, ratio)
            resp = requests.post(submit_url, headers=headers, json=payload, timeout=60)

            # Fallback to flux-pro-1.1 if flux-2-pro specific path is not found on older BFL gateway
            if resp.status_code == 404 and self.model in ("flux-2-pro", "flux_2_pro"):
                fallback_url = f"{self.base_url}/v1/flux-pro-1.1"
                logger.info("Retrying Flux with endpoint %s...", fallback_url)
                resp = requests.post(fallback_url, headers=headers, json=payload, timeout=60)

            if resp.status_code == 200:
                data = resp.json()
                polling_url = data.get("polling_url")
                if not polling_url and "id" in data:
                    polling_url = f"{self.base_url}/v1/get_result?id={data['id']}"

                if polling_url:
                    import time
                    start_time = time.time()
                    image_url = None
                    while time.time() - start_time < 180:
                        poll_resp = requests.get(
                            polling_url,
                            headers={"x-key": self.api_key, "accept": "application/json"},
                            timeout=30,
                        )
                        if poll_resp.status_code == 200:
                            p_data = poll_resp.json()
                            status = p_data.get("status")
                            if status == "Ready":
                                image_url = (p_data.get("result") or {}).get("sample")
                                break
                            elif status in ("Error", "Failed", "Request Moderated", "Content Moderated"):
                                logger.warning("Flux 2 Pro generation failed: %s", p_data)
                                break
                        time.sleep(2)

                    if image_url:
                        img_bytes = requests.get(image_url, timeout=60).content
                        target_path.write_bytes(img_bytes)
                        logger.info("Successfully generated Flux 2 Pro image: %s", target_path)
                        return True
            else:
                logger.warning("Direct Flux 2 Pro request returned %d: %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.warning("Direct Flux 2 Pro request failed, attempting CLI fallback: %s", exc)

        # Attempt 2: Fallback to skill image_gen.py with BFL backend
        env = dict(os.environ)
        env["BFL_API_KEY"] = self.api_key
        env["FLUX_API_KEY"] = self.api_key
        if self.base_url:
            env["BFL_BASE_URL"] = self.base_url
        cmd = [
            self.config.python_executable,
            str(self.script_path),
            prompt,
            "--backend",
            "bfl",
            "--model",
            self.model,
            "--aspect_ratio",
            ratio,
            "--output",
            str(target_path.parent),
            "--filename",
            target_path.stem,
        ]
        res = run_command_safe(cmd, cwd=self.config.repo_root, env_overrides=env, timeout=240)
        if target_path.is_file():
            return True
        for cand in target_path.parent.glob(f"{target_path.stem}.*"):
            if cand.is_file() and cand.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
                return True

        logger.error("Flux 2 Pro image generation failed: %s", res.stderr or res.stdout)
        return False

    def process_manifest(self, manifest_path: Path) -> bool:
        """Run batch generation for an image_prompts.json manifest using Flux / BFL."""
        if not manifest_path.is_file() or not self.api_key:
            return False

        # If using Azure AI Studio, process entries directly via HTTP
        active_azure_url = (
            self.endpoint if (self.endpoint and "services.ai.azure.com" in self.endpoint)
            else (self.base_url if "services.ai.azure.com" in self.base_url else None)
        )
        if active_azure_url:
            try:
                import json
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                images = data.get("images", [])
                parent_dir = manifest_path.parent
                for item in images:
                    fn = item.get("filename")
                    pr = item.get("prompt")
                    ar = item.get("aspect_ratio", "16:9")
                    if fn and pr:
                        self.acquire_image(prompt=pr, target_path=parent_dir / fn, aspect_ratio=ar)
                return True
            except Exception as exc:
                logger.warning("Azure AI Studio manifest processing warning: %s", exc)
                return False

        cmd = [
            self.config.python_executable,
            str(self.script_path),
            "--manifest",
            str(manifest_path),
            "--backend",
            "bfl",
            "--model",
            self.model,
        ]
        env = dict(os.environ)
        env["BFL_API_KEY"] = self.api_key
        env["FLUX_API_KEY"] = self.api_key
        if self.base_url:
            env["BFL_BASE_URL"] = self.base_url
        res = run_command_safe(cmd, cwd=self.config.repo_root, env_overrides=env, timeout=400)
        return res.is_success


def get_image_provider(config: Any) -> BaseImageProvider:
    """Factory to create appropriate image provider based on configuration."""
    provider_name = getattr(config, "image_provider", "local").lower()

    # 1. Flux 2 Pro / BFL provider (explicit or when FLUX API key is set)
    flux_key = (
        getattr(config, "flux_api_key", None)
        or os.getenv("FLUX_API_KEY")
        or os.getenv("FLUX_2_PRO_API_KEY")
        or os.getenv("BFL_API_KEY")
    )
    if provider_name in ("flux", "flux-2-pro", "flux_2_pro", "flux-pro", "bfl") or (provider_name in ("auto", "default", "local") and flux_key):
        if flux_key:
            return FluxImageProvider(
                config=config,
                api_key=flux_key,
                model=getattr(config, "flux_model", "flux-2-pro"),
                base_url=getattr(config, "flux_base_url", "https://api.bfl.ai"),
                endpoint=getattr(config, "flux_endpoint", None),
            )

    # 2. Nano Banana provider (Gemini / Fal / OpenRouter)
    if provider_name in ("nano_banana", "nano-banana", "gemini", "google"):
        backend = getattr(config, "nano_banana_backend", "gemini")
        api_key = config.gemini_api_key or os.getenv("GEMINI_API_KEY")
        model = getattr(config, "gemini_model", "gemini-nano-banana-2.1")
        if backend == "fal":
            api_key = config.fal_key or os.getenv("FAL_KEY") or os.getenv("FAL_API_KEY")
            model = "google/nano-banana-2.1"
        elif backend == "openrouter":
            api_key = config.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
            model = "google/gemini-nano-banana-2.1"

        if api_key:
            return NanoBananaImageProvider(
                config=config,
                backend=backend,
                model=model,
                api_key=api_key,
            )

    # 3. Azure OpenAI DALL-E provider
    if (
        provider_name == "azure_openai"
        and getattr(config, "azure_openai_endpoint", None)
        and getattr(config, "azure_openai_api_key", None)
        and getattr(config, "image_deployment", None)
    ):
        return AzureOpenAIImageProvider(
            endpoint=config.azure_openai_endpoint,
            api_key=config.azure_openai_api_key,
            api_version=config.azure_openai_api_version,
            deployment=config.image_deployment,
        )

    # 4. Automatic fallback: If GEMINI_API_KEY is available in the environment, activate Nano Banana
    gemini_key = getattr(config, "gemini_api_key", None) or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        return NanoBananaImageProvider(
            config=config,
            backend="gemini",
            model=getattr(config, "gemini_model", "gemini-nano-banana-2.1"),
            api_key=gemini_key,
        )

    return LocalAssetImageProvider()
