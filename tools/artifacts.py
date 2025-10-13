#Let my server sace tool outputs to disk (txt/json/bin) and return short previews for chat.

from __future__ import annotations
from typing import Optional, Dict, Any, List
from pathlib import Path
import os, glob, json, base64
from mcp.server.fastmcp import FastMCP

ART_DIR = Path(os.environ.get("MCP_ARTIFACTS_DIR", "./artifacts")).resolve()
ART_DIR.mkdir(parents=True, exist_ok=True)

def _safe_name(name: str) -> str:
    if not name or any(c in name for c in r'\/:*?"<>|'):
        raise ValueError("Invalid filename")
    return name

def _preview_text(text: str, limit: int = 300) -> str:
    if len(text) <= limit: return text
    head = text[:limit//2].rstrip()
    tail = text[-limit//2:].lstrip()
    return head + "\n...\n" + tail

def register_artifact_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    def save_text(filename: str, text: str, overwrite: bool = False) -> Dict[str, Any]:
        """Save UTF-8 text and return a small preview."""
        fn = _safe_name(filename)
        path = ART_DIR / fn
        if path.exists() and not overwrite:
            return {"ok": False, "reason": "exists", "path": str(path)}
        path.write_text(text, encoding="utf-8")
        return {"ok": True, "path": str(path), "size": len(text), "preview": _preview_text(text)}

    @mcp.tool()
    def save_json(filename: str, obj: Dict[str, Any], overwrite: bool = False, indent: int = 2) -> Dict[str, Any]:
        """Save a JSON object and return a preview (pretty-printed)."""
        fn = _safe_name(filename)
        if not fn.lower().endswith(".json"):
            fn += ".json"
        path = ART_DIR / fn
        if path.exists() and not overwrite:
            return {"ok": False, "reason": "exists", "path": str(path)}
        text = json.dumps(obj, ensure_ascii=False, indent=indent)
        path.write_text(text, encoding="utf-8")
        return {"ok": True, "path": str(path), "size": len(text), "preview": _preview_text(text)}

    @mcp.tool()
    def save_bytes(filename: str, b64: str, overwrite: bool = False) -> Dict[str, Any]:
        """Save arbitrary bytes given as base64 (e.g., images, logs, zips)."""
        fn = _safe_name(filename)
        path = ART_DIR / fn
        if path.exists() and not overwrite:
            return {"ok": False, "reason": "exists", "path": str(path)}
        data = base64.b64decode(b64)
        path.write_bytes(data)
        return {"ok": True, "path": str(path), "size": len(data)}

    @mcp.tool()
    def read_artifact(filename: str, as_text: bool = True) -> Dict[str, Any]:
        """Read an artifact. When as_text=False, returns base64."""
        fn = _safe_name(filename)
        path = ART_DIR / fn
        if not path.exists():
            return {"ok": False, "reason": "not_found", "path": str(path)}
        if as_text:
            text = path.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "path": str(path), "text": text, "preview": _preview_text(text)}
        else:
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            return {"ok": True, "path": str(path), "b64": b64, "size": path.stat().st_size}

    @mcp.tool()
    def list_artifacts(suffix: Optional[str] = None) -> Dict[str, Any]:
        """List saved files (optionally filter by suffix e.g. '.json')."""
        files: List[str] = []
        for p in ART_DIR.iterdir():
            if p.is_file() and (not suffix or p.name.endswith(suffix)):
                files.append(p.name)
        files.sort()
        return {"ok": True, "count": len(files), "files": files, "dir": str(ART_DIR)}

    @mcp.tool()
    def delete_artifact(filename: str) -> Dict[str, Any]:
        """Delete a file by name."""
        fn = _safe_name(filename)
        path = ART_DIR / fn
        if not path.exists():
            return {"ok": False, "reason": "not_found", "path": str(path)}
        path.unlink()
        return {"ok": True, "path": str(path)}