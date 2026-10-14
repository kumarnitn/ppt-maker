"""Document intake and source extraction service."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from app.config import AppConfig
from app.utils.subprocess_runner import run_command_safe

logger = logging.getLogger("ppt_master.document_service")

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".xlsx",
    ".xlsm",
    ".csv",
    ".tsv",
    ".txt",
    ".md",
    ".markdown",
    ".html",
    ".htm",
}


class DocumentService:
    """Manages document validation and conversion into markdown using source_to_md.py."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.source_to_md_script = (
            self.config.skill_dir / "scripts" / "source_to_md.py"
        )

    def validate_file(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """Validate input file format and size."""
        if not file_path.is_file():
            return False, f"File does not exist: {file_path}"

        suffix = file_path.suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return (
                False,
                f"Unsupported file format '{suffix}'. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )

        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.config.upload_max_size_mb:
            return (
                False,
                f"File size ({file_size_mb:.1f} MB) exceeds limit of {self.config.upload_max_size_mb} MB.",
            )

        return True, None

    def convert_to_markdown(
        self,
        source_file: Path,
        output_dir: Optional[Path] = None,
    ) -> Tuple[Optional[Path], Optional[str]]:
        """Convert document to markdown using repository source_to_md.py.

        Returns (markdown_file_path, error_message).
        """
        valid, err = self.validate_file(source_file)
        if not valid:
            return None, err

        # If it's already markdown, return directly
        if source_file.suffix.lower() in {".md", ".markdown"}:
            return source_file, None

        cmd = [
            self.config.python_executable,
            str(self.source_to_md_script),
            str(source_file),
        ]
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            cmd.extend(["-o", str(output_dir)])

        logger.info("Executing source conversion: %s", cmd)
        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            timeout=self.config.subprocess_timeout,
        )

        if not res.is_success:
            logger.error("source_to_md failed: %s\n%s", res.stdout, res.stderr)
            return None, f"Source conversion failed: {res.stderr or res.stdout}"

        # Parse output path from stdout: "OUTPUT: <path>"
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("OUTPUT:"):
                out_path = Path(line.split("OUTPUT:", 1)[1].strip())
                if out_path.is_file():
                    return out_path, None

        # Fallback: check expected markdown beside source
        expected = source_file.with_suffix(".md")
        if expected.is_file():
            return expected, None

        if output_dir:
            expected_in_out = output_dir / f"{source_file.stem}.md"
            if expected_in_out.is_file():
                return expected_in_out, None

        return None, "Conversion completed but output markdown was not found."

    def extract_text_for_planning(self, md_path: Path) -> str:
        """Extract clean text content from markdown for presentation planning."""
        if not md_path.is_file():
            return ""
        return md_path.read_text(encoding="utf-8", errors="replace")
