"""Speaker notes generation and split synchronization service."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from app.ai.client import BaseAIClient
from app.config import AppConfig
from app.schemas.plan import PresentationPlan
from app.utils.file_utils import atomic_write_text
from app.utils.subprocess_runner import run_command_safe

logger = logging.getLogger("ppt_master.notes_service")


class NotesService:
    """Generates speaker notes for slides and runs total_md_split.py."""

    def __init__(self, config: AppConfig, ai_client: BaseAIClient) -> None:
        self.config = config
        self.ai_client = ai_client
        self.split_script = self.config.skill_dir / "scripts" / "total_md_split.py"

    def generate_and_split_notes(
        self,
        plan: PresentationPlan,
        project_path: Path,
    ) -> Tuple[bool, Optional[str]]:
        """Generate notes for all slides, write notes/total.md, and run total_md_split.py."""
        notes_dir = project_path / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        total_notes_file = notes_dir / "total.md"

        # Clean up any stale slide notes beyond current plan
        for old_note in notes_dir.glob("slide_*.md"):
            try:
                idx = int(old_note.stem.split("_")[-1])
                if idx > len(plan.slides):
                    old_note.unlink(missing_ok=True)
            except (ValueError, IndexError):
                pass

        sections: list[str] = []
        for slide in plan.slides:
            slide_svg_path = project_path / "svg_output" / f"slide_{slide.index:02d}.svg"
            svg_content = (
                slide_svg_path.read_text(encoding="utf-8")
                if slide_svg_path.is_file()
                else ""
            )

            notes_body = self.ai_client.generate_speaker_notes(plan, slide, svg_content)
            # Use format: # Slide <index>: <title>
            section_text = f"# Slide {slide.index}: {slide.title}\n\n{notes_body.strip()}\n"
            sections.append(section_text)

        full_notes_text = "\n\n".join(sections)
        atomic_write_text(total_notes_file, full_notes_text)

        # Run total_md_split.py to split into individual files
        cmd = [
            self.config.python_executable,
            str(self.split_script),
            str(project_path),
        ]
        logger.info("Splitting speaker notes: %s", cmd)
        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            timeout=self.config.subprocess_timeout,
        )

        if not res.is_success:
            logger.warning(
                "total_md_split returned non-zero (notes still saved in total.md): %s",
                res.stderr,
            )
            # If total_md_split failed, let's write individual slide notes directly as fallback
            for slide in plan.slides:
                slide_notes_file = notes_dir / f"slide_{slide.index:02d}.md"
                if not slide_notes_file.is_file():
                    slide_notes_file.write_text(
                        f"## {slide.title}\n\n{slide.core_message}\n\n"
                        + "\n".join(f"- {pt}" for pt in slide.bullet_points),
                        encoding="utf-8",
                    )

        return True, None
