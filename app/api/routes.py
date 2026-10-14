"""System and health check API routes."""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.config import get_config
from app.orchestration.state import JobStore

routes_bp = Blueprint("routes", __name__)


def get_job_store() -> JobStore:
    config = get_config()
    return JobStore(config.data_dir / "jobs.db")


@routes_bp.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify(
        {
            "status": "ok",
            "service": "PPT Master Standalone Application",
            "version": "1.0.0",
        }
    )


@routes_bp.route("/api/config", methods=["GET"])
def get_system_config():
    """Return non-sensitive configuration settings."""
    config = get_config()
    validation_errors = config.validate_provider_config()
    return jsonify(
        {
            "config": config.redacted_dict(),
            "provider_ready": len(validation_errors) == 0,
            "provider_validation_errors": validation_errors,
        }
    )


@routes_bp.route("/api/stats", methods=["GET"])
def get_system_stats():
    """Return summary statistics of presentation jobs."""
    store = get_job_store()
    jobs = store.list_jobs(limit=100)
    total = len(jobs)
    completed = sum(1 for j in jobs if j.status == "COMPLETED")
    failed = sum(1 for j in jobs if j.status == "FAILED")
    running = total - completed - failed

    return jsonify(
        {
            "total_jobs": total,
            "completed_jobs": completed,
            "failed_jobs": failed,
            "in_progress_jobs": running,
        }
    )
