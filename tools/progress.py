#Goal: process big/ever-growing files incrementally (resume where you left).
#We’ll store offsets in KV and read only the new bytes.

# progress.py (replace file)
from __future__ import annotations
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from pathlib import Path
import os, json
from tools import config
from tools.tool_utils import unwrap_tool_result

def _key_for(path: str) -> str:
    return f"offset:{str(Path(path).resolve())}"

async def _kv_get_json(mcp: FastMCP, key: str) -> Optional[Dict[str, Any]]:
    res = unwrap_tool_result(await mcp.call_tool("kv_get", {"key": key}))
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

async def _kv_set_json(mcp: FastMCP, key: str, obj: Dict[str, Any]) -> None:
    await mcp.call_tool("kv_set", {"key": key, "value": json.dumps(obj, ensure_ascii=False)})

def register_progress_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def offset_get(path: str) -> Dict[str, Any]:
        """Return last saved offset for 'path'."""
        k = _key_for(path)
        state = await _kv_get_json(mcp, k)
        if state:
            return {"ok": True, "path": path, "offset": int(state.get("offset", 0)), "size": state.get("size")}
        return {"ok": True, "path": path, "offset": 0, "size": None}

    @mcp.tool()
    async def offset_set(path: str, offset: int) -> Dict[str, Any]:
        """Force-set the saved offset for 'path'."""
        p = str(Path(path).resolve())
        size = os.path.getsize(p) if os.path.exists(p) else 0
        state = {"offset": int(offset), "size": size}
        await _kv_set_json(mcp, _key_for(path), state)
        return {"ok": True, "path": path, "offset": int(offset), "size": size}

    @mcp.tool()
    async def offset_reset(path: str) -> Dict[str, Any]:
        """Reset offset to 0."""
        return await offset_set(path=path, offset=0) 

    @mcp.tool()
    async def track_read(path: str, max_bytes: int = 65536, encoding: str = "utf-8") -> Dict[str, Any]:
        # Resolve path: absolute = as-is; relative = under sandbox_root
        cfg = await config.load_config(mcp)
        base = os.path.abspath(cfg.get("sandbox_root", "./sandbox"))

        # If caller gives "logs/app.log", read sandbox/logs/app.log
        p = Path(path)
        abs_path = p if p.is_absolute() else Path(base) / p
        abs_path = abs_path.resolve()

        if not abs_path.exists():
            return {"ok": False, "reason": "not_found", "path": str(abs_path)}

        size_now = abs_path.stat().st_size
        prev = await _kv_get_json(mcp, _key_for(str(abs_path)))
        start = int(prev.get("offset", 0)) if prev else 0
        size_prev = int(prev.get("size", 0)) if prev else 0

        if size_now < size_prev or start > size_now:
            start = 0

        read_upto = min(max_bytes, max(0, size_now - start))
        with open(p, "rb") as f:
            f.seek(start)
            data = f.read(read_upto)

        try:
            chunk = data.decode(encoding, errors="replace")
        except LookupError:
            chunk = data.decode("utf-8", errors="replace")

        end = start + len(data)
        eof = (end >= size_now)

        await _kv_set_json(mcp, _key_for(path), {"offset": end, "size": size_now})

        return {
            "ok": True,
            "path": p,
            "start": start,
            "end": end,
            "eof": eof,
            "chunk": chunk,
            "bytes_read": len(data),
            "file_size": size_now
        }

    @mcp.tool()
    async def track_read_and_summarize(path: str, key: Optional[str] = None, max_bytes: int = 65536) -> Dict[str, Any]:
        """track_read -> summarize_logs -> save_text; caches paths/summaries in KV if 'key' set."""
        tr = await track_read(path=path, max_bytes=max_bytes)  # local await
        if not tr.get("ok"):
            return tr
        if tr["bytes_read"] == 0:
            return {"ok": True, "path": tr["path"], "start": tr["start"], "end": tr["end"], "eof": tr["eof"], "note": "no new bytes"}

        summ = unwrap_tool_result(await mcp.call_tool("summarize_logs", {"text":tr["chunk"]}))
        summary = summ.get("summary", "") if isinstance(summ, dict) else str(summ)

        fname = f"summary_{Path(tr['path']).name}_{tr['start']}_{tr['end']}.txt"
        saved = unwrap_tool_result(
            await mcp.call_tool("save_text", {"filename":fname, "text":summary, "overwrite":True})
        )

        if key:
            saved_path = saved.get("path", "") if isinstance(saved, dict) else ""
            await mcp.call_tool("kv_set", {"key": f"artifact:last_summary:{key}", "value": saved_path})
            await mcp.call_tool("kv_set", {"key": f"summary:last_chunk:{key}", "value": summary})


        return {
            "ok": True,
            "path": tr["path"],
            "start": tr["start"],
            "end": tr["end"],
            "eof": tr["eof"],
            "bytes_read": tr["bytes_read"],
            "artifact_path": saved.get("path") if isinstance(saved, dict) else None,
            "preview": ((saved.get("preview") or "") if isinstance(saved, dict) else "")[:160]
        }
