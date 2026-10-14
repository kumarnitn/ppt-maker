"""Project initialization and lifecycle management service."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from app.config import AppConfig
from app.utils.file_utils import sanitize_project_name
from app.utils.subprocess_runner import run_command_safe

logger = logging.getLogger("ppt_master.project_service")


class ProjectService:
    """Manages project directory creation and source import using project_manager.py."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.pm_script = self.config.skill_dir / "scripts" / "project_manager.py"

    def initialize_project(
        self,
        project_name: Optional[str] = None,
        quick_generate: bool = True,
    ) -> Tuple[Optional[Path], Optional[str]]:
        """Initialize project directory with project_manager.py init.

        Returns (project_path, error_message).
        """
        slug = sanitize_project_name(project_name)
        import datetime
        import uuid

        today_str = datetime.date.today().strftime("%Y%m%d")
        candidate = self.config.projects_dir / f"{slug}_{today_str}"
        if candidate.is_dir():
            slug = f"{slug}_{uuid.uuid4().hex[:4]}"

        cmd = [
            self.config.python_executable,
            str(self.pm_script),
            "init",
            slug,
        ]
        if quick_generate:
            cmd.append("--quick-generate")

        logger.info("Initializing project: %s", cmd)
        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            timeout=self.config.subprocess_timeout,
        )

        if not res.is_success:
            # Check if it was directory already exists error
            combined = (res.stderr or "") + (res.stdout or "")
            if "Project directory already exists:" in combined:
                for line in combined.splitlines():
                    if "Project directory already exists:" in line:
                        existing_path = Path(line.split("Project directory already exists:", 1)[1].strip())
                        if existing_path.is_dir():
                            return existing_path, None
            logger.error("Project init failed: %s\n%s", res.stdout, res.stderr)
            return None, f"Project initialization failed: {res.stderr or res.stdout}"

        # Parse project path from stdout: "Project created: <path>"
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("Project created:"):
                created_path = Path(line.split("Project created:", 1)[1].strip())
                if created_path.is_dir():
                    return created_path, None

        # Fallback: search projects_dir for matching stem
        for child in self.config.projects_dir.iterdir():
            if child.is_dir() and child.name.startswith(slug):
                return child, None

        return None, "Project created line not found in init output."

    def import_sources(
        self,
        project_path: Path,
        source_file: Path,
        converted_md: Optional[Path] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Import source files and converted markdown into project sources/ directory."""
        if not project_path.is_dir():
            return False, f"Project directory does not exist: {project_path}"

        args = [
            self.config.python_executable,
            str(self.pm_script),
            "import-sources",
            str(project_path),
            str(source_file),
        ]
        if converted_md and converted_md.is_file() and converted_md != source_file:
            args.append(str(converted_md))

        logger.info("Importing sources: %s", args)
        res = run_command_safe(
            args,
            cwd=self.config.repo_root,
            timeout=self.config.subprocess_timeout,
        )

        if not res.is_success:
            logger.error("Source import failed: %s\n%s", res.stdout, res.stderr)
            return False, f"Source import failed: {res.stderr or res.stdout}"

        return True, None
