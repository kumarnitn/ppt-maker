"""AI client abstraction supporting Azure OpenAI, standard OpenAI, and Mocking."""

from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.ai.prompts import (
    DESIGN_SPEC_SYSTEM_PROMPT,
    DESIGN_SPEC_USER_PROMPT,
    NOTES_SYSTEM_PROMPT,
    NOTES_USER_PROMPT,
    PLANNING_SYSTEM_PROMPT,
    PLANNING_USER_PROMPT,
    SLIDE_REPAIR_SYSTEM_PROMPT,
    SLIDE_REPAIR_USER_PROMPT,
    SLIDE_SVG_SYSTEM_PROMPT,
    SLIDE_SVG_USER_PROMPT,
)
from app.ai.structured_output import clean_markdown_fences, parse_structured_output
from app.config import AppConfig
from app.schemas.plan import PresentationPlan, SlidePlan
from app.schemas.spec import DesignSpecSchema

logger = logging.getLogger("ppt_master.ai_client")


class AIError(Exception):
    """Base exception for AI client failures."""
    pass


class AIAuthenticationError(AIError):
    """Authentication or credential failure."""
    pass


class AIRateLimitError(AIError):
    """API rate limit exceeded."""
    pass


class AITimeoutError(AIError):
    """API request timed out."""
    pass


class BaseAIClient(ABC):
    """Abstract interface for presentation AI operations."""

    @abstractmethod
    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.5,
        max_tokens: int = 4000,
    ) -> str:
        """Generate completion text."""
        pass

    def generate_plan(self, document_text: str, params: dict[str, Any]) -> PresentationPlan:
        """Generate structured presentation plan."""
        formatted_prompt = PLANNING_USER_PROMPT.format(
            document_text=document_text[:25000],  # Bound input length
            project_name=params.get("project_name", "Presentation"),
            purpose=params.get("purpose", "Executive Presentation"),
            audience=params.get("audience", "Key Stakeholders"),
            slide_count=params.get("slide_count") or "Dynamic (5-8 slides)",
            aspect_ratio=params.get("aspect_ratio", "16:9"),
            style_direction=params.get("style_direction", "Modern Clean"),
        )
        response_text = self.generate_text(
            system_prompt=PLANNING_SYSTEM_PROMPT,
            user_prompt=formatted_prompt,
            temperature=0.3,
        )
        return parse_structured_output(response_text, PresentationPlan)

    def generate_design_spec(
        self, plan: PresentationPlan, params: dict[str, Any]
    ) -> DesignSpecSchema:
        """Generate design specification tokens."""
        formatted_prompt = DESIGN_SPEC_USER_PROMPT.format(
            title=plan.title,
            audience=plan.target_audience,
            objective=plan.core_objective,
            aspect_ratio=params.get("aspect_ratio", "16:9"),
            style_direction=params.get("style_direction", "Modern Clean"),
            project_name=params.get("project_name", "Presentation"),
        )
        response_text = self.generate_text(
            system_prompt=DESIGN_SPEC_SYSTEM_PROMPT,
            user_prompt=formatted_prompt,
            temperature=0.2,
        )
        return parse_structured_output(response_text, DesignSpecSchema)

    def generate_slide_svg(
        self,
        slide: SlidePlan,
        spec: DesignSpecSchema,
        total_slides: int,
        image_instruction: Optional[str] = None,
    ) -> str:
        """Generate DrawingML-compatible SVG for a slide."""
        bullet_text = "\n".join(f"- {pt}" for pt in slide.bullet_points)
        img_inst = image_instruction or "None. Use vector SVG cards, shapes, and icons."
        formatted_prompt = SLIDE_SVG_USER_PROMPT.format(
            slide_index=slide.index,
            total_slides=total_slides,
            title=slide.title,
            subtitle=slide.subtitle or "",
            slide_role=slide.slide_role,
            core_message=slide.core_message,
            layout_type=slide.layout_type,
            bullet_points=bullet_text,
            visual_suggestion=slide.visual_suggestion or "Split card layout",
            image_instruction=img_inst,
            view_box=spec.view_box,
            bg_color=spec.palette.background,
            surface_color=spec.palette.surface,
            border_color=spec.palette.surface_border,
            text_primary=spec.palette.text_primary,
            text_secondary=spec.palette.text_secondary,
            accent_primary=spec.palette.accent_primary,
            accent_secondary=spec.palette.accent_secondary,
            primary_font=spec.typography.font_family_primary,
        )
        raw_svg = self.generate_text(
            system_prompt=SLIDE_SVG_SYSTEM_PROMPT,
            user_prompt=formatted_prompt,
            temperature=0.3,
            max_tokens=4000,
        )
        return clean_markdown_fences(raw_svg)

    def repair_slide_svg(self, original_svg: str, error_report: str) -> str:
        """Repair invalid SVG based on quality check error report."""
        formatted_prompt = SLIDE_REPAIR_USER_PROMPT.format(
            errors=error_report,
            original_svg=original_svg,
        )
        repaired = self.generate_text(
            system_prompt=SLIDE_REPAIR_SYSTEM_PROMPT,
            user_prompt=formatted_prompt,
            temperature=0.2,
            max_tokens=4000,
        )
        return clean_markdown_fences(repaired)

    def generate_speaker_notes(
        self,
        plan: PresentationPlan,
        slide: SlidePlan,
        slide_svg: str,
    ) -> str:
        """Generate speaker notes for a slide."""
        bullet_text = "\n".join(f"- {pt}" for pt in slide.bullet_points)
        formatted_prompt = NOTES_USER_PROMPT.format(
            deck_title=plan.title,
            slide_index=slide.index,
            title=slide.title,
            core_message=slide.core_message,
            bullet_points=bullet_text,
            slide_summary=f"Slide role: {slide.slide_role}. Layout: {slide.layout_type}",
        )
        return self.generate_text(
            system_prompt=NOTES_SYSTEM_PROMPT,
            user_prompt=formatted_prompt,
            temperature=0.4,
        )


