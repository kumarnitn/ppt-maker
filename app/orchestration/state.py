"""Persistent SQLite job storage and state tracking."""

from __future__ import annotations

import datetime
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from app.schemas.job import JobPhase, JobResponse, JobStatus, JobStepLog

_DB_LOCK = threading.Lock()


class JobStore:
    """Thread-safe SQLite store for persistent job state and execution logs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with _DB_LOCK:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        project_name TEXT NOT NULL,
                        project_path TEXT,
                        status TEXT NOT NULL,
                        phase TEXT NOT NULL,
                        progress_percent INTEGER DEFAULT 0,
                        current_slide INTEGER DEFAULT 0,
                        total_slides INTEGER DEFAULT 0,
                        source_filename TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        error_message TEXT,
                        validation_summary TEXT,
                        output_pptx_path TEXT,
                        auto_approve INTEGER DEFAULT 1,
                        config_snapshot TEXT,
                        plan_json TEXT,
                        spec_json TEXT,
                        last_checkpoint TEXT
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS job_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        phase TEXT NOT NULL,
                        step_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        message TEXT NOT NULL,
                        details TEXT,
                        FOREIGN KEY (job_id) REFERENCES jobs (job_id)
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def create_job(
        self,
        job_id: str,
        project_name: str,
        project_path: Optional[str] = None,
        source_filename: Optional[str] = None,
        auto_approve: bool = True,
        config_snapshot: Optional[dict[str, Any]] = None,
    ) -> JobResponse:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _DB_LOCK:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO jobs (
                        job_id, project_name, project_path, status, phase,
                        progress_percent, current_slide, total_slides,
                        source_filename, created_at, updated_at,
                        auto_approve, config_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        project_name,
                        project_path,
                        JobStatus.CREATED.value,
                        JobPhase.INTAKE.value,
                        0,
                        0,
                        0,
                        source_filename,
                        now,
                        now,
                        1 if auto_approve else 0,
                        json.dumps(config_snapshot or {}),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        self.add_log(
            job_id,
            phase=JobPhase.INTAKE.value,
            step_name="JobCreated",
            status="SUCCESS",
            message=f"Job {job_id} created for project '{project_name}'.",
        )
        return self.get_job(job_id)  # type: ignore

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[JobStatus] = None,
        phase: Optional[JobPhase] = None,
        progress_percent: Optional[int] = None,
        current_slide: Optional[int] = None,
        total_slides: Optional[int] = None,
        project_path: Optional[str] = None,
        error_message: Optional[str] = None,
        validation_summary: Optional[dict[str, Any]] = None,
        output_pptx_path: Optional[str] = None,
        plan_json: Optional[str] = None,
        spec_json: Optional[str] = None,
        last_checkpoint: Optional[str] = None,
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [now]

        if status is not None:
            updates.append("status = ?")
            params.append(status.value)
        if phase is not None:
            updates.append("phase = ?")
            params.append(phase.value)
        if progress_percent is not None:
            updates.append("progress_percent = ?")
            params.append(progress_percent)
        if current_slide is not None:
            updates.append("current_slide = ?")
            params.append(current_slide)
        if total_slides is not None:
            updates.append("total_slides = ?")
            params.append(total_slides)
        if project_path is not None:
            updates.append("project_path = ?")
            params.append(project_path)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if validation_summary is not None:
            updates.append("validation_summary = ?")
            params.append(json.dumps(validation_summary))
        if output_pptx_path is not None:
            updates.append("output_pptx_path = ?")
            params.append(output_pptx_path)
        if plan_json is not None:
            updates.append("plan_json = ?")
            params.append(plan_json)
        if spec_json is not None:
            updates.append("spec_json = ?")
            params.append(spec_json)
        if last_checkpoint is not None:
            updates.append("last_checkpoint = ?")
            params.append(last_checkpoint)

        params.append(job_id)
        sql = f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?"

        with _DB_LOCK:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                conn.commit()
            finally:
                conn.close()

    def get_job(self, job_id: str) -> Optional[JobResponse]:
        with _DB_LOCK:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
                row = cursor.fetchone()
                if not row:
                    return None

                cursor.execute(
                    "SELECT timestamp, phase, step_name, status, message, details "
                    "FROM job_logs WHERE job_id = ? ORDER BY id ASC",
                    (job_id,),
                )
                log_rows = cursor.fetchall()
            finally:
                conn.close()

        logs = [
            JobStepLog(
                timestamp=r["timestamp"],
                phase=r["phase"],
                step_name=r["step_name"],
                status=r["status"],
                message=r["message"],
                details=json.loads(r["details"]) if r["details"] else None,
            )
            for r in log_rows
        ]

        val_summary = None
        if row["validation_summary"]:
            try:
                val_summary = json.loads(row["validation_summary"])
            except Exception:
                pass

        download_url = None
        if row["output_pptx_path"] and Path(row["output_pptx_path"]).is_file():
            download_url = f"/api/downloads/{job_id}/pptx"

        return JobResponse(
            job_id=row["job_id"],
            project_name=row["project_name"],
            project_path=row["project_path"],
            status=JobStatus(row["status"]),
            phase=JobPhase(row["phase"]),
            progress_percent=row["progress_percent"],
            current_slide=row["current_slide"],
            total_slides=row["total_slides"],
            source_filename=row["source_filename"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            error_message=row["error_message"],
            validation_summary=val_summary,
            output_pptx_path=row["output_pptx_path"],
            download_url=download_url,
            logs=logs,
            auto_approve=bool(row["auto_approve"]),
        )

    def list_jobs(self, limit: int = 50) -> list[JobResponse]:
        with _DB_LOCK:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
                rows = cursor.fetchall()
            finally:
                conn.close()

        results: list[JobResponse] = []
        for r in rows:
            job = self.get_job(r["job_id"])
            if job:
                results.append(job)
        return results

    def add_log(
        self,
        job_id: str,
        phase: str,
        step_name: str,
        status: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with _DB_LOCK:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO job_logs (
                        job_id, timestamp, phase, step_name, status, message, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        now,
                        phase,
                        step_name,
                        status,
                        message,
                        json.dumps(details) if details else None,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_plan_json(self, job_id: str) -> Optional[str]:
        with _DB_LOCK:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT plan_json FROM jobs WHERE job_id = ?", (job_id,))
                row = cursor.fetchone()
                return row["plan_json"] if row else None
            finally:
                conn.close()

    def get_spec_json(self, job_id: str) -> Optional[str]:
        with _DB_LOCK:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT spec_json FROM jobs WHERE job_id = ?", (job_id,))
                row = cursor.fetchone()
                return row["spec_json"] if row else None
            finally:
                conn.close()
