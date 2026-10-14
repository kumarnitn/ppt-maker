"""Checkpoint management for resilient resume and recovery."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ppt_master.checkpoints")


class CheckpointManager:
    """Manages disk-backed checkpoint verification and state synchronization."""

    @staticmethod
    def verify_intake_checkpoint(project_path: Path) -> bool:
        """Check if source extraction landed valid markdown."""
        sources_dir = project_path / "sources"
        if not sources_dir.is_dir():
            return False
        md_files = list(sources_dir.glob("*.md"))
        return len(md_files) > 0

    @staticmethod
    def verify_plan_checkpoint(project_path: Path) -> bool:
        """Check if presentation plan was saved."""
        plan_file = project_path / "presentation_plan.json"
        if not plan_file.is_file():
            return False
        try:
            data = json.loads(plan_file.read_text(encoding="utf-8"))
            return "slides" in data and len(data["slides"]) > 0
        except Exception:
            return False

    @staticmethod
    def verify_design_checkpoint(project_path: Path) -> bool:
        """Check if design spec and spec lock files exist."""
        spec_file = project_path / "design_spec.md"
        lock_file = project_path / "spec_lock.md"
        return spec_file.is_file() and lock_file.is_file()

    @staticmethod
    def get_completed_slides(project_path: Path) -> list[Path]:
        """Return list of generated slide SVGs in sorted order."""
        svg_dir = project_path / "svg_output"
        if not svg_dir.is_dir():
            return []
        return sorted(svg_dir.glob("slide_*.svg"))

    @staticmethod
    def verify_slides_checkpoint(project_path: Path, expected_count: int) -> bool:
        """Check if all planned slide SVGs exist and are non-empty."""
        slides = CheckpointManager.get_completed_slides(project_path)
        if len(slides) < expected_count:
            return False
        for s in slides:
            if s.stat().st_size < 50:
                return False
        return True

    @staticmethod
    def verify_notes_checkpoint(project_path: Path) -> bool:
        """Check if notes were generated."""
        total_notes = project_path / "notes" / "total.md"
        return total_notes.is_file() and total_notes.stat().st_size > 0

    @staticmethod
    def verify_export_checkpoint(project_path: Path) -> Optional[Path]:
        """Return path to valid exported PPTX if present, None otherwise."""
        exports_dir = project_path / "exports"
        if not exports_dir.is_dir():
            return None
        pptx_files = sorted(exports_dir.glob("*.pptx"), key=lambda p: p.stat().st_mtime, reverse=True)
        for pptx in pptx_files:
            if pptx.is_file() and pptx.stat().st_size > 1024:
                return pptx
        return None
