"""Recovery logic for resuming interrupted or failed presentation jobs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from app.orchestration.checkpoints import CheckpointManager
from app.schemas.job import JobPhase, JobStatus

logger = logging.getLogger("ppt_master.recovery")


class JobRecoveryManager:
    """Calculates safe recovery point from disk state and stored job data."""

    @staticmethod
    def determine_resume_point(
        project_path: Path,
        total_slides: int,
    ) -> Tuple[JobStatus, JobPhase, int]:
        """Examine project directory artifacts and return (status, phase, resume_slide_index).

        resume_slide_index is 1-based (next slide to author).
        """
        # Check export
        if CheckpointManager.verify_export_checkpoint(project_path):
            return JobStatus.COMPLETED, JobPhase.COMPLETE, total_slides

        # Check slides
        completed_slides = CheckpointManager.get_completed_slides(project_path)
        completed_count = len(completed_slides)

        if total_slides > 0 and completed_count >= total_slides:
            # All slides exist, check notes
            if not CheckpointManager.verify_notes_checkpoint(project_path):
                return JobStatus.GENERATING_NOTES, JobPhase.NOTES, total_slides
            # Notes exist, resume at compilation
            return JobStatus.COMPILING, JobPhase.FINALIZATION, total_slides

        if completed_count > 0:
            # Resume generating remaining slides
            next_slide = completed_count + 1
            return JobStatus.GENERATING_SLIDES, JobPhase.CONSTRUCTION, next_slide

        # Check design spec
        if CheckpointManager.verify_design_checkpoint(project_path):
            return JobStatus.GENERATING_SLIDES, JobPhase.CONSTRUCTION, 1

        # Check plan
        if CheckpointManager.verify_plan_checkpoint(project_path):
            return JobStatus.PREPARING_ASSETS, JobPhase.DESIGN, 0

        # Default: start at intake
        return JobStatus.INGESTING, JobPhase.INTAKE, 0
