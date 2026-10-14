"""Job management and execution API routes."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from flask import Blueprint, abort, jsonify, request, send_file

from app.ai.client import get_ai_client
from app.ai.image_provider import get_image_provider
from app.config import get_config
from app.orchestration.state import JobStore
from app.orchestration.workflow import WorkflowEngine
from app.schemas.job import JobCreateRequest
from app.schemas.plan import PresentationPlan
from app.utils.file_utils import sanitize_project_name

logger = logging.getLogger("ppt_master.api.jobs")
jobs_bp = Blueprint("jobs", __name__)


def get_engine(
    image_provider_override: Optional[str] = None,
    flux_api_key_override: Optional[str] = None,
    flux_model_override: Optional[str] = None,
) -> WorkflowEngine:
    config = get_config()
    store = JobStore(config.data_dir / "jobs.db")
    ai_client = get_ai_client(config)
    updates = {}
    if image_provider_override:
        updates["image_provider"] = image_provider_override
    if flux_api_key_override:
        updates["flux_api_key"] = flux_api_key_override
    if flux_model_override:
        updates["flux_model"] = flux_model_override

    if updates:
        overridden_cfg = config.model_copy(update=updates)
        image_provider = get_image_provider(overridden_cfg)
    else:
        image_provider = get_image_provider(config)
    return WorkflowEngine(config, store, ai_client, image_provider)


@jobs_bp.route("/api/jobs", methods=["POST"])
def create_job():
    """Create and start a new presentation generation job."""
    config = get_config()

    # Extract form or JSON parameters early
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    image_provider_req = data.get("image_provider")
    flux_api_key_req = data.get("flux_api_key") or request.headers.get("X-Flux-Api-Key")
    flux_model_req = data.get("flux_model")
    engine = get_engine(
        image_provider_override=image_provider_req,
        flux_api_key_override=flux_api_key_req,
        flux_model_override=flux_model_req,
    )

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    uploaded_file = request.files.get("file")
    source_file_path: Optional[Path] = None
    source_filename: Optional[str] = None

    if uploaded_file and uploaded_file.filename:
        source_filename = Path(uploaded_file.filename).name
        uploads_dir = config.data_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        saved_file = uploads_dir / f"{job_id}_{source_filename}"
        uploaded_file.save(str(saved_file))
        source_file_path = saved_file

        # Validate file
        valid, err = engine.doc_service.validate_file(saved_file)
        if not valid:
            if saved_file.exists():
                saved_file.unlink()
            return jsonify({"error": err}), 400

    project_name = data.get("project_name")
    if not project_name:
        if source_filename:
            project_name = Path(source_filename).stem
        else:
            project_name = "presentation"

    project_slug = sanitize_project_name(project_name)
    auto_approve_str = data.get("auto_approve", "true")
    auto_approve = str(auto_approve_str).lower() in ("true", "1", "yes")

    slide_count_raw = data.get("slide_count")
    slide_count = int(slide_count_raw) if slide_count_raw and str(slide_count_raw).isdigit() else None

    enable_notes_str = data.get("enable_notes", "true")
    enable_notes = str(enable_notes_str).lower() in ("true", "1", "yes")

    enable_animations_str = data.get("enable_animations", "true")
    enable_animations = str(enable_animations_str).lower() in ("true", "1", "yes")

    params = {
        "project_name": project_slug,
        "topic": data.get("topic", ""),
        "purpose": data.get("purpose", "Executive Presentation"),
        "audience": data.get("audience", "Stakeholders"),
        "slide_count": slide_count,
        "aspect_ratio": data.get("aspect_ratio", "16:9"),
        "style_direction": data.get("style_direction", "Executive Consulting"),
        "enable_notes": enable_notes,
        "enable_animations": enable_animations,
        "transition": data.get("transition", "push"),
        "animation_trigger": data.get("animation_trigger", "after-previous"),
        "auto_approve": auto_approve,
        "image_provider": image_provider_req or config.image_provider,
    }

    job = engine.store.create_job(
        job_id=job_id,
        project_name=project_slug,
        source_filename=source_filename,
        auto_approve=auto_approve,
        config_snapshot=config.redacted_dict(),
    )

    # Start execution in background
    engine.start_job_async(job_id, source_file_path, params)

    return jsonify(job.model_dump()), 201


@jobs_bp.route("/api/jobs", methods=["GET"])
def list_jobs():
    """List recent presentation generation jobs."""
    engine = get_engine()
    limit = int(request.args.get("limit", 50))
    jobs = engine.store.list_jobs(limit=limit)
    return jsonify([j.model_dump() for j in jobs])


@jobs_bp.route("/api/jobs/<job_id>", methods=["GET"])
def get_job(job_id: str):
    """Get single job status and logs."""
    engine = get_engine()
    job = engine.store.get_job(job_id)
    if not job:
        abort(404, description="Job not found")
    return jsonify(job.model_dump())


@jobs_bp.route("/api/jobs/<job_id>/plan", methods=["GET"])
def get_job_plan(job_id: str):
    """Retrieve the generated presentation plan for review."""
    engine = get_engine()
    job = engine.store.get_job(job_id)
    if not job:
        abort(404, description="Job not found")

    plan_str = engine.store.get_plan_json(job_id)
    if not plan_str:
        abort(404, description="Presentation plan has not been generated yet.")

    return jsonify(json.loads(plan_str))


@jobs_bp.route("/api/jobs/<job_id>/approve", methods=["POST"])
def approve_job_plan(job_id: str):
    """Approve or revise the presentation plan to proceed with generation."""
    engine = get_engine()
    job = engine.store.get_job(job_id)
    if not job:
        abort(404, description="Job not found")

    data = request.get_json(silent=True) or {}
    revised_plan: Optional[PresentationPlan] = None
    if "approved_plan" in data and data["approved_plan"]:
        try:
            revised_plan = PresentationPlan.model_validate(data["approved_plan"])
        except Exception as exc:
            return jsonify({"error": f"Invalid plan format: {exc}"}), 400

    success = engine.approve_plan(job_id, revised_plan)
    if not success:
        return (
            jsonify({"error": "Job is not in AWAITING_APPROVAL state or plan is missing."}),
            400,
        )

    updated = engine.store.get_job(job_id)
    return jsonify(updated.model_dump() if updated else {"status": "resumed"})


@jobs_bp.route("/api/jobs/<job_id>/resume", methods=["POST"])
def resume_job(job_id: str):
    """Resume an interrupted or failed presentation generation job."""
    engine = get_engine()
    job = engine.store.get_job(job_id)
    if not job:
        abort(404, description="Job not found")

    success = engine.resume_job(job_id)
    if not success:
        return jsonify({"error": "Unable to resume job from checkpoint."}), 400

    updated = engine.store.get_job(job_id)
    return jsonify(updated.model_dump() if updated else {"status": "resumed"})


@jobs_bp.route("/api/jobs/<job_id>/slides", methods=["GET"])
def list_slides(job_id: str):
    """List generated slides for preview."""
    engine = get_engine()
    job = engine.store.get_job(job_id)
    if not job or not job.project_path:
        abort(404, description="Job not found")

    svg_dir = Path(job.project_path) / "svg_output"
    if not svg_dir.is_dir():
        return jsonify([])

    slides = sorted(svg_dir.glob("slide_*.svg"))
    return jsonify(
        [
            {
                "filename": s.name,
                "slide_index": int(s.stem.split("_")[-1]) if s.stem.split("_")[-1].isdigit() else 1,
                "preview_url": f"/api/jobs/{job_id}/slides/{int(s.stem.split('_')[-1]) if s.stem.split('_')[-1].isdigit() else 1}",
            }
            for s in slides
        ]
    )


@jobs_bp.route("/api/jobs/<job_id>/slides/<int:slide_index>", methods=["GET"])
def get_slide_svg(job_id: str, slide_index: int):
    """Get raw SVG markup of a generated slide, embedding local images for web browser preview."""
    engine = get_engine()
    job = engine.store.get_job(job_id)
    if not job or not job.project_path:
        abort(404, description="Job not found")

    slide_file = Path(job.project_path) / "svg_output" / f"slide_{slide_index:02d}.svg"
    if not slide_file.is_file():
        abort(404, description=f"Slide {slide_index} not found")

    content = slide_file.read_text(encoding="utf-8")
    project_dir = Path(job.project_path)
    images_dir = project_dir / "images"

    # Browser sandbox blocks external relative URLs in <img src="slide.svg">.
    # Inline local images as base64 data URIs specifically for the browser preview response.
    if "<image" in content and images_dir.is_dir():
        import base64
        import re

        def _inline_img(match: re.Match) -> str:
            prefix = match.group(1)
            quote = match.group(2)
            rel_path = match.group(3)
            fn = Path(rel_path).name
            img_path = images_dir / fn
            if img_path.is_file():
                raw = img_path.read_bytes()
                mime = "image/png"
                if img_path.suffix.lower() in [".jpg", ".jpeg"]:
                    mime = "image/jpeg"
                elif img_path.suffix.lower() == ".webp":
                    mime = "image/webp"
                b64 = base64.b64encode(raw).decode("ascii")
                return f"{prefix}{quote}data:{mime};base64,{b64}{quote}"
            return match.group(0)

        content = re.sub(
            r'(\b(?:href|xlink:href)\s*=\s*)(["\'])([^"\']+)\2',
            _inline_img,
            content,
        )

    from flask import Response
    return Response(content, mimetype="image/svg+xml")


@jobs_bp.route("/api/jobs/<job_id>/images/<filename>", methods=["GET"])
def get_job_image(job_id: str, filename: str):
    """Serve slide image asset directly."""
    engine = get_engine()
    job = engine.store.get_job(job_id)
    if not job or not job.project_path:
        abort(404, description="Job not found")

    image_file = Path(job.project_path) / "images" / filename
    if not image_file.is_file():
        abort(404, description=f"Image {filename} not found")

    mimetype = "image/png"
    if image_file.suffix.lower() in [".jpg", ".jpeg"]:
        mimetype = "image/jpeg"
    elif image_file.suffix.lower() == ".webp":
        mimetype = "image/webp"

    return send_file(str(image_file), mimetype=mimetype)

