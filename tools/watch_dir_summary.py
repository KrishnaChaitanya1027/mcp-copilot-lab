from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP


def _collect_paths(items: Any) -> List[str]:
    if not isinstance(items, list):
        return []
    paths: List[str] = []
    for entry in items:
        if isinstance(entry, dict):
            path = entry.get("path")
            if isinstance(path, str):
                paths.append(path)
    return paths


def _unwrap_result(payload: Any) -> Optional[Dict[str, Any]]:
    if isinstance(payload, dict):
        inner = payload.get("result")
        if isinstance(inner, dict):
            return inner
        return payload
    if isinstance(payload, (list, tuple)):
        for part in payload:
            result = _unwrap_result(part)
            if result is not None:
                return result
    return None


def register_watch_dir_summary_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def watch_dir_summary(glob: str = "logs/*.log") -> Dict[str, Any]:
        """
        Run watch_dir_once for the provided glob and capture a short summary.
        Saves a dir_watch_summary.txt artifact containing: date, glob, changed files, unchanged count.
        """
        raw_watch_res = await mcp.call_tool("watch_dir_once", {"glob": glob})
        watch_res = _unwrap_result(raw_watch_res)
        if not watch_res or not watch_res.get("ok"):
            return {
                "ok": False,
                "error": "watch_dir_once failed",
                "details": raw_watch_res,
                "glob": glob,
            }

        changed_paths = _collect_paths(watch_res.get("changed"))
        unchanged_count = len(watch_res.get("unchanged") or [])

        timestamp = datetime.now(timezone.utc).isoformat()
        lines = [
            f"Date: {timestamp}",
            f"Glob: {glob}",
            f"Changed files ({len(changed_paths)}):",
        ]

        if changed_paths:
            lines.extend(f"- {path}" for path in changed_paths)
        else:
            lines.append("- none")

        lines.append(f"Unchanged count: {unchanged_count}")
        summary_text = "\n".join(lines) + "\n"

        raw_save_res = await mcp.call_tool(
            "save_text",
            {"filename": "dir_watch_summary.txt", "text": summary_text, "overwrite": True},
        )
        save_res = _unwrap_result(raw_save_res)
        if not save_res or not save_res.get("ok"):
            return {
                "ok": False,
                "error": "Failed to save artifact",
                "details": raw_save_res,
                "glob": glob,
            }

        return {
            "ok": True,
            "glob": glob,
            "changed_count": len(changed_paths),
            "artifact": {"path": save_res.get("path")},
        }
