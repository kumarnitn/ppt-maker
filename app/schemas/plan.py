"""Presentation plan schemas."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class SlidePlan(BaseModel):
    """Plan for an individual slide."""
    index: int = Field(..., description="1-based slide index")
    title: str = Field(..., description="Slide title")
    subtitle: Optional[str] = Field(None, description="Slide subtitle or kicker")
    core_message: str = Field(..., description="Single takeaway message of this slide")
    slide_role: str = Field("content", description="cover, toc, chapter, content, ending")
    layout_type: str = Field("split_cards", description="Suggested visual layout pattern")
    bullet_points: list[str] = Field(default_factory=list, description="Key supporting text points")
    visual_suggestion: Optional[str] = Field(None, description="Visual treatment (cards, kpi, comparison, etc.)")
    suggested_icons: list[str] = Field(default_factory=list, description="Suggested icons like tabler-outline/chart")
    image_needed: Optional[bool] = Field(False, description="Whether this slide context requires an AI-generated contextual image")
    image_prompt: Optional[str] = Field(None, description="Detailed prompt for Flux image generation tailored to this slide")
    image_aspect_ratio: Optional[str] = Field("16:9", description="Preferred aspect ratio for the image (e.g. 16:9, 4:3, 1:1)")
    image_filename: Optional[str] = Field(None, description="Target image filename in images/, e.g. slide_02_hero.png")
    notes_outline: Optional[str] = Field(None, description="Key points for speaker notes")

    from pydantic import field_validator

    @field_validator("image_needed", mode="before")
    @classmethod
    def _validate_image_needed(cls, v: Any) -> bool:
        if v is None:
            return False
        return bool(v)

    @field_validator("image_aspect_ratio", mode="before")
    @classmethod
    def _validate_aspect_ratio(cls, v: Any) -> str:
        if not v:
            return "16:9"
        return str(v)

    @property
    def slide_number(self) -> int:
        return self.index


class PresentationPlan(BaseModel):
    """Complete structured presentation outline generated from source document."""
    title: str = Field(..., description="Overall presentation title")
    subtitle: Optional[str] = Field(None, description="Presentation subtitle")
    target_audience: str = Field(..., description="Target audience")
    core_objective: str = Field(..., description="Primary takeaway or call to action")
    recommended_slide_count: int = Field(..., ge=1, le=50)
    slides: list[SlidePlan] = Field(..., min_length=1)
    color_palette_name: Optional[str] = Field("corporate_blue", description="Recommended color scheme")


class PlanApprovalRequest(BaseModel):
    """Request to approve or update presentation plan."""
    approved_plan: Optional[PresentationPlan] = None
    action: str = Field("approve", description="'approve' or 'revise'")
    revision_feedback: Optional[str] = None
