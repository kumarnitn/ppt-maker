"""Service for importing existing PowerPoint presentations and executing 1:1 beautification.

Wraps PPT Master's native tools:
- pptx_to_svg.py (direct OpenXML-to-SVG extraction & roundtrip)
- beautify_identity.py (theme, palette, fonts, canvas extraction)
- beautify_inventory.py (content and slide structure extraction)
- svg_to_pptx.py (roundtrip and quick-generate compilation)
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import AppConfig
from app.utils.subprocess_runner import run_command_safe

logger = logging.getLogger("ppt_master.pptx_import_service")


class PPTXImportAndBeautifyService:
    """Manages PPTX import, roundtrip workspaces, and presentation beautification."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.scripts_dir = self.config.skill_dir / "scripts"
        self.pptx_to_svg_script = self.scripts_dir / "pptx_to_svg.py"
        self.beautify_identity_script = self.scripts_dir / "beautify_identity.py"
        self.beautify_inventory_script = self.scripts_dir / "beautify_inventory.py"
        self.project_manager_script = self.scripts_dir / "project_manager.py"
        self.svg_to_pptx_script = self.scripts_dir / "svg_to_pptx.py"

    def extract_identity(self, pptx_path: Path) -> Optional[Dict[str, Any]]:
        """Extract visual identity, color palette, fonts, and aspect ratio from a PPTX file."""
        if not pptx_path.is_file():
            logger.error("PPTX file not found: %s", pptx_path)
            return None

        cmd = [
            self.config.python_executable,
            str(self.beautify_identity_script),
            str(pptx_path),
        ]
        res = run_command_safe(cmd, cwd=self.config.repo_root)
        if not res.is_success:
            logger.warning("Failed to extract identity from %s: %s", pptx_path, res.stderr)
            return None

        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse identity JSON from %s: %s", pptx_path, exc)
            return None

    def import_pptx_to_workspace(
        self,
        pptx_path: Path,
        target_project_dir: Path,
        roundtrip: bool = True,
    ) -> bool:
        """Convert a PPTX file into an editable SVG workspace using pptx_to_svg.py.

        Creates authoring-svg-flat/, images/, and metadata.
        """
        if not pptx_path.is_file():
            logger.error("Source PPTX not found: %s", pptx_path)
            return False

        target_project_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.config.python_executable,
            str(self.pptx_to_svg_script),
            str(pptx_path),
            "-o",
            str(target_project_dir),
            "--inheritance-mode",
            "both",
        ]
        if roundtrip:
            cmd.append("--roundtrip")

        logger.info("Importing PPTX to workspace: %s", cmd)
        res = run_command_safe(cmd, cwd=self.config.repo_root, timeout=180)
        if not res.is_success:
            logger.error("pptx_to_svg failed: %s", res.stderr or res.stdout)
            return False

        logger.info("Successfully imported PPTX to %s", target_project_dir)
        return True

    def compile_roundtrip(
        self,
        project_dir: Path,
        enable_animations: bool = True,
        transition: str = "push",
    ) -> Tuple[Optional[Path], Optional[str]]:
        """Recompile an imported roundtrip workspace back into PPTX using svg_to_pptx.py --roundtrip."""
        cmd = [
            self.config.python_executable,
            str(self.svg_to_pptx_script),
            str(project_dir),
            "--roundtrip",
        ]
        if enable_animations:
            cmd.extend([
                "-a", "auto",
                "--animation-trigger", "after-previous",
                "--animation-stagger", "0.4",
            ])
            if transition and transition != "none":
                cmd.extend(["-t", transition])
        else:
            cmd.append("--no-animations")

        logger.info("Compiling roundtrip presentation: %s", cmd)
        res = run_command_safe(cmd, cwd=self.config.repo_root, timeout=300)
        if not res.is_success:
            return None, f"Roundtrip compilation failed: {res.stderr or res.stdout}"

        # Look for exported pptx
        exports_dir = project_dir / "exports"
        if exports_dir.is_dir():
            pptx_files = sorted(exports_dir.glob("*.pptx"), key=lambda p: p.stat().st_mtime, reverse=True)
            if pptx_files:
                return pptx_files[0], None

        return None, "No output PPTX generated in exports/"
