"""Shared helpers for working with FastMCP tool responses."""
from __future__ import annotations

from typing import Any, Sequence
import json

from mcp.types import ContentBlock, TextContent


def unwrap_tool_result(result: Any) -> Any:
    """Normalize FastMCP tool responses back into plain Python objects.

    FastMCP now returns unstructured results as sequences of ``ContentBlock``
    instances (or a ``(content, structured)`` tuple when structured output is
    enabled). This helper restores the original Python object when the
    content is JSON, otherwise it returns the best-effort string payload.
    """
    # Structured output wins if present.
    if isinstance(result, tuple) and len(result) == 2:
        _, structured = result
        if isinstance(structured, dict):
            return structured
        # Fall back to the unstructured part if structured data is not a dict.
        result = result[0]

    if isinstance(result, dict):
        return result

    if isinstance(result, Sequence):
        text_chunks: list[str] = []
        for block in result:
            text = _extract_text(block)
            if text is not None:
                text_chunks.append(text)

        combined = "".join(text_chunks).strip()
        if not combined:
            return {}
        try:
            return json.loads(combined)
        except json.JSONDecodeError:
            return combined

    return result


def _extract_text(block: ContentBlock | Any) -> str | None:
    """Extract text from a ``ContentBlock`` or compatible object."""
    if isinstance(block, TextContent):
        return block.text

    # Fall back to model_dump if available (Pydantic models).
    model_dump = getattr(block, "model_dump", None)
    if callable(model_dump):
        text = model_dump(mode="python").get("text")  # type: ignore[arg-type]
        if isinstance(text, str):
            return text

    # As a last resort, treat plain strings as text.
    if isinstance(block, str):
        return block

    return None
