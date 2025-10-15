"""Append-only action audit log helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from tools.artifacts import ART_DIR

_LOG_NAME = "action_log.jsonl"


def register_audit_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def audit_append(event: Dict[str, Any]) -> Dict[str, Any]:
        """Append a structured event to the shared action log."""
        payload = event or {}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "event must be a dictionary"}

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": payload.get("tool"),
            "actor": payload.get("actor"),
            "event": payload,
        }

        path = ART_DIR / _LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

        return {"ok": True, "path": str(path)}
