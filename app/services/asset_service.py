"""Asset preparation and synchronization service (icons, images)."""

from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Any, Optional

from app.ai.image_provider import BaseImageProvider
from app.config import AppConfig
from app.schemas.plan import PresentationPlan
from app.utils.subprocess_runner import run_command_safe

logger = logging.getLogger("ppt_master.asset_service")


class AssetService:
    """Synchronizes vector icons and manages visual assets for the presentation."""

    def __init__(self, config: AppConfig, image_provider: BaseImageProvider) -> None:
        self.config = config
        self.image_provider = image_provider
        self.icon_sync_script = self.config.skill_dir / "scripts" / "icon_sync.py"
        self.analyze_images_script = self.config.skill_dir / "scripts" / "analyze_images.py"

    def prepare_assets(
        self,
        plan: PresentationPlan,
        project_path: Path,
    ) -> bool:
        """Synchronize icons and prepare slide visual assets."""
        # 1. Collect all requested icons
        icon_names: set[str] = set()
        for slide in plan.slides:
            for icon in slide.suggested_icons:
                icon_clean = icon.strip()
                if "/" in icon_clean:
                    icon_names.add(icon_clean)
                else:
                    icon_names.add(f"tabler-outline/{icon_clean}")

        if icon_names:
            self._sync_icons(project_path, list(icon_names))

        # 2. Acquire contextual images for slides requiring visual illustration
        images_dir = project_path / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        manifest_entries: list[dict[str, Any]] = []

        for slide in plan.slides:
            slide_idx = getattr(slide, "index", getattr(slide, "slide_number", 1))
            if getattr(slide, "image_needed", False) and getattr(slide, "image_prompt", None):
                if not getattr(slide, "image_filename", None):
                    clean_title = "".join(c if c.isalnum() else "_" for c in slide.title.lower())
                    clean_title = "_".join(filter(None, clean_title.split("_")))[:25]
                    slide.image_filename = f"slide_{slide_idx:02d}_{clean_title or 'visual'}.png"

                target_img = images_dir / slide.image_filename
                manifest_entries.append({
                    "slide": slide_idx,
                    "filename": slide.image_filename,
                    "prompt": slide.image_prompt,
                    "aspect_ratio": getattr(slide, "image_aspect_ratio", "16:9") or "16:9",
                })

                logger.info(
                    "Acquiring contextual image for Slide %d (%s) with %s...",
                    slide_idx,
                    slide.image_filename,
                    self.image_provider.__class__.__name__,
                )
                try:
                    self.image_provider.acquire_image(
                        prompt=slide.image_prompt,
                        target_path=target_img,
                        aspect_ratio=getattr(slide, "image_aspect_ratio", "16:9") or "16:9",
                    )
                except Exception as exc:
                    logger.warning("Failed to acquire image for slide %d: %s", slide_idx, exc)

        # 3. Write / update image_prompts.json manifest or process existing manifest
        manifest_file = images_dir / "image_prompts.json"
        if manifest_entries:
            try:
                manifest_data = {"images": manifest_entries}
                manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
                logger.info("Wrote image prompts manifest: %s", manifest_file)
            except Exception as exc:
                logger.warning("Could not write image manifest: %s", exc)
        elif manifest_file.is_file() and hasattr(self.image_provider, "process_manifest"):
            logger.info("Executing image manifest with %s...", self.image_provider.__class__.__name__)
            try:
                self.image_provider.process_manifest(manifest_file)
            except Exception as exc:
                logger.warning("Manifest image generation warning: %s", exc)

        # 4. Analyze existing images if images/ directory has content
        if images_dir.is_dir() and any(images_dir.iterdir()):
            self._analyze_images(images_dir)

        return True

    def _sync_icons(self, project_path: Path, icon_list: list[str]) -> bool:
        """Run icon_sync.py to pull requested vector icons into the project."""
        cmd = [
            self.config.python_executable,
            str(self.icon_sync_script),
            str(project_path),
        ] + icon_list

        logger.info("Syncing icons: %s", icon_list)
        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            timeout=self.config.subprocess_timeout,
        )
        if not res.is_success:
            logger.warning("icon_sync reported issues (continuing gracefully): %s", res.stderr)
            return False
        return True

    def _analyze_images(self, images_dir: Path) -> bool:
        """Run analyze_images.py to produce image_analysis.csv."""
        cmd = [
            self.config.python_executable,
            str(self.analyze_images_script),
            str(images_dir),
        ]
        logger.info("Analyzing images in %s", images_dir)
        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            timeout=self.config.subprocess_timeout,
        )
        return res.is_success
