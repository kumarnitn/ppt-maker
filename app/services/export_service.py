"""PowerPoint compilation and packaging service."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from app.config import AppConfig
from app.utils.subprocess_runner import run_command_safe

logger = logging.getLogger("ppt_master.export_service")


class ExportService:
    """Orchestrates asset finalization and native PPTX compilation."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.finalize_script = self.config.skill_dir / "scripts" / "finalize_svg.py"
        self.svg_to_pptx_script = self.config.skill_dir / "scripts" / "svg_to_pptx.py"

    def finalize_assets(self, project_path: Path) -> bool:
        """Run finalize_svg.py to produce self-contained visual preview in svg_final/."""
        cmd = [
            self.config.python_executable,
            str(self.finalize_script),
            str(project_path),
        ]
        logger.info("Finalizing SVG assets: %s", cmd)
        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            timeout=self.config.subprocess_timeout,
        )
        if not res.is_success:
            logger.warning(
                "finalize_svg reported warnings (preview may still be usable): %s",
                res.stderr or res.stdout,
            )
        return True

    def compile_pptx(
        self,
        project_path: Path,
        enable_notes: bool = True,
        enable_animations: bool = True,
        transition: str = "push",
        animation_trigger: str = "after-previous",
    ) -> Tuple[Optional[Path], Optional[str]]:
        """Compile slides into native PowerPoint OpenXML presentation with dynamic animations and transitions.

        Returns (output_pptx_path, error_message).
        """
        cmd = [
            self.config.python_executable,
            str(self.svg_to_pptx_script),
            str(project_path),
            "--quick-generate",
        ]
        if enable_notes:
            cmd.append("--with-notes")
        else:
            cmd.append("--no-notes")

        if enable_animations:
            cmd.extend([
                "-a", "auto",
                "--animation-trigger", animation_trigger or "after-previous",
                "--animation-stagger", "0.4",
            ])
        else:
            cmd.append("--no-animations")

        if transition and transition != "none":
            cmd.extend(["-t", transition])

        logger.info("Compiling PPTX presentation: %s", cmd)
        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            timeout=self.config.subprocess_timeout,
        )

        if not res.is_success:
            logger.error("svg_to_pptx compilation failed: %s\n%s", res.stdout, res.stderr)
            return None, f"PowerPoint compilation failed: {res.stderr or res.stdout}"

        # Locate compiled PPTX in exports/
        exports_dir = project_path / "exports"
        if not exports_dir.is_dir():
            return None, "Exports directory was not created."

        pptx_candidates = sorted(
            exports_dir.glob("*.pptx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not pptx_candidates:
            return None, "No .pptx file found in exports directory."

        latest_pptx = pptx_candidates[0]
        if latest_pptx.stat().st_size < 1024:
            return None, f"Generated .pptx is empty or corrupt ({latest_pptx.stat().st_size} bytes)."

        # Validate PPTX package integrity with python-pptx
        try:
            from pptx import Presentation

            prs = Presentation(str(latest_pptx))
            slide_count = len(prs.slides)
            logger.info("Validated OpenXML PPTX with %d slide(s): %s", slide_count, latest_pptx)
        except Exception as exc:
            logger.warning("python-pptx package validation warning: %s", exc)

        return latest_pptx, None
