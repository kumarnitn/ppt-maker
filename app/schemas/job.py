"""Job status and request/response models."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Execution status of a presentation job."""
    CREATED = "CREATED"
    INGESTING = "INGESTING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PREPARING_ASSETS = "PREPARING_ASSETS"
    GENERATING_SLIDES = "GENERATING_SLIDES"
    VALIDATING_SLIDES = "VALIDATING_SLIDES"
    GENERATING_NOTES = "GENERATING_NOTES"
    FINALIZING_ASSETS = "FINALIZING_ASSETS"
    COMPILING = "COMPILING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobPhase(str, Enum):
    """Major phase in the 6-phase presentation lifecycle."""
    INTAKE = "Phase 0: Intake and source extraction"
    PLANNING = "Phase 1: Strategist and presentation planning"
    DESIGN = "Phase 2: Design specification and asset preparation"
    CONSTRUCTION = "Phase 3: Slide construction and quality gates"
    NOTES = "Phase 4: Speaker notes"
    FINALIZATION = "Phase 5: Finalization and native compilation"
    COMPLETE = "Complete"


class JobStepLog(BaseModel):
    """Log entry for an individual job execution step."""
    timestamp: str
    phase: str
    step_name: str
    status: str
    message: str
    details: Optional[dict[str, Any]] = None


class JobCreateRequest(BaseModel):
    """User request parameters for generating a presentation."""
    project_name: Optional[str] = Field(None, description="Human-readable project name or slug")
    topic: Optional[str] = Field(None, description="Topic description or instructions")
    purpose: Optional[str] = Field("executive_presentation", description="Presentation purpose/context")
    audience: Optional[str] = Field("general_business", description="Target audience")
    slide_count: Optional[int] = Field(None, ge=1, le=50, description="Desired slide count (auto if omitted)")
    aspect_ratio: Optional[str] = Field("16:9", description="Canvas aspect ratio (16:9 or 4:3)")
    style_direction: Optional[str] = Field("executive_consulting", description="Style/theme direction")
    auto_approve: bool = Field(True, description="Whether to proceed automatically without manual plan approval")
    enable_notes: bool = Field(True, description="Generate speaker notes")
    enable_animations: bool = Field(True, description="Apply PowerPoint native animations and staggered builds")
    transition: Optional[str] = Field("push", description="PowerPoint slide transition (push, fade, wipe, reveal, morph, none)")
    animation_trigger: Optional[str] = Field("after-previous", description="Animation start trigger: after-previous, on-click, with-previous")
    image_provider: Optional[str] = Field("auto", description="Image provider: flux, nano_banana, azure_openai, local, or auto")
    flux_api_key: Optional[str] = Field(None, description="Flux 2 Pro / BFL API key")
    flux_model: Optional[str] = Field("flux-2-pro", description="Flux model variant (e.g. flux-2-pro, flux-pro-1.1)")


class JobResponse(BaseModel):
    """Detailed job status and metadata returned by API."""
    job_id: str
    project_name: str
    project_path: Optional[str] = None
    status: JobStatus
    phase: JobPhase
    progress_percent: int = 0
    current_slide: int = 0
    total_slides: int = 0
    source_filename: Optional[str] = None
    created_at: str
    updated_at: str
    error_message: Optional[str] = None
    validation_summary: Optional[dict[str, Any]] = None
    output_pptx_path: Optional[str] = None
    download_url: Optional[str] = None
    logs: list[JobStepLog] = Field(default_factory=list)
    auto_approve: bool = True
