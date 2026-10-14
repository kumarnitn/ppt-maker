"""Application entry point supporting Web UI and CLI workflows."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from flask import Flask, send_from_directory

from app.api import downloads_bp, jobs_bp, routes_bp
from app.config import get_config
from app.orchestration.state import JobStore
from app.orchestration.workflow import WorkflowEngine
from app.ai.client import get_ai_client
from app.ai.image_provider import get_image_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ppt_master.app")


def create_app() -> Flask:
    """Create and configure the Flask web application."""
    config = get_config()
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"

    app = Flask(
        __name__,
        static_folder=str(frontend_dir),
        static_url_path="",
    )

    # Register API blueprints
    app.register_blueprint(routes_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(downloads_bp)

    @app.route("/")
    def serve_index():
        return send_from_directory(str(frontend_dir), "index.html")

    @app.route("/<path:path>")
    def serve_static(path: str):
        return send_from_directory(str(frontend_dir), path)

    return app


def run_cli(args: argparse.Namespace) -> int:
    """Execute presentation generation in headless CLI mode."""
    config = get_config()
    store = JobStore(config.data_dir / "jobs.db")
    ai_client = get_ai_client(config)
    image_provider = get_image_provider(config)
    engine = WorkflowEngine(config, store, ai_client, image_provider)

    source_path = Path(args.source) if args.source else None
    if source_path and not source_path.is_file():
        logger.error("Source file not found: %s", source_path)
        return 1

    project_name = args.name or (source_path.stem if source_path else "cli_presentation")
    import uuid
    job_id = f"job_cli_{uuid.uuid4().hex[:8]}"

    params = {
        "project_name": project_name,
        "topic": args.topic or "",
        "purpose": args.purpose or "Executive Presentation",
        "audience": args.audience or "General Audience",
        "slide_count": args.slides,
        "aspect_ratio": args.aspect_ratio or "16:9",
        "style_direction": args.style or "Modern Clean",
        "enable_notes": not args.no_notes,
        "enable_animations": args.animations,
        "auto_approve": True,
    }

    print(f"\n=======================================================")
    print(f" PPT Master Standalone CLI Runner")
    print(f" Job ID: {job_id} | Project: {project_name}")
    print(f"=======================================================\n")

    store.create_job(
        job_id=job_id,
        project_name=project_name,
        source_filename=source_path.name if source_path else None,
        auto_approve=True,
    )

    engine.run_job(job_id, source_file_path=source_path, job_params=params)

    job = store.get_job(job_id)
    if job and job.status == "COMPLETED" and job.output_pptx_path:
        out_pptx = Path(job.output_pptx_path)
        print(f"\n[SUCCESS] Presentation generated successfully!")
        print(f"Export Path: {out_pptx}")
        print(f"Slides: {job.current_slide} / {job.total_slides}")

        if args.output:
            dest = Path(args.output)
            dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(out_pptx, dest)
            print(f"Copied to requested destination: {dest}")
        return 0
    else:
        print(f"\n[FAILED] Presentation generation failed: {job.error_message if job else 'Unknown'}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PPT Master - Standalone Presentation Generation Application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    # Server subcommand
    server_parser = subparsers.add_parser("server", help="Run local web interface and API server")
    server_parser.add_argument("--host", default=None, help="Host to bind (default from config)")
    server_parser.add_argument("--port", type=int, default=None, help="Port to bind (default from config)")
    server_parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")

    # CLI subcommand
    cli_parser = subparsers.add_parser("cli", help="Generate a presentation directly via CLI")
    cli_parser.add_argument("--source", "-s", help="Path to source document (PDF, Word, Markdown, etc.)")
    cli_parser.add_argument("--topic", "-t", help="Topic description or source text")
    cli_parser.add_argument("--name", "-n", help="Project name or slug")
    cli_parser.add_argument("--slides", type=int, help="Target slide count")
    cli_parser.add_argument("--purpose", help="Presentation purpose")
    cli_parser.add_argument("--audience", help="Target audience")
    cli_parser.add_argument("--aspect-ratio", default="16:9", help="Canvas aspect ratio (16:9 or 4:3)")
    cli_parser.add_argument("--style", default="Modern Clean", help="Visual style direction")
    cli_parser.add_argument("--no-notes", action="store_true", help="Disable speaker notes")
    cli_parser.add_argument("--animations", action="store_true", help="Enable native animations")
    cli_parser.add_argument("--output", "-o", help="Optional copy destination for output .pptx")

    args = parser.parse_args()
    config = get_config()

    if args.command == "cli":
        sys.exit(run_cli(args))
    else:
        # Default action is running server
        host = getattr(args, "host", None) or config.host
        port = getattr(args, "port", None) or config.port
        debug = getattr(args, "debug", False) or config.debug

        app = create_app()
        print(f"\n=======================================================")
        print(f" PPT Master Web Application Running")
        print(f" URL: http://{host}:{port}")
        print(f" Provider: {config.ai_provider}")
        print(f"=======================================================\n")
        app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
