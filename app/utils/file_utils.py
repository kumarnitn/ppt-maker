"""File handling and path security utilities."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Optional


def sanitize_project_name(name: Optional[str]) -> str:
    """Sanitize project name to a safe filesystem slug."""
    if not name or not name.strip():
        import datetime
        return f"presentation_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Replace invalid chars with underscore
    slug = re.sub(r"[^\w\-\.]+", "_", name.strip())
    slug = re.sub(r"_+", "_", slug).strip("._-")
    if not slug:
        import datetime
        return f"presentation_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return slug[:64]


def ensure_within_directory(base_dir: Path, target_path: Path) -> Path:
    """Ensure target_path does not escape base_dir (prevents directory traversal).

    Raises ValueError if path traverses outside base_dir.
    """
    resolved_base = base_dir.resolve()
    resolved_target = target_path.resolve()
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        raise ValueError(f"Path traversal detected: {target_path} is outside {base_dir}")
    return resolved_target


def atomic_write_text(file_path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text atomically using a temporary file in the same directory."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(
        "w",
        dir=str(file_path.parent),
        prefix=".tmp_",
        delete=False,
        encoding=encoding,
    )
    temp_path = Path(temp_file.name)
    try:
        temp_file.write(content)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_file.close()
        temp_path.replace(file_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as fp:
        while chunk := fp.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()