class AzureOpenAIClient(BaseAIClient):
    """Production AI client using Azure OpenAI API with retry logic."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        api_version: str,
        deployment: str,
        max_retries: int = 3,
        timeout: int = 90,
    ) -> None:
        try:
            from openai import AzureOpenAI
        except ImportError as exc:
            raise AIError("openai package is required for AzureOpenAIClient.") from exc

        self.endpoint = endpoint
        self.deployment = deployment
        self.max_retries = max_retries
        self.timeout = timeout
        self.client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
            timeout=float(timeout),
        )

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.5,
        max_tokens: int = 4000,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        attempt = 0
        backoff = 2.0
        while attempt < self.max_retries:
            attempt += 1
            try:
                logger.debug("Sending request to Azure OpenAI (attempt %d/%d)", attempt, self.max_retries)
                response = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                choice = response.choices[0]
                content = choice.message.content or ""
                return content
            except Exception as exc:
                error_str = str(exc)
                if "401" in error_str or "AccessDenied" in error_str:
                    raise AIAuthenticationError(f"Azure OpenAI Authentication Failed: {exc}") from exc
                if "429" in error_str or "RateLimit" in error_str:
                    logger.warning("Azure OpenAI rate limited on attempt %d: %s", attempt, exc)
                    if attempt >= self.max_retries:
                        raise AIRateLimitError(f"Azure OpenAI rate limit exceeded: {exc}") from exc
                    jitter = random.uniform(0.5, 1.5)
                    time.sleep(backoff + jitter)
                    backoff *= 2.0
                    continue
                if "timeout" in error_str.lower():
                    logger.warning("Azure OpenAI timeout on attempt %d: %s", attempt, exc)
                    if attempt >= self.max_retries:
                        raise AITimeoutError(f"Azure OpenAI timeout: {exc}") from exc
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue

                if attempt >= self.max_retries:
                    raise AIError(f"Azure OpenAI failed after {attempt} attempts: {exc}") from exc
                time.sleep(backoff)
                backoff *= 1.5

        raise AIError(f"Failed to generate text after {self.max_retries} retries.")


class OpenAIClient(BaseAIClient):
    """Production AI client using standard OpenAI API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
        max_retries: int = 3,
        timeout: int = 90,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AIError("openai package is required for OpenAIClient.") from exc

        self.model = model
        self.max_retries = max_retries
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=float(timeout),
        )

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.5,
        max_tokens: int = 4000,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        attempt = 0
        backoff = 2.0
        while attempt < self.max_retries:
            attempt += 1
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                if "401" in str(exc):
                    raise AIAuthenticationError(f"OpenAI Authentication Failed: {exc}") from exc
                if attempt >= self.max_retries:
                    raise AIError(f"OpenAI failed after {attempt} attempts: {exc}") from exc
                time.sleep(backoff)
                backoff *= 1.5
        raise AIError("OpenAI call failed.")


