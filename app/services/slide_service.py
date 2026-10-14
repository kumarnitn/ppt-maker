"""Slide SVG generation, quality gate enforcement, and bounded repair service."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional, Tuple

from app.ai.client import BaseAIClient
from app.config import AppConfig
from app.schemas.plan import PresentationPlan, SlidePlan
from app.schemas.spec import DesignSpecSchema
from app.services.validation_service import ValidationResult, ValidationService
from app.utils.file_utils import atomic_write_text

logger = logging.getLogger("ppt_master.slide_service")


class SlideService:
    """Orchestrates slide generation, early/final quality gates, and targeted repair."""

    def __init__(
        self,
        config: AppConfig,
        ai_client: BaseAIClient,
        validation_service: ValidationService,
    ) -> None:
        self.config = config
        self.ai_client = ai_client
        self.validation_service = validation_service

    def generate_single_slide(
        self,
        slide: SlidePlan,
        spec: DesignSpecSchema,
        total_slides: int,
        project_path: Path,
        max_retries: Optional[int] = None,
    ) -> Tuple[bool, Path, list[str]]:
        """Generate one slide SVG and apply targeted repairs until valid or retries exhausted."""
        retries = max_retries if max_retries is not None else self.config.max_retries_per_slide
        svg_dir = project_path / "svg_output"
        svg_dir.mkdir(parents=True, exist_ok=True)
        slide_file = svg_dir / f"slide_{slide.index:02d}.svg"
        image_instruction = "None. Use vector SVG cards, shapes, and icons."
        if slide.image_filename:
            img_file = project_path / "images" / slide.image_filename
            if img_file.is_file():
                if slide.index == 1:
                    image_instruction = (
                        f"Contextual image asset available at '../images/{slide.image_filename}'. "
                        f"Embed it on the right side using: "
                        f"<image href='../images/{slide.image_filename}' x='760' y='180' width='460' height='460' rx='8' preserveAspectRatio='xMidYMid slice'/>\n"
                        f"Keep the main title, proposal badges, and central promise box on the left side (x: 60 to 720)."
                    )
                else:
                    image_instruction = (
                        f"Contextual image asset available at '../images/{slide.image_filename}'. "
                        f"You MUST embed it in the layout using: "
                        f"<image href='../images/{slide.image_filename}' x='60' y='180' width='460' height='480' preserveAspectRatio='xMidYMid slice'/>\n"
                        f"Place your structured title, key points, and metrics on the opposite side (x: 540 to 1220)."
                    )

        logger.info("Generating slide %d/%d: %s", slide.index, total_slides, slide.title)
        raw_svg = self.ai_client.generate_slide_svg(
            slide, spec, total_slides, image_instruction=image_instruction
        )

        attempt = 0
        current_svg = self.validation_service.sanitize_svg_content(raw_svg)
        errors = self.validation_service.preflight_svg_text(current_svg, slide_file.name)

        while errors and attempt < retries:
            attempt += 1
            logger.warning(
                "Slide %d preflight failed (attempt %d/%d). Applying targeted repair: %s",
                slide.index,
                attempt,
                retries,
                errors,
            )
            repaired_svg = self.ai_client.repair_slide_svg(
                current_svg, "\n".join(str(e) for e in errors)
            )
            repaired_svg = self.validation_service.sanitize_svg_content(repaired_svg)
            repair_errors = self.validation_service.preflight_svg_text(
                repaired_svg, slide_file.name
            )
            if not repair_errors or len(repair_errors) < len(errors):
                current_svg = repaired_svg
                errors = repair_errors
            else:
                logger.warning("Repair did not reduce errors on slide %d", slide.index)

        atomic_write_text(slide_file, current_svg)
        success = len(errors) == 0
        return success, slide_file, errors

    def run_slide_pipeline(
        self,
        plan: PresentationPlan,
        spec: DesignSpecSchema,
        project_path: Path,
        on_slide_completed: Optional[Callable[[int, int], None]] = None,
        start_slide_index: int = 1,
    ) -> Tuple[bool, ValidationResult]:
        """Generate all planned slides sequentially with early and final quality gates."""
        total_slides = len(plan.slides)
        svg_dir = project_path / "svg_output"
        svg_dir.mkdir(parents=True, exist_ok=True)

        # Clean up any stale slide SVGs beyond total_slides from prior runs
        if start_slide_index == 1:
            for old_svg in svg_dir.glob("slide_*.svg"):
                try:
                    idx = int(old_svg.stem.split("_")[-1])
                    if idx > total_slides:
                        old_svg.unlink(missing_ok=True)
                except (ValueError, IndexError):
                    pass

        for slide in plan.slides:
            if slide.index < start_slide_index:
                logger.info("Skipping already generated slide %d", slide.index)
                continue

            success, slide_file, errors = self.generate_single_slide(
                slide, spec, total_slides, project_path
            )
            if not success:
                logger.error(
                    "Slide %d failed preflight repair after retries: %s",
                    slide.index,
                    errors,
                )
                return False, ValidationResult(
                    is_valid=False,
                    blocking_issues=errors,
                    warnings=[],
                )

            if on_slide_completed:
                on_slide_completed(slide.index, total_slides)

            # Early gate check after Slide 5 if total > 6
            if slide.index == 5 and total_slides > 6:
                logger.info("Running mandatory early quality gate after Slide 5...")
                early_result = self.validation_service.run_quality_checker(
                    project_path, stage="early", quick_generate=True
                )
                if not early_result.is_valid:
                    logger.warning(
                        "Early quality gate found blocking issues: %s. Attempting targeted repairs...",
                        early_result.blocking_issues,
                    )
                    # Attempt repairing affected early slides only
                    for early_slide in plan.slides[:5]:
                        slide_prefix = f"slide_{early_slide.index:02d}.svg"
                        matching_issues = [
                            iss for iss in early_result.blocking_issues
                            if slide_prefix in str(iss) or "slide_" not in str(iss)
                        ]
                        if matching_issues:
                            self.repair_existing_slide(early_slide, spec, project_path, matching_issues)
                    # Re-verify early gate
                    early_recheck = self.validation_service.run_quality_checker(
                        project_path, stage="early", quick_generate=True
                    )
                    if not early_recheck.is_valid:
                        return False, early_recheck

        # Final quality gate with bounded multi-pass repair
        logger.info("Running final quality gate for all %d slides...", total_slides)
        final_result = self.validation_service.run_quality_checker(
            project_path, stage="final", quick_generate=True
        )

        repair_pass = 0
        max_repair_passes = 3
        while not final_result.is_valid and repair_pass < max_repair_passes:
            repair_pass += 1
            logger.warning(
                "Final gate detected blocking issues (attempt %d/%d): %s. Running repair pass...",
                repair_pass,
                max_repair_passes,
                final_result.blocking_issues,
            )
            for slide in plan.slides:
                slide_prefix = f"slide_{slide.index:02d}.svg"
                matching_issues = [
                    iss for iss in final_result.blocking_issues
                    if slide_prefix in str(iss) or "slide_" not in str(iss)
                ]
                if matching_issues:
                    self.repair_existing_slide(slide, spec, project_path, matching_issues)

            final_result = self.validation_service.run_quality_checker(
                project_path, stage="final", quick_generate=True
            )

        return final_result.is_valid, final_result

    def repair_existing_slide(
        self,
        slide: SlidePlan,
        spec: DesignSpecSchema,
        project_path: Path,
        issues: list[Any],
    ) -> bool:
        """Apply targeted repair to an existing slide on disk."""
        slide_file = project_path / "svg_output" / f"slide_{slide.index:02d}.svg"
        if not slide_file.is_file():
            return False

        orig_svg = slide_file.read_text(encoding="utf-8")
        clean_issue_lines = [
            it if isinstance(it, str) else (
                f"[{it.get('file', '')}] {it.get('message', str(it))}"
                if isinstance(it, dict)
                else str(it)
            )
            for it in issues
        ]

        # Apply deterministic normalization first
        normalized_orig = self.validation_service.sanitize_svg_content(orig_svg)
        repaired_svg = self.ai_client.repair_slide_svg(normalized_orig, "\n".join(clean_issue_lines))
        repaired_svg = self.validation_service.sanitize_svg_content(repaired_svg)
        preflight = self.validation_service.preflight_svg_text(repaired_svg, slide_file.name)
        if not preflight:
            atomic_write_text(slide_file, repaired_svg)
            logger.info("Successfully repaired %s with AI model", slide_file.name)
            return True
        else:
            # Fallback to normalized original if AI output introduced preflight errors
            atomic_write_text(slide_file, normalized_orig)
            logger.info("Repaired %s via deterministic normalization fallback", slide_file.name)
            return True
