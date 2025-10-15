# tools/watch_dir.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Union
from mcp.server.fastmcp import FastMCP
from pathlib import Path
import json, asyncio
from tools import config

def _default_steps_for(path: str, max_bytes: int) -> List[Dict[str, Any]]:
    """Simple per-file plan: read -> save -> pin path in KV."""
    fname = f"watch_{Path(path).name}.txt"
    return [
        {"id":"read","tool":"read_file","args":{"path": path, "max_bytes": max_bytes}},
        {"id":"save","tool":"save_text","args":{"filename": fname, "text":"{read.text}", "overwrite": True}},
        {"id":"pin","tool":"kv_set","args":{"key":"artifact:last_watch", "value":"{save.path}"}}
    ]

async def _list_files(mcp: FastMCP, glob_pattern: str) -> List[str]:
    """Returns relative paths (as your search_files does)."""
    res = await mcp.call_tool("search_files", {"pattern": glob_pattern})
    if isinstance(res, dict) and res.get("ok"):
        return list(res.get("files") or [])
    # Try to handle legacy list returns
    if isinstance(res, list):
        for part in res:
            if isinstance(part, dict) and isinstance(part.get("json"), dict):
                return part["json"].get("files", [])
    return []

def register_watch_dir_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def watch_dir_once(
        glob: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        steps_json: Optional[Union[str, List[Dict[str, Any]]]] = None,
        max_files: int = 50,
        read_max_bytes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Enumerate files by glob and call watch_file_once per file.
        If steps/steps_json omitted, uses a default plan (read->save->pin).
        Returns: {ok, glob, total, changed:[...], unchanged:[...]}
        """
        cfg = await config.load_config(mcp)
        glob_pat = glob or cfg.get("log_glob", "*.log")
        files = await _list_files(mcp, glob_pat)
        files = files[: max(0, int(max_files))]

        # choose plan
        maxb = int(read_max_bytes or cfg.get("read.max_bytes", 2048))
        parsed_steps: Optional[List[Dict[str, Any]]] = None
        if steps is None and steps_json is not None:
            if isinstance(steps_json, str):
                try:
                    parsed_steps = json.loads(steps_json)
                except Exception as e:
                    return {"ok": False, "error": f"steps_json invalid: {e}"}
            elif isinstance(steps_json, list):
                parsed_steps = steps_json
            else:
                return {"ok": False, "error": "steps_json must be str or list"}

        changed, unchanged = [], []
        for rel in files:
            # default plan uses the literal file path
            per_file_steps = steps or parsed_steps or _default_steps_for(rel, maxb)
            res = await mcp.call_tool("watch_file_once", {"path": rel, "steps": per_file_steps})
            if isinstance(res, dict) and res.get("ok"):
                (changed if res.get("changed") else unchanged).append({
                    "path": res.get("path"),
                    "fingerprint": res.get("fingerprint"),
                    "plan_ran": bool(res.get("changed"))
                })
            else:
                unchanged.append({"path": rel, "error": "watch_file_once failed", "detail": res})

        # Record a slim audit trail for downstream incident reviews.
        try:
            await mcp.call_tool("audit_append", {"event": {
                "tool": "watch_dir_once",
                "actor": "system",
                "glob": glob_pat,
                "changed_count": len(changed),
            }})
        except Exception:
            pass

        return {
            "ok": True,
            "glob": glob_pat,
            "total": len(files),
            "changed": changed,
            "unchanged": unchanged
        }

    @mcp.tool()
    async def watch_dir_poll(
        glob: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        steps_json: Optional[Union[str, List[Dict[str, Any]]]] = None,
        interval_sec: int = 5,
        iterations: int = 5,
        max_files: int = 50,
        read_max_bytes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Poll all files in a glob for N iterations. On each pass, run watch_file_once per file.
        Bounded loop (no background daemon).
        """
        cfg = await config.load_config(mcp)
        glob_pat = glob or cfg.get("log_glob", "*.log")
        files = await _list_files(mcp, glob_pat)
        files = files[: max(0, int(max_files))]

        # plan choice
        maxb = int(read_max_bytes or cfg.get("read.max_bytes", 2048))
        parsed_steps: Optional[List[Dict[str, Any]]] = None
        if steps is None and steps_json is not None:
            if isinstance(steps_json, str):
                try:
                    parsed_steps = json.loads(steps_json)
                except Exception as e:
                    return {"ok": False, "error": f"steps_json invalid: {e}"}
            elif isinstance(steps_json, list):
                parsed_steps = steps_json
            else:
                return {"ok": False, "error": "steps_json must be str or list"}

        history: List[Dict[str, Any]] = []
        iters = max(1, int(iterations))
        gap = max(1, int(interval_sec))

        for i in range(iters):
            pass_result = {"iter": i + 1, "files": []}
            for rel in files:
                per_file_steps = steps or parsed_steps or _default_steps_for(rel, maxb)
                res = await mcp.call_tool("watch_file_once", {"path": rel, "steps": per_file_steps})
                if isinstance(res, dict):
                    pass_result["files"].append({
                        "path": res.get("path"),
                        "changed": res.get("changed"),
                        "fingerprint": res.get("fingerprint")
                    })
                else:
                    pass_result["files"].append({"path": rel, "error": "watch_file_once failed"})
            history.append(pass_result)
            if i < iters - 1:
                await asyncio.sleep(gap)

        return {"ok": True, "glob": glob_pat, "iterations": iters, "interval_sec": gap, "history": history}