class MockAIClient(BaseAIClient):
    """Deterministic, offline mock client for automated testing and offline development."""

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.5,
        max_tokens: int = 4000,
    ) -> str:
        sys_lower = system_prompt.lower()
        usr_lower = user_prompt.lower()

        # 1. Slide Repair
        if "repair" in sys_lower:
            return """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#0F172A"/>
  <g id="header">
    <text id="title" x="80" y="90" font-family="Arial, sans-serif" font-size="36" font-weight="bold" fill="#FFFFFF">Repaired Slide</text>
  </g>
  <g id="card-1">
    <rect x="80" y="180" width="1120" height="420" rx="12" fill="#1E293B" stroke="#334155" stroke-width="2"/>
    <text x="120" y="240" font-family="Arial, sans-serif" font-size="20" fill="#FFFFFF">Corrected and validated XML structure.</text>
  </g>
</svg>"""

        # 2. Slide SVG Generation
        if "drawingml-compatible svg" in sys_lower or "render the complete <svg>" in usr_lower:
            img_m = re.search(r"available at ['\"]([^'\"]+)['\"]", usr_lower)
            if img_m:
                img_path = img_m.group(1)
                return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#0F172A"/>
  <g id="header">
    <text id="title" x="80" y="90" font-family="Arial, sans-serif" font-size="36" font-weight="bold" fill="#FFFFFF">Executive Overview</text>
    <text id="subtitle" x="80" y="130" font-family="Arial, sans-serif" font-size="18" fill="#94A3B8">Transforming PPT Master into a Standalone Application</text>
  </g>
  <g id="card-1">
    <rect x="80" y="180" width="540" height="420" rx="12" fill="#1E293B" stroke="#334155" stroke-width="2"/>
    <text x="110" y="230" font-family="Arial, sans-serif" font-size="22" font-weight="bold" fill="#38BDF8">Architecture</text>
    <text x="110" y="270" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Decoupled REST API</text>
    <text x="110" y="305" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Web and CLI interfaces</text>
    <text x="110" y="340" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Persistent state machine</text>
  </g>
  <g id="card-2">
    <image href="{img_path}" x="660" y="180" width="540" height="420" preserveAspectRatio="xMidYMid slice"/>
  </g>
  <g id="footer">
    <text x="80" y="660" font-family="Arial, sans-serif" font-size="12" fill="#64748B">PPT Master Standalone Application</text>
    <text x="1200" y="660" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#64748B">1</text>
  </g>
</svg>"""

            return """<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="#0F172A"/>
  <g id="header">
    <text id="title" x="80" y="90" font-family="Arial, sans-serif" font-size="36" font-weight="bold" fill="#FFFFFF">Executive Overview</text>
    <text id="subtitle" x="80" y="130" font-family="Arial, sans-serif" font-size="18" fill="#94A3B8">Transforming PPT Master into a Standalone Application</text>
  </g>
  <g id="card-1">
    <rect x="80" y="180" width="360" height="420" rx="12" fill="#1E293B" stroke="#334155" stroke-width="2"/>
    <text x="110" y="230" font-family="Arial, sans-serif" font-size="22" font-weight="bold" fill="#38BDF8">Architecture</text>
    <text x="110" y="270" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Decoupled REST API</text>
    <text x="110" y="305" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Web and CLI interfaces</text>
    <text x="110" y="340" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Persistent state machine</text>
  </g>
  <g id="card-2">
    <rect x="470" y="180" width="360" height="420" rx="12" fill="#1E293B" stroke="#334155" stroke-width="2"/>
    <text x="500" y="230" font-family="Arial, sans-serif" font-size="22" font-weight="bold" fill="#818CF8">Quality Gates</text>
    <text x="500" y="270" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Strict XML validation</text>
    <text x="500" y="305" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Automated slide repair</text>
    <text x="500" y="340" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Bounded retry limits</text>
  </g>
  <g id="card-3">
    <rect x="860" y="180" width="340" height="420" rx="12" fill="#1E293B" stroke="#334155" stroke-width="2"/>
    <text x="890" y="230" font-family="Arial, sans-serif" font-size="22" font-weight="bold" fill="#38BDF8">Native Export</text>
    <text x="890" y="270" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• DrawingML shapes</text>
    <text x="890" y="305" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Editable PowerPoint</text>
    <text x="890" y="340" font-family="Arial, sans-serif" font-size="16" fill="#E2E8F0">• Synchronized notes</text>
  </g>
  <g id="footer">
    <text x="80" y="660" font-family="Arial, sans-serif" font-size="12" fill="#64748B">PPT Master Standalone Application</text>
    <text x="1200" y="660" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#64748B">1</text>
  </g>
