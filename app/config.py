"""Application configuration module."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


def _load_dotenv_if_present() -> None:
    """Manually parse .env file if present in repo root without third-party requirement."""
    repo_root = Path(__file__).resolve().parent.parent
    env_file = repo_root / ".env"
    if not env_file.is_file():
        return
    try:
        with env_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass


_load_dotenv_if_present()


class AppConfig(BaseModel):
    """Configuration settings for PPT Master application."""

    # Provider: azure_openai, openai, mock
    ai_provider: str = Field(
        default_factory=lambda: os.getenv("AI_PROVIDER", "azure_openai").lower()
    )

    # Azure OpenAI credentials
    azure_openai_endpoint: Optional[str] = Field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    azure_openai_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY")
    )
    azure_openai_api_version: str = Field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    )
    azure_openai_deployment: Optional[str] = Field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT")
    )

    # Standard OpenAI credentials
    openai_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )
    openai_model: str = Field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o")
    )
    openai_base_url: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL")
    )

    # Image generation settings
    image_provider: str = Field(
        default_factory=lambda: (
            os.getenv("IMAGE_PROVIDER") or os.getenv("IMAGE_BACKEND") or "local"
        ).lower()
    )
    image_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("IMAGE_API_KEY")
    )
    image_deployment: Optional[str] = Field(
        default_factory=lambda: os.getenv("IMAGE_DEPLOYMENT", "dall-e-3")
    )

    # Nano Banana image generation settings (Gemini / Fal / OpenRouter)
    gemini_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    )
    gemini_model: str = Field(
        default_factory=lambda: os.getenv("GEMINI_MODEL") or os.getenv("NANO_BANANA_MODEL", "gemini-nano-banana-2.1")
    )
    nano_banana_backend: str = Field(
        default_factory=lambda: os.getenv("NANO_BANANA_BACKEND", "gemini").lower()
    )
    fal_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("FAL_KEY") or os.getenv("FAL_API_KEY")
    )
    openrouter_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY")
    )

    # Flux Image Generation settings (Flux 2 Pro / BFL)
    flux_api_key: Optional[str] = Field(
        default_factory=lambda: (
            os.getenv("FLUX_API_KEY")
            or os.getenv("FLUX_2_PRO_API_KEY")
            or os.getenv("BFL_API_KEY")
        )
    )
    flux_model: str = Field(
        default_factory=lambda: os.getenv("FLUX_MODEL", "flux-2-pro")
    )
    flux_base_url: str = Field(
        default_factory=lambda: os.getenv("FLUX_BASE_URL", "https://api.bfl.ai")
    )
    flux_endpoint: Optional[str] = Field(
        default_factory=lambda: (
            os.getenv("FLUX_ENDPOINT")
            or os.getenv("FLUX_BASE_URL")
        )
    )

    # Application Paths
    repo_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent
    )
    skill_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "skills" / "ppt-master"
    )
    projects_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "projects"
    )
    data_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data"
    )

    # Python interpreter in .venv or system
    python_executable: str = Field(
        default_factory=lambda: (
            str(Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python3")
            if (Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python3").is_file()
            else "python3"
        )
    )

    # Server settings
    host: str = Field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "5000")))
    debug: bool = Field(default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true")

    # Workflow constraints
    max_retries_per_slide: int = 3
    subprocess_timeout: int = 180
    max_slides_limit: int = 50
    upload_max_size_mb: int = 50

    def redacted_dict(self) -> dict[str, str | int | bool | None]:
        """Return config with API keys and secrets redacted."""
        nano_banana_ready = bool(
            self.gemini_api_key or self.fal_key or self.openrouter_api_key
        )
        return {
            "ai_provider": self.ai_provider,
            "azure_openai_endpoint": self.azure_openai_endpoint,
            "azure_openai_api_key": "***REDACTED***" if self.azure_openai_api_key else None,
            "azure_openai_api_version": self.azure_openai_api_version,
            "azure_openai_deployment": self.azure_openai_deployment,
            "openai_api_key": "***REDACTED***" if self.openai_api_key else None,
            "openai_model": self.openai_model,
            "image_provider": self.image_provider,
            "flux_ready": bool(self.flux_api_key),
            "flux_model": self.flux_model,
            "flux_api_key": "***REDACTED***" if self.flux_api_key else None,
            "nano_banana_ready": nano_banana_ready,
            "nano_banana_backend": self.nano_banana_backend,
            "nano_banana_model": self.gemini_model,
            "gemini_api_key": "***REDACTED***" if self.gemini_api_key else None,
            "projects_dir": str(self.projects_dir),
            "host": self.host,
            "port": self.port,
            "max_retries_per_slide": self.max_retries_per_slide,
        }

    def validate_provider_config(self) -> list[str]:
        """Validate if the configured AI provider has required credentials."""
        errors: list[str] = []
        if self.ai_provider == "azure_openai":
            if not self.azure_openai_endpoint:
                errors.append("AZURE_OPENAI_ENDPOINT is required when AI_PROVIDER is azure_openai")
            if not self.azure_openai_api_key:
                errors.append("AZURE_OPENAI_API_KEY is required when AI_PROVIDER is azure_openai")
            if not self.azure_openai_deployment:
                errors.append("AZURE_OPENAI_DEPLOYMENT is required when AI_PROVIDER is azure_openai")
        elif self.ai_provider == "openai":
            if not self.openai_api_key:
                errors.append("OPENAI_API_KEY is required when AI_PROVIDER is openai")
        elif self.ai_provider == "mock":
            pass
        else:
            errors.append(f"Unsupported AI_PROVIDER: {self.ai_provider}. Choose azure_openai, openai, or mock.")
        return errors


_config_instance: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get or initialize singleton AppConfig instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig()
        _config_instance.data_dir.mkdir(parents=True, exist_ok=True)
        _config_instance.projects_dir.mkdir(parents=True, exist_ok=True)
    return _config_instance
