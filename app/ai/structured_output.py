"""Structured output parsing and validation utilities."""

from __future__ import annotations

import json
import re
from typing import Any, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def clean_markdown_fences(content: str) -> str:
    """Strip markdown code fence wrappers (```json ... ``` or ```xml ... ```)."""
    text = content.strip()
    # Match ```json ... ``` or ```xml ... ``` or bare ``` ... ```
    match = re.match(r"^```(?:json|xml|svg)?\s*\n?(.*?)\n?```$", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def parse_json_safely(content: str) -> dict[str, Any]:
    """Parse JSON text safely, handling potential markdown code blocks or stray characters."""
    cleaned = clean_markdown_fences(content)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to locate first '{' and last '}'
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            substring = cleaned[start : end + 1]
            return json.loads(substring)
        # Try array '[' and ']'
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            substring = cleaned[start : end + 1]
            return json.loads(substring)
        raise


def parse_structured_output(content: str, model_cls: Type[T]) -> T:
    """Parse content into a specified Pydantic model class."""
    data = parse_json_safely(content)
    return model_cls.model_validate(data)