</svg>"""

        # 3. Design Spec
        if "design spec" in sys_lower or "design specification" in sys_lower or "create the design specification" in usr_lower:
            return """{
  "project_name": "Presentation",
  "target_audience": "Technical Leadership",
  "core_objective": "Deliver native presentation decks",
  "view_box": "0 0 1280 720",
  "width": 1280,
  "height": 720,
  "palette": {
    "background": "#0F172A",
    "surface": "#1E293B",
    "surface_border": "#334155",
    "text_primary": "#FFFFFF",
    "text_secondary": "#94A3B8",
    "accent_primary": "#38BDF8",
    "accent_secondary": "#818CF8"
  },
  "typography": {
    "font_family_primary": "Arial, sans-serif",
    "font_family_heading": "Arial, sans-serif",
    "title_size_px": 36,
    "subtitle_size_px": 18,
    "body_size_px": 16,
    "caption_size_px": 12
  },
  "icon_library": "tabler-outline",
  "layout_guidelines": [
    "Generous padding and whitespace",
    "Consistent card styling",
    "Strong typographic hierarchy"
  ]
}"""

        # 4. Speaker Notes
        if "speechwriter" in sys_lower or "speaker notes" in sys_lower:
            return """Welcome everyone. Today we walk through the strategic overview of this project.
