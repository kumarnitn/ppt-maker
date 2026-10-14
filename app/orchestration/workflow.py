"""Workflow execution engine orchestrating the 6-phase presentation lifecycle."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

from app.ai.client import BaseAIClient
from app.ai.image_provider import BaseImageProvider
from app.config import AppConfig
from app.orchestration.checkpoints import CheckpointManager
from app.orchestration.recovery import JobRecoveryManager
from app.orchestration.state import JobStore
from app.schemas.job import JobPhase, JobResponse, JobStatus
from app.schemas.plan import PresentationPlan
from app.services.asset_service import AssetService
from app.services.document_service import DocumentService
from app.services.export_service import ExportService
from app.services.notes_service import NotesService
from app.services.planning_service import PlanningService
from app.services.project_service import ProjectService
from app.services.slide_service import SlideService
from app.services.validation_service import ValidationService

logger = logging.getLogger("ppt_master.workflow")


class WorkflowEngine:
    """Orchestrates end-to-end presentation generation jobs."""

    def __init__(
        self,
        config: AppConfig,
        job_store: JobStore,
        ai_client: BaseAIClient,
        image_provider: BaseImageProvider,
    ) -> None:
        self.config = config
        self.store = job_store
        self.ai_client = ai_client
        self.image_provider = image_provider

        # Services
        self.doc_service = DocumentService(config)
        self.project_service = ProjectService(config)
        self.planning_service = PlanningService(config, ai_client)
        self.asset_service = AssetService(config, image_provider)
        self.validation_service = ValidationService(config)
        self.slide_service = SlideService(config, ai_client, self.validation_service)
        self.notes_service = NotesService(config, ai_client)
        self.export_service = ExportService(config)

    def start_job_async(
        self,
        job_id: str,
        source_file_path: Optional[Path] = None,
        job_params: Optional[dict[str, Any]] = None,
    ) -> threading.Thread:
        """Run presentation generation workflow in a background thread."""
        thread = threading.Thread(
            target=self.run_job,
            args=(job_id, source_file_path, job_params),
            daemon=True,
            name=f"job-{job_id}",
        )
        thread.start()
        return thread

    def resume_job_async(self, job_id: str) -> threading.Thread:
        """Resume an existing job in background."""
        thread = threading.Thread(
            target=self.resume_job,
            args=(job_id,),
            daemon=True,
            name=f"resume-{job_id}",
        )
        thread.start()
        return thread

    def run_job(
        self,
        job_id: str,
        source_file_path: Optional[Path] = None,
        job_params: Optional[dict[str, Any]] = None,
    ) -> None:
        """Execute the 6-phase presentation lifecycle synchronously."""
        params = job_params or {}
        job = self.store.get_job(job_id)
        if not job:
            logger.error("Job %s not found in store.", job_id)
            return

        try:
            # ─────────────────────────────────────────────────────────────
            # Phase 0: Intake and source extraction
            # ─────────────────────────────────────────────────────────────
            self.store.update_job(
                job_id,
                status=JobStatus.INGESTING,
                phase=JobPhase.INTAKE,
                progress_percent=5,
            )
            self.store.add_log(
                job_id,
                phase=JobPhase.INTAKE.value,
                step_name="SourceIntake",
                status="RUNNING",
                message="Validating and converting source document...",
            )

            project_path: Optional[Path] = None
            if job.project_path:
                project_path = Path(job.project_path)

            converted_md: Optional[Path] = None
            doc_text = ""

            if source_file_path and source_file_path.is_file():
                converted_md, conv_err = self.doc_service.convert_to_markdown(source_file_path)
                if conv_err or not converted_md:
                    raise RuntimeError(f"Source conversion failed: {conv_err}")
                doc_text = self.doc_service.extract_text_for_planning(converted_md)
            elif params.get("topic"):
                doc_text = params["topic"]
            else:
                doc_text = "General presentation overview."

            # Initialize project directory if not already created
            if not project_path or not project_path.is_dir():
                project_path, init_err = self.project_service.initialize_project(
                    project_name=params.get("project_name") or job.project_name,
                    quick_generate=True,
                )
                if init_err or not project_path:
                    raise RuntimeError(f"Project initialization failed: {init_err}")
                self.store.update_job(job_id, project_path=str(project_path))

            # Import sources
            if source_file_path and source_file_path.is_file():
                self.project_service.import_sources(project_path, source_file_path, converted_md)

            self.store.add_log(
                job_id,
                phase=JobPhase.INTAKE.value,
                step_name="SourceIntake",
                status="SUCCESS",
                message=f"Source content ready in {project_path.name}/sources.",
            )
            self.store.update_job(job_id, last_checkpoint="INTAKE", progress_percent=15)

            # ─────────────────────────────────────────────────────────────
            # Phase 1: Strategist and presentation planning
            # ─────────────────────────────────────────────────────────────
            self.store.update_job(
                job_id,
                status=JobStatus.PLANNING,
                phase=JobPhase.PLANNING,
                progress_percent=20,
            )
            self.store.add_log(
                job_id,
                phase=JobPhase.PLANNING.value,
                step_name="StrategistPlan",
                status="RUNNING",
                message="Generating structured presentation outline with AI...",
            )

            plan, plan_file = self.planning_service.create_presentation_plan(
                document_text=doc_text,
                params=params,
                project_path=project_path,
            )

            self.store.update_job(
                job_id,
                plan_json=plan.model_dump_json(),
                total_slides=len(plan.slides),
                last_checkpoint="PLANNING",
                progress_percent=30,
            )
            self.store.add_log(
                job_id,
                phase=JobPhase.PLANNING.value,
                step_name="StrategistPlan",
                status="SUCCESS",
                message=f"Presentation plan created with {len(plan.slides)} slides.",
            )

            # Check if user approval gate is requested
            if not job.auto_approve:
                self.store.update_job(
                    job_id,
                    status=JobStatus.AWAITING_APPROVAL,
                    phase=JobPhase.PLANNING,
                )
                self.store.add_log(
                    job_id,
                    phase=JobPhase.PLANNING.value,
                    step_name="ApprovalGate",
                    status="WAITING",
                    message="Presentation plan generated. Awaiting user review and approval.",
                )
                logger.info("Job %s is now AWAITING_APPROVAL.", job_id)
                return  # Pause here; resume after approve_plan API is called

            # ─────────────────────────────────────────────────────────────
            # Continue through remaining phases
            # ─────────────────────────────────────────────────────────────
            self._execute_generation_phases(job_id, project_path, plan, params)

        except Exception as exc:
            logger.exception("Job %s failed with error: %s", job_id, exc)
            self.store.update_job(
                job_id,
                status=JobStatus.FAILED,
                error_message=str(exc),
            )
            self.store.add_log(
                job_id,
                phase=JobPhase.INTAKE.value,
                step_name="JobExecution",
                status="ERROR",
                message=f"Job failed: {exc}",
            )

    def _execute_generation_phases(
        self,
        job_id: str,
        project_path: Path,
        plan: PresentationPlan,
        params: dict[str, Any],
        start_slide_index: int = 1,
    ) -> None:
        """Execute phases 2 to 5 after plan approval."""
        total_slides = len(plan.slides)

        # ─────────────────────────────────────────────────────────────
        # Phase 2: Design specification & asset preparation
        # ─────────────────────────────────────────────────────────────
        self.store.update_job(
            job_id,
            status=JobStatus.PREPARING_ASSETS,
            phase=JobPhase.DESIGN,
            progress_percent=35,
        )
        self.store.add_log(
            job_id,
            phase=JobPhase.DESIGN.value,
            step_name="DesignSpecification",
            status="RUNNING",
            message="Creating design specifications and preparing vector icons...",
        )

        spec, spec_file, lock_file = self.planning_service.create_design_spec_and_lock(
            plan=plan,
            params=params,
            project_path=project_path,
        )
        self.asset_service.prepare_assets(plan, project_path)

        self.store.update_job(
            job_id,
            spec_json=spec.model_dump_json(),
            last_checkpoint="DESIGN",
            progress_percent=40,
        )
        self.store.add_log(
            job_id,
            phase=JobPhase.DESIGN.value,
            step_name="DesignSpecification",
            status="SUCCESS",
            message="Design spec locked and icons synchronized.",
        )

        # ─────────────────────────────────────────────────────────────
        # Phase 3: Slide construction & quality gates
        # ─────────────────────────────────────────────────────────────
        self.store.update_job(
            job_id,
            status=JobStatus.GENERATING_SLIDES,
            phase=JobPhase.CONSTRUCTION,
            progress_percent=45,
        )

        def on_slide_progress(current: int, total: int) -> None:
            # Scale progress 45% -> 80% across slides
            progress = 45 + int((current / total) * 35)
            self.store.update_job(
                job_id,
                current_slide=current,
                progress_percent=progress,
            )
            self.store.add_log(
                job_id,
                phase=JobPhase.CONSTRUCTION.value,
                step_name="SlideGenerated",
                status="SUCCESS",
                message=f"Generated and validated slide {current}/{total}.",
            )

        slides_valid, val_report = self.slide_service.run_slide_pipeline(
            plan=plan,
            spec=spec,
            project_path=project_path,
            on_slide_completed=on_slide_progress,
            start_slide_index=start_slide_index,
        )

        self.store.update_job(
            job_id,
            validation_summary=val_report.to_dict(),
            last_checkpoint="SLIDES",
            progress_percent=80,
        )

        if not slides_valid:
            error_details = (
                "; ".join(str(iss) for iss in val_report.blocking_issues)
                if val_report.blocking_issues
                else "Quality gates failed"
            )
            raise RuntimeError(f"Slide quality gates failed: {error_details}")

        self.store.add_log(
            job_id,
            phase=JobPhase.CONSTRUCTION.value,
            step_name="QualityGateFinal",
            status="SUCCESS",
            message=f"All {total_slides} slides passed SVG quality gates.",
        )

        # ─────────────────────────────────────────────────────────────
        # Phase 4: Speaker notes
        # ─────────────────────────────────────────────────────────────
        enable_notes = params.get("enable_notes", True)
        if enable_notes:
            self.store.update_job(
                job_id,
                status=JobStatus.GENERATING_NOTES,
                phase=JobPhase.NOTES,
                progress_percent=85,
            )
            self.store.add_log(
                job_id,
                phase=JobPhase.NOTES.value,
                step_name="SpeakerNotes",
                status="RUNNING",
                message="Generating speaker notes...",
            )
            self.notes_service.generate_and_split_notes(plan, project_path)
            self.store.add_log(
                job_id,
                phase=JobPhase.NOTES.value,
                step_name="SpeakerNotes",
                status="SUCCESS",
                message="Speaker notes synchronized and split.",
            )

        # ─────────────────────────────────────────────────────────────
        # Phase 5: Finalization and native compilation
        # ─────────────────────────────────────────────────────────────
        self.store.update_job(
            job_id,
            status=JobStatus.COMPILING,
            phase=JobPhase.FINALIZATION,
            progress_percent=90,
        )
        self.store.add_log(
            job_id,
            phase=JobPhase.FINALIZATION.value,
            step_name="Compilation",
            status="RUNNING",
            message="Finalizing SVG assets and compiling native PowerPoint OpenXML package...",
        )

        # Finalize SVG
        self.export_service.finalize_assets(project_path)

        # Compile PPTX
        pptx_path, compile_err = self.export_service.compile_pptx(
            project_path=project_path,
            enable_notes=enable_notes,
            enable_animations=params.get("enable_animations", True),
            transition=params.get("transition", "push"),
            animation_trigger=params.get("animation_trigger", "after-previous"),
        )

        if compile_err or not pptx_path:
            raise RuntimeError(f"PowerPoint compilation failed: {compile_err}")

        # Completed!
        self.store.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            phase=JobPhase.COMPLETE,
            output_pptx_path=str(pptx_path),
            last_checkpoint="EXPORT",
            progress_percent=100,
        )
        self.store.add_log(
            job_id,
            phase=JobPhase.COMPLETE.value,
            step_name="ExportCompleted",
            status="SUCCESS",
            message=f"Presentation successfully exported to {pptx_path.name}!",
        )
        logger.info("Job %s successfully COMPLETED! Export: %s", job_id, pptx_path)

    def approve_plan(
        self,
        job_id: str,
        revised_plan: Optional[PresentationPlan] = None,
    ) -> bool:
        """Approve plan and trigger continuation of workflow."""
        job = self.store.get_job(job_id)
        if not job or job.status != JobStatus.AWAITING_APPROVAL:
            return False

        project_path = Path(job.project_path)
        plan_str = self.store.get_plan_json(job_id)
        plan = (
            revised_plan
            if revised_plan
            else (PresentationPlan.model_validate_json(plan_str) if plan_str else None)
        )

        if not plan:
            return False

        if revised_plan:
            self.store.update_job(
                job_id,
                plan_json=revised_plan.model_dump_json(),
                total_slides=len(revised_plan.slides),
            )

        self.store.add_log(
            job_id,
            phase=JobPhase.PLANNING.value,
            step_name="PlanApproved",
            status="SUCCESS",
            message="Presentation plan approved by user. Resuming generation.",
        )

        thread = threading.Thread(
            target=self._execute_generation_phases,
            args=(job_id, project_path, plan, {}),
            daemon=True,
            name=f"exec-{job_id}",
        )
        thread.start()
        return True

    def resume_job(self, job_id: str) -> bool:
        """Resume an interrupted or failed job from its last valid checkpoint."""
        job = self.store.get_job(job_id)
        if not job or not job.project_path:
            return False

        project_path = Path(job.project_path)
        if not project_path.is_dir():
            return False

        status, phase, resume_slide = JobRecoveryManager.determine_resume_point(
            project_path, job.total_slides
        )

        logger.info(
            "Resuming job %s: determined point (status=%s, phase=%s, slide=%d)",
            job_id,
            status,
            phase,
            resume_slide,
        )

        plan_str = self.store.get_plan_json(job_id)
        if not plan_str:
            # Need to re-run from scratch
            self.run_job(job_id)
            return True

        plan = PresentationPlan.model_validate_json(plan_str)

        self.store.add_log(
            job_id,
            phase=phase.value,
            step_name="JobResumed",
            status="RUNNING",
            message=f"Resuming job from checkpoint at slide {resume_slide}...",
        )

        self._execute_generation_phases(
            job_id=job_id,
            project_path=project_path,
            plan=plan,
            params={},
            start_slide_index=resume_slide if resume_slide > 0 else 1,
        )
        return True
