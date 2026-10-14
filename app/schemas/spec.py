"""Design specification and lock schemas."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ColorPalette(BaseModel):
    """Semantic color palette - Executive Corporate / Consulting default."""
    background: str = "#FFFFFF"
    surface: str = "#F8FAFC"
    surface_border: str = "#E2E8F0"
    text_primary: str = "#1E293B"
    text_secondary: str = "#64748B"
    accent_primary: str = "#2563EB"
    accent_secondary: str = "#E86C38"


class TypographyHierarchy(BaseModel):
    """Typography rules."""
    font_family_primary: str = "Arial, Helvetica, sans-serif"
    font_family_heading: str = "Arial, Helvetica, sans-serif"
    title_size_px: int = 40
    subtitle_size_px: int = 20
    body_size_px: int = 16
    caption_size_px: int = 12


class DesignSpecSchema(BaseModel):
    """Structured design spec values corresponding to design_spec.md."""
    project_name: str = "Presentation"
    target_audience: str = "General Audience"
    core_objective: str = "Executive communication"
    view_box: str = "0 0 1280 720"
    width: int = 1280
    height: int = 720
    palette: ColorPalette = Field(default_factory=ColorPalette)
    typography: TypographyHierarchy = Field(default_factory=TypographyHierarchy)
    icon_library: str = "tabler-outline"
    layout_guidelines: list[str] = Field(default_factory=list)


class SpecLockSchema(BaseModel):
    """Immutable constraints locked before SVG generation."""
    view_box: str = "0 0 1280 720"
    primary_font: str = "Arial, Helvetica, sans-serif"
    colors: ColorPalette = Field(default_factory=ColorPalette)
    slide_ids: list[str] = Field(default_factory=list)
    icon_prefix: str = "tabler-outline"
