"""Presentation planning and design specification generation service."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Tuple

from app.ai.client import BaseAIClient
from app.config import AppConfig
from app.schemas.plan import PresentationPlan
from app.schemas.spec import DesignSpecSchema
from app.utils.file_utils import atomic_write_text

logger = logging.getLogger("ppt_master.planning_service")


class PlanningService:
    """Orchestrates AI analysis of documents and produces presentation plans and design specs."""

    def __init__(self, config: AppConfig, ai_client: BaseAIClient) -> None:
        self.config = config
        self.ai_client = ai_client

    def create_presentation_plan(
        self,
        document_text: str,
        params: dict[str, Any],
        project_path: Path,
    ) -> Tuple[PresentationPlan, Path]:
        """Analyze source text and save presentation_plan.json."""
        logger.info("Generating presentation plan for %s", params.get("project_name"))
        plan = self.ai_client.generate_plan(document_text, params)

        plan_file = project_path / "presentation_plan.json"
        atomic_write_text(plan_file, plan.model_dump_json(indent=2))
        return plan, plan_file

    def create_design_spec_and_lock(
        self,
        plan: PresentationPlan,
        params: dict[str, Any],
        project_path: Path,
    ) -> Tuple[DesignSpecSchema, Path, Path]:
        """Generate and save design_spec.md and spec_lock.md."""
        logger.info("Generating design specification and lock for %s", plan.title)
        spec = self.ai_client.generate_design_spec(plan, params)

        spec_file = project_path / "design_spec.md"
        lock_file = project_path / "spec_lock.md"

        # Generate markdown conforming to ppt-master schema
        spec_content = self._render_design_spec_md(plan, spec)
        lock_content = self._render_spec_lock_md(plan, spec)

        atomic_write_text(spec_file, spec_content)
        atomic_write_text(lock_file, lock_content)

        return spec, spec_file, lock_file

    def _render_design_spec_md(self, plan: PresentationPlan, spec: DesignSpecSchema) -> str:
        """Render human-readable design_spec.md."""
        lines = [
            "<!-- ppt-master-schema: design-spec/v1 -->",
            f"# {plan.title} - Design Spec",
            "",
            "## I. Project Information",
            "",
            "| Item | Value |",
            "| --- | --- |",
            f"| Project Name | {spec.project_name} |",
            f"| Canvas Format | PPT 16:9 ({spec.width}x{spec.height}) |",
            f"| Page Count | {len(plan.slides)} |",
            "| Primary Language | en-US |",
            f"| Target Audience | {plan.target_audience} |",
            f"| Core Objective | {plan.core_objective} |",
            "",
            "## II. Canvas Specification",
            "",
            "| Property | Value |",
            "| --- | --- |",
            f"| viewBox | {spec.view_box} |",
            f"| Dimensions | {spec.width}x{spec.height} |",
            "",
            "## III. Color System",
            "",
            "| Token | HEX | Description |",
            "| --- | --- | --- |",
            f"| Background | {spec.palette.background} | Slide canvas background |",
            f"| Surface | {spec.palette.surface} | Card and container surface |",
            f"| Border | {spec.palette.surface_border} | Card perimeter border |",
            f"| Primary Text | {spec.palette.text_primary} | Titles and primary copy |",
            f"| Secondary Text | {spec.palette.text_secondary} | Subtitles and captions |",
            f"| Accent Primary | {spec.palette.accent_primary} | Highlights and callouts |",
            f"| Accent Secondary | {spec.palette.accent_secondary} | Supporting accents |",
            "",
            "## IV. Typography",
            "",
            "| Role | Family | Size (px) | Weight |",
            "| --- | --- | --- | --- |",
            f"| Title | {spec.typography.font_family_heading} | {spec.typography.title_size_px} | Bold |",
            f"| Subtitle | {spec.typography.font_family_primary} | {spec.typography.subtitle_size_px} | Regular |",
            f"| Body | {spec.typography.font_family_primary} | {spec.typography.body_size_px} | Regular |",
            f"| Caption | {spec.typography.font_family_primary} | {spec.typography.caption_size_px} | Regular |",
            "",
            "## IX. Slide Roster",
            "",
        ]

        for s in plan.slides:
            lines.extend(
                [
                    f"### Slide {s.index:02d}: {s.title}",
                    f"- Role: `{s.slide_role}`",
                    f"- Message: {s.core_message}",
                    f"- Layout: `{s.layout_type}`",
                    f"- Suggestion: {s.visual_suggestion or 'Default split layout'}",
                    "",
                ]
            )

        return "\n".join(lines)

    def _render_spec_lock_md(self, plan: PresentationPlan, spec: DesignSpecSchema) -> str:
        """Render machine-checked spec_lock.md."""
        lines = [
            "<!-- ppt-master-schema: spec-lock/v1 -->",
            "# Specification Lock",
            "",
            "## Canvas Anchors",
            f"- viewBox: `{spec.view_box}`",
            f"- width: `{spec.width}`",
            f"- height: `{spec.height}`",
            "",
            "## Color Anchors",
            f"- background: `{spec.palette.background}`",
            f"- surface: `{spec.palette.surface}`",
            f"- text_primary: `{spec.palette.text_primary}`",
            f"- accent_primary: `{spec.palette.accent_primary}`",
            "",
            "## Typography Anchors",
            f"- primary_font: `{spec.typography.font_family_primary}`",
            f"- title_size: `{spec.typography.title_size_px}`",
            "",
            "## Page Roster",
        ]
        for s in plan.slides:
            lines.append(f"- slide_{s.index:02d}.svg: `{s.slide_role}` ({s.title})")
        return "\n".join(lines)
