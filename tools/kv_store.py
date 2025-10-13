#kv_store.py — Goal: 
#Give your MCP server a simple memory you can read/write/list/delete, stored in a JSON file.

from __future__ import annotations
from typing import Optional, Dict
from pathlib import Path
import json, threading
from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "kv.json"
_LOCK = threading.RLock()

def _load_db() -> Dict[str, str]:
    if not DB_PATH.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        DB_PATH.write_text("{}", encoding="utf-8")
        return {}
    try:
        txt = DB_PATH.read_text(encoding="utf-8")
        return json.loads(txt or "{}")
    except json.JSONDecodeError:
        # auto-recover if file got corrupted
        backup = DB_PATH.with_suffix(".corrupt.json")
        DB_PATH.rename(backup)
        DB_PATH.write_text("{}", encoding="utf-8")
        return {}

def _save_db(db: Dict[str, str]) -> None:
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DB_PATH)

def register_kv_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def kv_set(key: str, value: str) -> dict:
        """Store a string value under 'key'. 
        Returns {"ok": true, "key": ..., "len": ...}."""
        if not key:
            raise ValueError("key must be non-empty")
        with _LOCK:
            db = _load_db()
            db[key] = value
            _save_db(db)
        return {"ok": True, "key": key, "len": len(value)}

    @mcp.tool()
    async def kv_get(key: str, default: Optional[str] = None) -> dict:
        """Get value for 'key'. Returns {"found": bool, "value": str|None}."""
        if not key:
            raise ValueError("key must be non-empty")
        with _LOCK:
            db = _load_db()
            if key in db:
                return {"found": True, "value": db[key]}
            return {"found": False, "value": default}

    @mcp.tool()
    async def kv_del(key: str) -> dict:
        """Delete 'key' if present. Returns {"deleted": bool}."""
        if not key:
            raise ValueError("key must be non-empty")
        with _LOCK:
            db = _load_db()
            existed = key in db
            if existed:
                del db[key]
                _save_db(db)
        return {"deleted": existed}

    @mcp.tool()
    async def kv_list(prefix: Optional[str] = None) -> dict:
        """List keys, optionally filtered by prefix. Returns {"count": int, "keys": [..]}."""
        with _LOCK:
            db = _load_db()
            keys = sorted(k for k in db if not prefix or k.startswith(prefix))
        return {"count": len(keys), "keys": keys}

