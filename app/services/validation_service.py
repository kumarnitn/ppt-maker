"""SVG quality validation and report parsing service."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

from app.config import AppConfig
from app.utils.subprocess_runner import run_command_safe

logger = logging.getLogger("ppt_master.validation_service")

# Disallowed HTML entities
FORBIDDEN_HTML_ENTITIES = [
    "&bull;",
    "&mdash;",
    "&ndash;",
    "&copy;",
    "&reg;",
    "&rarr;",
    "&middot;",
    "&nbsp;",
    "&hellip;",
]

FORBIDDEN_TAGS = [
    "<style",
    "<foreignobject",
    "<script",
    "<iframe",
    "<animate",
]


class ValidationResult:
    """Encapsulates SVG quality gate check results."""

    def __init__(
        self,
        is_valid: bool,
        blocking_issues: list[str],
        warnings: list[str],
        raw_report: Optional[dict[str, Any]] = None,
    ) -> None:
        self.is_valid = is_valid
        self.blocking_issues = blocking_issues
        self.warnings = warnings
        self.raw_report = raw_report or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "blocking_count": len(self.blocking_issues),
            "warning_count": len(self.warnings),
            "blocking_issues": self.blocking_issues,
            "warnings": self.warnings[:20],
        }


class ValidationService:
    """Validates SVG syntax and executes repo svg_quality_checker.py."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.checker_script = self.config.skill_dir / "scripts" / "svg_quality_checker.py"

    def sanitize_svg_content(self, svg_content: str) -> str:
        """Sanitize common LLM formatting quirks in SVG."""
        sanitized = svg_content

        # 1. Strip forbidden tags (foreignObject, style, script, animate)
        sanitized = re.sub(
            r"<(?:foreignObject|style|script|animate)\b[^>]*>.*?</(?:foreignObject|style|script|animate)>",
            "",
            sanitized,
            flags=re.IGNORECASE | re.DOTALL,
        )
        sanitized = re.sub(
            r"<(?:foreignObject|style|script|animate)\b[^>]*/>",
            "",
            sanitized,
            flags=re.IGNORECASE,
        )

        # 2. Replace forbidden HTML named entities with XML/Unicode equivalents
        entity_replacements = {
            "&bull;": "&#8226;",
            "&mdash;": "&#8212;",
            "&ndash;": "&#8211;",
            "&copy;": "&#169;",
            "&reg;": "&#174;",
            "&rarr;": "&#8594;",
            "&middot;": "&#183;",
            "&nbsp;": " ",
            "&hellip;": "&#8230;",
        }
        for ent, rep in entity_replacements.items():
            sanitized = sanitized.replace(ent, rep)

        # 3. Strip class="..." attributes
        sanitized = re.sub(r'\bclass\s*=\s*["\'][^"\']*["\']', "", sanitized, flags=re.IGNORECASE)

        # 4. Clean whitespace within data URIs: href="data:image/... "
        def _clean_data_uri(match: re.Match) -> str:
            attr = match.group(1)
            quote = match.group(2)
            uri = match.group(3)
            cleaned_uri = re.sub(r"\s+", "", uri)
            return f"{attr}{quote}{cleaned_uri}{quote}"

        sanitized = re.sub(
            r'((?:xlink:)?href=)(["\'])(data:image/[^"\']+)\2',
            _clean_data_uri,
            sanitized,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # 5. Deterministically clamp bounds and wrap overflowing text
        sanitized = self.normalize_svg_viewbox_bounds(sanitized)
        return sanitized

    def normalize_svg_viewbox_bounds(self, svg_content: str) -> str:
        """Deterministically clamp and reflow coordinates exceeding the 1280x720 canvas, including transformed groups."""
        try:
            return self._dom_normalize_svg_viewbox_bounds(svg_content)
        except Exception as exc:
            logger.warning("DOM-based SVG normalization failed (%s), falling back to regex: %s", type(exc).__name__, exc)
            return self._regex_normalize_svg_viewbox_bounds(svg_content)

    def _dom_normalize_svg_viewbox_bounds(self, svg_content: str) -> str:
        """DOM-aware normalizer tracking accumulated transforms (e.g. <g transform='translate(...)'>)."""
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

        root = ET.fromstring(svg_content)
        svg_ns = "http://www.w3.org/2000/svg"

        def _local_tag(elem: ET.Element) -> str:
            return elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        def _parse_translate(tr: str) -> tuple[float, float]:
            if not tr:
                return 0.0, 0.0
            m = re.search(r"translate\(\s*([-+]?\d+(?:\.\d+)?)[,\s]+([-+]?\d+(?:\.\d+)?)\s*\)", tr)
            if m:
                return float(m.group(1)), float(m.group(2))
            m1 = re.search(r"translate\(\s*([-+]?\d+(?:\.\d+)?)\s*\)", tr)
            if m1:
                return float(m1.group(1)), 0.0
            return 0.0, 0.0

        def _walk_and_normalize(elem: ET.Element, parent_tx: float = 0.0, parent_ty: float = 0.0) -> None:
            tx, ty = _parse_translate(elem.get("transform", ""))
            cur_tx = parent_tx + tx
            cur_ty = parent_ty + ty

            tag = _local_tag(elem)
            if tag == "text":
                lx = float(elem.get("x", "80"))
                ly = float(elem.get("y", "40"))
                rx = cur_tx + lx
                ry = cur_ty + ly

                # Prevent left-edge overflow caused by invalid text-anchor on left-aligned text
                anchor = elem.get("text-anchor")
                if anchor == "middle" and rx < 250:
                    elem.attrib.pop("text-anchor", None)
                elif anchor == "end" and rx < 100:
                    elem.attrib.pop("text-anchor", None)

                # Vertical clamping in root space
                if ry >= 675:
                    new_ly = max(30.0, 660.0 - cur_ty)
                    elem.set("y", f"{new_ly:.0f}")
                elif ry < 30:
                    new_ly = max(30.0, 50.0 - cur_ty)
                    elem.set("y", f"{new_ly:.0f}")

                fs = float(elem.get("font-size", "20"))
                char_w = fs * 0.55
                lh = int(fs * 1.3)

                tspans = [ch for ch in elem if _local_tag(ch) == "tspan"]
                if not tspans:
                    text = (elem.text or "").strip()
                    if (rx + len(text) * char_w) > 1220 and len(text) > 15:
                        avail_w = max(100.0, 1220.0 - rx)
                        max_chars = max(12, int(avail_w / char_w))
                        words = text.split()
                        lines = []
                        curr: list[str] = []
                        for w in words:
                            cand = " ".join(curr + [w])
                            if len(cand) <= max_chars or not curr:
                                curr.append(w)
                            else:
                                lines.append(" ".join(curr))
                                curr = [w]
                        if curr:
                            lines.append(" ".join(curr))

                        elem.text = None
                        for i, line in enumerate(lines):
                            ts = ET.Element(f"{{{svg_ns}}}tspan" if "}" in elem.tag else "tspan")
                            ts.set("x", f"{lx:.0f}")
                            ts.set("dy", f"{0 if i == 0 else lh}")
                            ts.text = line
                            elem.append(ts)
                else:
                    needs_rewrap = False
                    for ts in tspans:
                        tsx = float(ts.get("x", str(lx)))
                        r_tsx = cur_tx + tsx
                        tst = (ts.text or "").strip()
                        if (r_tsx + len(tst) * char_w) > 1220 and len(tst) > 15:
                            needs_rewrap = True
                            break

                    if needs_rewrap:
                        all_text = " ".join((ts.text or "").strip() for ts in tspans)
                        avail_w = max(100.0, 1220.0 - rx)
                        max_chars = max(12, int(avail_w / char_w))
                        words = all_text.split()
                        lines = []
                        curr = []
                        for w in words:
                            cand = " ".join(curr + [w])
                            if len(cand) <= max_chars or not curr:
                                curr.append(w)
                            else:
                                lines.append(" ".join(curr))
                                curr = [w]
                        if curr:
                            lines.append(" ".join(curr))

                        for ts in list(tspans):
                            elem.remove(ts)
                        for i, line in enumerate(lines):
                            ts = ET.Element(f"{{{svg_ns}}}tspan" if "}" in elem.tag else "tspan")
                            ts.set("x", f"{lx:.0f}")
                            ts.set("dy", f"{0 if i == 0 else lh}")
                            ts.text = line
                            elem.append(ts)

            elif tag == "rect":
                lx = float(elem.get("x", "0"))
                ly = float(elem.get("y", "0"))
                w = float(elem.get("width", "0"))
                h = float(elem.get("height", "0"))
                rx = cur_tx + lx
                ry = cur_ty + ly
                if 0 <= rx < 1280 and w < 1280 and (rx + w) > 1240:
                    new_w = max(100.0, 1220.0 - rx)
                    elem.set("width", f"{new_w:.0f}")
                if 0 <= ry < 720 and h < 720 and (ry + h) > 680:
                    new_h = max(60.0, 660.0 - ry)
                    elem.set("height", f"{new_h:.0f}")

            for ch in elem:
                _walk_and_normalize(ch, cur_tx, cur_ty)

        _walk_and_normalize(root)
        normalized = ET.tostring(root, encoding="unicode")
        return self._regex_normalize_svg_viewbox_bounds(normalized)

    def _regex_normalize_svg_viewbox_bounds(self, svg_content: str) -> str:
        """Regex-based fallback to clamp raw coordinates and wrap plain unnested text."""
        sanitized = svg_content

        # 1. Clamp any text/tspan y coordinate >= 675 down to 660, and < 30 up to 50
        def _clamp_text_tag(match: re.Match) -> str:
            tag_str = match.group(0)
            y_m = re.search(r'\by\s*=\s*(["\'])([-+]?\d+(?:\.\d+)?)\1', tag_str)
            if not y_m:
                return tag_str
            q = y_m.group(1)
            y_val = float(y_m.group(2))
            if y_val >= 675:
                return re.sub(r'\by\s*=\s*(["\'])[-+]?\d+(?:\.\d+)?\1', f'y={q}660{q}', tag_str, count=1)
            if y_val < 30:
                return re.sub(r'\by\s*=\s*(["\'])[-+]?\d+(?:\.\d+)?\1', f'y={q}50{q}', tag_str, count=1)
            return tag_str

        sanitized = re.sub(r'<(?:text|tspan)\b[^>]*>', _clamp_text_tag, sanitized)

        # 2. Fix cards exceeding 1280 width or 720 height
        def _clamp_rect_bounds(match: re.Match) -> str:
            rect_tag = match.group(0)
            x_m = re.search(r'\bx\s*=\s*["\']([-+]?\d+(?:\.\d+)?)["\']', rect_tag)
            w_m = re.search(r'\bwidth\s*=\s*["\']([-+]?\d+(?:\.\d+)?)["\']', rect_tag)
            y_m = re.search(r'\by\s*=\s*["\']([-+]?\d+(?:\.\d+)?)["\']', rect_tag)
            h_m = re.search(r'\bheight\s*=\s*["\']([-+]?\d+(?:\.\d+)?)["\']', rect_tag)

            if x_m and w_m:
                x = float(x_m.group(1))
                w = float(w_m.group(1))
                if 0 <= x < 1280 and w < 1280 and (x + w) > 1240:
                    new_w = max(100.0, 1220.0 - x)
                    rect_tag = re.sub(r'\bwidth\s*=\s*["\'][-+]?\d+(?:\.\d+)?["\']', f'width="{new_w:.0f}"', rect_tag)

            if y_m and h_m:
                y = float(y_m.group(1))
                h = float(h_m.group(1))
                if 0 <= y < 720 and h < 720 and (y + h) > 680:
                    new_h = max(60.0, 660.0 - y)
                    rect_tag = re.sub(r'\bheight\s*=\s*["\'][-+]?\d+(?:\.\d+)?["\']', f'height="{new_h:.0f}"', rect_tag)

            return rect_tag

        sanitized = re.sub(r'<rect\b[^>]*>', _clamp_rect_bounds, sanitized)

        # 3. Wrap single-line or tspan text that would exceed horizontal bounds (> 1220)
        def _wrap_overflowing_text(match: re.Match) -> str:
            text_tag = match.group(0)
            open_m = re.match(r'(<text\b[^>]*>)(.*?)(</text>)', text_tag, re.DOTALL)
            if not open_m:
                return text_tag

            open_tag, inner_body, close_tag = open_m.groups()
            x_m = re.search(r'\bx\s*=\s*["\']([-+]?\d+(?:\.\d+)?)["\']', open_tag)
            size_m = re.search(r'\bfont-size\s*=\s*["\']([-+]?\d+(?:\.\d+)?)["\']', open_tag)

            base_x = float(x_m.group(1)) if x_m else 80.0
            font_size = float(size_m.group(1)) if size_m else 20.0
            char_w = font_size * 0.55
            lh = int(font_size * 1.3)

            if "<tspan" not in inner_body:
                clean_str = inner_body.strip()
                est_width = len(clean_str) * char_w
                if (base_x + est_width) > 1220 and len(clean_str) > 20:
                    avail_w = max(100.0, 1220.0 - base_x)
                    max_chars = max(12, int(avail_w / char_w))
                    words = clean_str.split()
                    lines = []
                    curr = []
                    for w in words:
                        cand = " ".join(curr + [w])
                        if len(cand) <= max_chars or not curr:
                            curr.append(w)
                        else:
                            lines.append(" ".join(curr))
                            curr = [w]
                    if curr:
                        lines.append(" ".join(curr))

                    tspans = "".join(
                        f'<tspan x="{base_x:.0f}" dy="{0 if i == 0 else lh}">{line}</tspan>'
                        for i, line in enumerate(lines)
                    )
                    return f"{open_tag}{tspans}{close_tag}"
            return text_tag

        sanitized = re.sub(r'<text\b[^>]*>.*?</text>', _wrap_overflowing_text, sanitized, flags=re.DOTALL)
        return sanitized

    def preflight_svg_text(self, svg_content: str, slide_name: str = "slide") -> list[str]:
        """Fast local syntax and rule check before disk write or quality checker."""
        errors: list[str] = []

        # 1. Check for banned HTML entities
        for ent in FORBIDDEN_HTML_ENTITIES:
            if ent in svg_content:
                errors.append(
                    f"Forbidden HTML named entity '{ent}' found. Use raw Unicode or standard XML entity."
                )

        # 2. Check for banned tags
        lower_svg = svg_content.lower()
        for tag in FORBIDDEN_TAGS:
            if tag in lower_svg:
                errors.append(f"Forbidden tag '{tag}>' found in SVG. Remove and use inline presentation attributes.")

        # 3. Check for CSS class attributes
        if re.search(r'\bclass\s*=', svg_content):
            errors.append("Forbidden 'class' attribute found. Styles must be applied as inline SVG attributes.")

        # 4. Check for invalid or corrupt <image> tags
        if "<image" in lower_svg:
            for match in re.finditer(r'<image\b[^>]*\b(?:href|xlink:href)=["\']([^"\']+)["\']', svg_content):
                href = match.group(1).strip()
                if href.startswith("data:image/"):
                    try:
                        _, payload = href.split(",", 1)
                        cleaned_payload = "".join(payload.split())
                        # Check padding & length
                        if len(cleaned_payload) == 0 or len(cleaned_payload) % 4 != 0:
                            errors.append(
                                "Invalid <image> data URI encoding. Use vector SVG shapes (<rect>, <path>, <text>) instead of inline base64."
                            )
                    except Exception:
                        errors.append(
                            "Malformed <image> data URI. Replace with vector SVG shapes and icons."
                        )

        # 5. XML parse check and viewBox bounds check
        try:
            root = ET.fromstring(svg_content)
            if not root.tag.endswith("svg"):
                errors.append(f"Root tag must be <svg>, got <{root.tag}>")
            if not root.get("viewBox"):
                errors.append("Missing viewBox attribute on root <svg> element.")

            # Check text and tspan horizontal bounds against 1280 canvas
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag == "text":
                    lx = float(elem.get("x", "0"))
                    ly = float(elem.get("y", "0"))
                    fs = float(elem.get("font-size", "20"))
                    char_w = fs * 0.55
                    tspans = [ch for ch in elem if (ch.tag.split("}")[-1] if "}" in ch.tag else ch.tag) == "tspan"]
                    if not tspans:
                        text = (elem.text or "").strip()
                        if (lx + len(text) * char_w) > 1260 and len(text) > 15:
                            errors.append(
                                f"[{slide_name}] <text> (x={lx:.0f}, y={ly:.0f}; text='{text[:25]}...') "
                                f"exceeds root viewBox width ({lx + len(text) * char_w:.1f} > 1280). Reflow into <tspan> lines."
                            )
                    else:
                        for ts in tspans:
                            tsx = float(ts.get("x", str(lx)))
                            tst = (ts.text or "").strip()
                            if (tsx + len(tst) * char_w) > 1260 and len(tst) > 15:
                                errors.append(
                                    f"[{slide_name}] <tspan> (x={tsx:.0f}; text='{tst[:25]}...') "
                                    f"exceeds root viewBox width ({tsx + len(tst) * char_w:.1f} > 1280). Reflow into shorter lines."
                                )
        except ET.ParseError as exc:
            errors.append(f"XML Parse Error: {exc}")
        except Exception:
            pass

        return errors

    @staticmethod
    def _normalize_issue(item: Any) -> str:
        """Ensure an issue entry from quality checker is formatted as a string."""
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            f = item.get("file")
            m = item.get("message") or item.get("rule") or str(item)
            return f"[{f}] {m}" if f else str(m)
        return str(item)

    def run_quality_checker(
        self,
        project_path: Path,
        stage: str = "final",  # "early" or "final"
        quick_generate: bool = True,
    ) -> ValidationResult:
        """Run repository svg_quality_checker.py and parse report."""
        cmd = [
            self.config.python_executable,
            str(self.checker_script),
            str(project_path),
            "--canonical-authoring",
            "--stage",
            stage,
            "--json",
        ]
        if quick_generate:
            cmd.append("--quick-generate")

        logger.info("Running SVG quality checker: %s", cmd)
        res = run_command_safe(
            cmd,
            cwd=self.config.repo_root,
            timeout=self.config.subprocess_timeout,
        )

        report_file_name = (
            "svg_quality_early_report.json" if stage == "early" else "svg_quality_report.json"
        )
        report_file = project_path / "validation" / report_file_name

        blocking_issues: list[str] = []
        warnings: list[str] = []
        raw_report: dict[str, Any] = {}

        if report_file.is_file():
            try:
                raw_report = json.loads(report_file.read_text(encoding="utf-8"))
                categories = raw_report.get("categories", {})
                raw_blocking = categories.get("blocking", {}).get("issues", [])
                raw_warnings = categories.get("warnings", {}).get("issues", [])
                blocking_issues = [self._normalize_issue(it) for it in raw_blocking]
                warnings = [self._normalize_issue(it) for it in raw_warnings]
            except Exception as exc:
                logger.warning("Failed to parse quality report JSON: %s", exc)

        if not res.is_success and not blocking_issues:
            # Command exited non-zero but no blocking issues in JSON: pull from stderr/stdout
            blocking_issues.append(res.stderr or res.stdout or f"Quality check failed with rc {res.returncode}")

        is_valid = len(blocking_issues) == 0 and res.returncode == 0
        return ValidationResult(
            is_valid=is_valid,
            blocking_issues=blocking_issues,
            warnings=warnings,
            raw_report=raw_report,
        )
