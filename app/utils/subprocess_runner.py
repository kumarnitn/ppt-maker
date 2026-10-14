"""Safe subprocess execution utility for invoking PPT Master scripts."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ppt_master.subprocess")


class SubprocessResult:
    """Encapsulates the result of a subprocess command execution."""

    def __init__(
        self,
        command: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
        duration_seconds: float,
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.duration_seconds = duration_seconds

    @property
    def is_success(self) -> bool:
        return self.returncode == 0

    def __repr__(self) -> str:
        return (
            f"<SubprocessResult rc={self.returncode} duration={self.duration_seconds:.2f}s "
            f"cmd={' '.join(self.command[:3])}...>"
        )


def run_command_safe(
    cmd: list[str],
    cwd: Optional[Path | str] = None,
    timeout: int = 180,
    env_overrides: Optional[dict[str, str]] = None,
) -> SubprocessResult:
    """Execute a command securely using argument lists and timeouts.

    Args:
        cmd: List of command arguments.
        cwd: Working directory (defaults to current repo root).
        timeout: Execution timeout in seconds.
        env_overrides: Additional or overridden environment variables.

    Returns:
        SubprocessResult containing exit code, stdout, stderr, duration.
    """
    if not cmd or not isinstance(cmd, list):
        raise ValueError("Command must be a non-empty list of string arguments.")

    # Ensure all elements are strings
    cmd_str = [str(arg) for arg in cmd]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if env_overrides:
        env.update(env_overrides)

    working_dir = str(cwd) if cwd else None

    logger.debug("Executing subprocess: %s (cwd=%s)", cmd_str, working_dir)
    import time

    start_time = time.time()
    try:
        process = subprocess.run(
            cmd_str,
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env,
        )
        duration = time.time() - start_time
        return SubprocessResult(
            command=cmd_str,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            duration_seconds=duration,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.time() - start_time
        logger.error("Command timed out after %ds: %s", timeout, cmd_str)
        return SubprocessResult(
            command=cmd_str,
            returncode=-1,
            stdout=exc.stdout or "",
            stderr=f"Command timed out after {timeout} seconds",
            duration_seconds=duration,
        )
    except Exception as exc:
        duration = time.time() - start_time
        logger.exception("Failed to execute command: %s", cmd_str)
        return SubprocessResult(
            command=cmd_str,
            returncode=-1,
            stdout="",
            stderr=f"Execution error: {exc}",
            duration_seconds=duration,
        )
