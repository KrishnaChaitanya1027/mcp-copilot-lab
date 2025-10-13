# watchers.py Goal: run a plan only when a file changes

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pathlib import Path
import os, json, hashlib, asyncio
from mcp.server.fastmcp import FastMCP
from tools import config
from tools.tool_utils import unwrap_tool_result

#Default plan steps if the user does not input using "steps= [...]"
def _default_steps_for(path: str, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    filename = f"watch_{Path(path).name}.txt"  # safe filename, no slashes
    maxb = int(cfg.get("read.max_bytes", 2048))
    return [
        {"id":"read","tool":"read_file","args":{"path": path, "max_bytes": maxb}},
        {"id":"save","tool":"save_text","args":{"filename": filename, "text":"{read.text}", "overwrite": True}},
        {"id":"pin","tool":"kv_set","args":{"key":"artifact:last_watch","value":"{save.path}"}}
    ]

def _fingerprint(path: str, quick_bytes: int = 4096) -> Dict[str, Any]:
    """Fast change detector: size + mtime + quick sha1 (head+tail)."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {"exists": False}
    size = p.stat().st_size
    mtime = int(p.stat().st_mtime_ns)
    h = hashlib.sha1()
    with p.open("rb") as f:
        head = f.read(quick_bytes)
        h.update(head)
        if size > quick_bytes:
            f.seek(max(0, size - quick_bytes))
            tail = f.read(quick_bytes)
            h.update(tail)
    return {"exists": True, "size": size, "mtime": mtime, "qsha1": h.hexdigest()}

def _state_key(path: str) -> str:
    return f"watch:{str(Path(path).resolve())}"

async def _kv_get(mcp: FastMCP, key: str) -> Optional[Dict[str, Any]]:
    res = unwrap_tool_result(await mcp.call_tool("kv_get", {"key":key}))
    if not (isinstance(res, dict) and res.get("found")):
        return None
    val = res.get("value")
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return None
    return None

async def _kv_set(mcp: FastMCP, key: str, value: Dict[str, Any]) -> None:
    # Store JSON as string for compatibility
    await mcp.call_tool("kv_set", {"key":key, "value":json.dumps(value, ensure_ascii=False)})

def register_watch_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def watch_file_once(path: str,
                              steps: Optional[List[Dict[str, Any]]] = None,
                              context: Optional[Dict[str, Any]] = None,
                              save_state: bool = True) -> Dict[str, Any]:
        """
        Check if 'path' changed since last run. If changed, run 'run_plan' with given steps.
        - steps: same format you pass to run_plan (dynamic plan).
        - context: extra template vars available to your steps (e.g., {"path":"logs/app.log"}).
        Returns:
          {"changed": bool, "fingerprint": {...}, "plan": {... or None}}
        """
        p = str(Path(path).resolve())
        fp = _fingerprint(p)
        state_key = _state_key(p)
        prev = await _kv_get(mcp, state_key)

        # Use default steps if not provided
        if steps is None:
            steps = _default_steps_for(p, getattr(config, 'WATCH_DEFAULTS', {}))

        changed = (prev != fp)
        plan_out = None
        if changed and fp.get("exists"):
            # Inject {path} and any provided context for templating in run_plan
            ctx = {"path": p}
            if context:
                ctx.update(context)

            # Attach these context vars into first step args if you rely on them
            # (Your steps can reference {path} or any ctx value directly.)
            plan_out = unwrap_tool_result(
                await mcp.call_tool("run_plan", {"steps":steps, "save_key":None})
            )

            if save_state:
                await _kv_set(mcp, state_key, fp)

        return {"ok": True, "path": p, "changed": changed, "fingerprint": fp, "plan": plan_out}

    @mcp.tool()
    async def watch_file_poll(path: str,
                              steps: List[Dict[str, Any]],
                              interval_sec: int = 5,
                              iterations: int = 5) -> Dict[str, Any]:
        """
        Poll 'path' a few times. On each detected change, run the plan once.
        This is a bounded loop (no background daemon).
        Returns a compact run log.
        """
        p = str(Path(path).resolve())
        runs: List[Dict[str, Any]] = []

        for i in range(max(1, int(iterations))):
            res = await watch_file_once(path=p, steps=steps, context={"path": p})
            runs.append({"iter": i + 1, "changed": res["changed"], "fingerprint": res["fingerprint"]})
            if i < iterations - 1:
                await asyncio.sleep(max(1, int(interval_sec)))

        return {"ok": True, "path": p, "iterations": iterations, "interval_sec": interval_sec, "runs": runs}