Key takeaway: This initiative creates high-value impact across the organization."""

        # 5. Planning
        if "strategist" in sys_lower or "plan" in sys_lower:
            return """{
  "title": "Autonomous AI Presentation Architecture",
  "subtitle": "Transforming PPT Master into a Standalone Application",
  "target_audience": "Technical Leadership & Product Teams",
  "core_objective": "Deliver native, editable PowerPoint decks programmatically",
  "recommended_slide_count": 4,
  "color_palette_name": "slate_blue",
  "slides": [
    {
      "index": 1,
      "title": "Executive Summary",
      "subtitle": "Overview of Standalone Transformation",
      "core_message": "PPT Master operates independently without runtime AI agent reliance.",
      "slide_role": "cover",
      "layout_type": "hero_cover",
      "bullet_points": ["Native DrawingML compilation", "Full lifecycle orchestration", "Azure OpenAI integration"],
      "visual_suggestion": "Large hero typography with dark theme and blue gradient accent",
      "suggested_icons": ["tabler-outline/presentation"],
      "notes_outline": "Welcome everyone. Today we present the transformation of PPT Master into a standalone app."
    },
    {
      "index": 2,
      "title": "Core Architecture",
      "subtitle": "Decoupled Service-Oriented Design",
      "core_message": "Modular subsystems manage documents, planning, SVG, and compilation.",
      "slide_role": "content",
      "layout_type": "split_cards",
      "bullet_points": ["FastAPI/Flask API and Web Interface", "Persistent SQLite Workflow Engine", "Strict Quality Gate Enforcement"],
      "visual_suggestion": "Three column card layout comparing the major subsystems",
      "suggested_icons": ["tabler-outline/stack-2", "tabler-outline/database", "tabler-outline/shield-check"],
      "notes_outline": "The architecture separates concerns into document intake, design specification, and slide generation."
    },
    {
      "index": 3,
      "title": "Quality Gates & Repair",
      "subtitle": "Fail-Closed Quality Assurance",
      "core_message": "Every slide passes SVG syntax and DrawingML constraints before compilation.",
      "slide_role": "content",
      "layout_type": "metric_kpis",
      "bullet_points": ["Early gate after Slide 5", "Final gate across all slides", "Targeted bounded repair on errors"],
      "visual_suggestion": "3 KPI metric tiles showing 100% validation, zero forbidden tags, native objects",
      "suggested_icons": ["tabler-outline/check", "tabler-outline/tool"],
      "notes_outline": "Our quality control system uses the existing svg_quality_checker script to guarantee validity."
    },
    {
      "index": 4,
      "title": "Next Steps & Roadmap",
      "subtitle": "Continuous Delivery and Asset Expansion",
      "core_message": "Ready for high-volume enterprise document-to-presentation workflows.",
      "slide_role": "ending",
      "layout_type": "split_cards",
      "bullet_points": ["API Endpoint automation", "Enterprise document ingestion", "Export to PowerPoint OpenXML"],
      "visual_suggestion": "Conclusion card with summary metrics and call to action",
      "suggested_icons": ["tabler-outline/rocket"],
      "notes_outline": "In conclusion, the standalone system is ready for production workloads."
    }
  ]
}"""
        return "Standard mock response."

    def generate_plan(self, document_text: str, params: dict[str, Any]) -> PresentationPlan:
        """Dynamically generate presentation plan respecting requested slide counts and topic."""
        requested_count = params.get("slide_count")
        if requested_count is not None:
            try:
                count = max(1, int(requested_count))
            except (ValueError, TypeError):
                count = 4
        else:
            count = 4

        project_title = params.get("project_name", "Presentation").replace("_", " ").title()
        slides: list[SlidePlan] = []
        for i in range(1, count + 1):
            if i == 1:
                role = "cover"
                layout = "hero_cover"
                title = f"{project_title}"
                icons = ["tabler-outline/presentation"]
                visual = "Hero banner card with typography and branding accents"
            elif i == count:
                role = "ending"
                layout = "split_cards"
                title = "Conclusion & Next Steps"
                icons = ["tabler-outline/rocket"]
                visual = "Summary recommendations and roadmap card"
            elif i == 2:
                role = "content"
                layout = "split_cards"
                title = "Problem Framing & Objectives"
                icons = ["tabler-outline/shield-check", "tabler-outline/check"]
                visual = "Comparison cards for objectives and goals"
            elif i == 3:
                role = "content"
                layout = "split_cards"
                title = "System Architecture & Modules"
                icons = ["tabler-outline/stack-2", "tabler-outline/database"]
                visual = "Multi-tier architectural card flow"
            else:
                role = "content"
                layout = "split_cards" if i % 2 == 0 else "metric_kpis"
                title = f"Technical Domain Section {i}"
                icons = ["tabler-outline/chart-dots", "tabler-outline/cpu"]
                visual = "Data points and technical metrics card"

            slides.append(
                SlidePlan(
                    index=i,
                    title=title,
                    subtitle=f"Section {i} Analysis",
                    core_message=f"Key insights and verified outcomes for section {i}.",
                    slide_role=role,
                    layout_type=layout,
                    bullet_points=[
                        f"Objective {i}.1: Verified system execution",
                        f"Objective {i}.2: Robust compliance and monitoring",
                        f"Objective {i}.3: Scalable operational performance",
                    ],
                    visual_suggestion=visual,
                    suggested_icons=icons,
                    notes_outline=f"Speaker discussion for slide {i}.",
                )
            )

        return PresentationPlan(
            title=project_title,
            subtitle="Executive Overview and Strategic Framework",
            target_audience=params.get("audience", "Technical Leadership & Stakeholders"),
            core_objective=params.get("purpose", "Executive Presentation"),
            recommended_slide_count=count,
            color_palette_name="slate_blue",
            slides=slides,
        )


def get_ai_client(config: AppConfig) -> BaseAIClient:
    """Factory to create the configured AI client."""
    provider = config.ai_provider
    if provider == "azure_openai":
        validation_errors = config.validate_provider_config()
        if validation_errors:
            logger.warning(
                "Azure OpenAI configuration incomplete: %s. Falling back to MockAIClient.",
                validation_errors,
            )
            return MockAIClient()
        assert config.azure_openai_endpoint is not None
        assert config.azure_openai_api_key is not None
        assert config.azure_openai_deployment is not None
        return AzureOpenAIClient(
            endpoint=config.azure_openai_endpoint,
            api_key=config.azure_openai_api_key,
            api_version=config.azure_openai_api_version,
            deployment=config.azure_openai_deployment,
        )
    elif provider == "openai":
        if not config.openai_api_key:
            logger.warning("OPENAI_API_KEY missing. Falling back to MockAIClient.")
            return MockAIClient()
        return OpenAIClient(
            api_key=config.openai_api_key,
            model=config.openai_model,
            base_url=config.openai_base_url,
        )
    elif provider == "mock":
        return MockAIClient()
    else:
        logger.warning("Unrecognized provider '%s'. Using MockAIClient.", provider)
        return MockAIClient()
