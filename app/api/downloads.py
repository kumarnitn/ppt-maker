"""Download routes for exported PowerPoint files and reports."""

from __future__ import annotations

from pathlib import Path
from flask import Blueprint, abort, jsonify, send_file

from app.config import get_config
from app.orchestration.state import JobStore

downloads_bp = Blueprint("downloads", __name__)


def get_job_store() -> JobStore:
    config = get_config()
    return JobStore(config.data_dir / "jobs.db")


@downloads_bp.route("/api/downloads/<job_id>/pptx", methods=["GET"])
def download_pptx(job_id: str):
    """Download compiled PowerPoint file for a completed job."""
    store = get_job_store()
    job = store.get_job(job_id)
    if not job:
        abort(404, description="Job not found")

    if not job.output_pptx_path:
        abort(404, description="No presentation export generated for this job")

    pptx_path = Path(job.output_pptx_path)
    if not pptx_path.is_file():
        abort(404, description="Export file does not exist on disk")

    return send_file(
        str(pptx_path),
        as_attachment=True,
        download_name=pptx_path.name,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@downloads_bp.route("/api/downloads/<job_id>/report", methods=["GET"])
def download_report(job_id: str):
    """Download validation report JSON."""
    store = get_job_store()
    job = store.get_job(job_id)
    if not job or not job.project_path:
        abort(404, description="Job not found")

    report_path = Path(job.project_path) / "validation" / "svg_quality_report.json"
    if not report_path.is_file():
        abort(404, description="Validation report not found")

    return send_file(
        str(report_path),
        as_attachment=True,
        download_name=f"{job.project_name}_quality_report.json",
        mimetype="application/json",
    )
