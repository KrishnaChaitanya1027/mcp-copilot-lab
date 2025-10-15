"""Minimal secret storage helpers backed by the existing KV store."""

from __future__ import annotations

from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

from tools.kv_store import _LOCK, _load_db, _save_db

_PREFIX = "secret:"


def _key(name: str) -> str:
    """Flatten caller names into the namespaced KV key."""
    return f"{_PREFIX}{name}"


def _list_secret_names(db: Dict[str, str], prefix: str = "") -> List[str]:
    """Extract secret names without revealing stored values."""
    names: List[str] = []
    for key in db:
        if not key.startswith(_PREFIX):
            continue
        name = key[len(_PREFIX):]
        if prefix and not name.startswith(prefix):
            continue
        names.append(name)
    names.sort()
    return names


def register_secret_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def secret_set(name: str, value: str) -> Dict[str, Any]:
        """Persist a secret value; overwrites existing entries."""
        if not name:
            return {"ok": False, "error": "name is required"}

        with _LOCK:
            db = _load_db()
            db[_key(name)] = value
            _save_db(db)

        return {"ok": True, "name": name}

    @mcp.tool()
    async def secret_get(name: str) -> Dict[str, Any]:
        """Fetch a secret value without leaking it to metadata."""
        if not name:
            return {"ok": False, "error": "name is required"}

        with _LOCK:
            db = _load_db()
            raw = db.get(_key(name))

        if raw is None:
            return {"ok": False, "error": "secret not found", "name": name}

        return {"ok": True, "name": name, "value": raw}

    @mcp.tool()
    async def secret_list(prefix: str = "") -> Dict[str, Any]:
        """List stored secret names only."""
        with _LOCK:
            db = _load_db()
            names = _list_secret_names(db, prefix.strip())

        return {"ok": True, "count": len(names), "names": names}
