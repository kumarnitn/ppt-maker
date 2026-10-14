"""Unit tests for subprocess execution and file security utilities."""

import tempfile
import unittest
from pathlib import Path

from app.utils.file_utils import (
    atomic_write_text,
    compute_file_sha256,
    ensure_within_directory,
    sanitize_project_name,
)
from app.utils.subprocess_runner import run_command_safe


class TestUtils(unittest.TestCase):
    def test_subprocess_runner_success(self):
        res = run_command_safe(["python3", "-c", "print('hello from runner')"])
        self.assertTrue(res.is_success)
        self.assertIn("hello from runner", res.stdout)
        self.assertEqual(res.returncode, 0)

    def test_subprocess_runner_error(self):
        res = run_command_safe(["python3", "-c", "import sys; sys.exit(42)"])
        self.assertFalse(res.is_success)
        self.assertEqual(res.returncode, 42)

    def test_subprocess_runner_timeout(self):
        res = run_command_safe(["python3", "-c", "import time; time.sleep(5)"], timeout=1)
        self.assertFalse(res.is_success)
        self.assertEqual(res.returncode, -1)
        self.assertIn("timed out", res.stderr)

    def test_sanitize_project_name(self):
        self.assertEqual(sanitize_project_name("My Deck 2026!"), "My_Deck_2026")
        self.assertEqual(sanitize_project_name("../traversal/danger"), "traversal_danger")
        self.assertTrue(sanitize_project_name("").startswith("presentation_"))

    def test_ensure_within_directory_valid(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            child = base / "safe" / "file.txt"
            child.parent.mkdir()
            child.touch()
            resolved = ensure_within_directory(base, child)
            self.assertEqual(resolved, child.resolve())

    def test_ensure_within_directory_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "sub"
            base.mkdir()
            escaping = base / ".." / "outside.txt"
            with self.assertRaises(ValueError):
                ensure_within_directory(base, escaping)

    def test_atomic_write_and_sha256(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "nested" / "atomic.txt"
            atomic_write_text(target, "test content for atomic write")
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_text(), "test content for atomic write")
            sha = compute_file_sha256(target)
            self.assertEqual(len(sha), 64)


if __name__ == "__main__":
    unittest.main()
