#Goal: stop hard-coding things like sandbox root, allowed extensions, max bytes, artifact dirs.
#We’ll add profiles (dev, prod, etc.), support env-var overrides, and expose config tools.

# config.py
from __future__ import annotations
from typing import Dict, Any, Optional
import os, json
from mcp.server.fastmcp import FastMCP
from tools.tool_utils import unwrap_tool_result

# Defaults per profile (edit to your taste)
DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "dev": {
        "sandbox_root": "./sandbox",
        "artifacts_dir": "./artifacts",
        "log_glob": "*.log",
        "read.max_bytes": 512,
        "track.max_bytes": 65536,
        "alerts.pattern": "ERROR",
        "alerts.threshold": 1,
        "alerts.comparator": ">=",
            },
    "customerA": {
        "sandbox_root": "./sandboxA",
        "artifacts_dir": "./artifactsA",
        "log_glob": "*customerA*.log",
        "read.max_bytes": 1024,
        "track.max_bytes": 131072,
        "alerts.pattern": "CRITICAL",
        "alerts.threshold": 2,
        "alerts.comparator": ">=",
                },
}

# Environment overrides (take precedence over profile values)
ENV_MAP = {
    "sandbox_root": "MCP_SANDBOX_ROOT",
    "artifacts_dir": "MCP_ARTIFACTS_DIR",
    "kv_db": "MCP_KV_DB",
}

CONFIG_KEY = "config:active"           # where we persist the active profile name
CONFIG_DATA_KEY = "config:data"        # optional persisted “current config” snapshot

async def _kv_get(mcp: FastMCP, key: str) -> Optional[Any]:
    res = unwrap_tool_result(await mcp.call_tool("kv_get", {"key": key}))
    if isinstance(res, dict) and res.get("found"):
        return res["value"]
    return None

async def _kv_set(mcp: FastMCP, key: str, value: Any) -> None:
    # Store objects as JSON strings for broad compatibility
    await mcp.call_tool("kv_set", {"key": key, "value": json.dumps(value, {"ensure_ascii":False}) if isinstance(value, (dict, list)) else value})

def _apply_env(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(cfg)
    for k, env_name in ENV_MAP.items():
        v = os.environ.get(env_name)
        if v:
            out[k] = v
    return out

def _merge(base: Dict[str, Any], overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not overrides: return dict(base)
    out = dict(base); out.update(overrides); return out

def _profile_or_default(name: Optional[str]) -> str:
    return name if name in DEFAULT_PROFILES else "dev"

async def load_config(mcp: FastMCP) -> Dict[str, Any]:
    """Load active profile, merge defaults + persisted overrides, then apply env."""
    active = await _kv_get(mcp, CONFIG_KEY)
    profile = _profile_or_default(active if isinstance(active, str) else None)

    # Try a persisted snapshot; if none, fall back to defaults
    snap = await _kv_get(mcp, CONFIG_DATA_KEY)
    if isinstance(snap, str):
        try: snap = json.loads(snap)
        except Exception: snap = None

    base = DEFAULT_PROFILES[profile]
    cfg = _merge(base, snap if isinstance(snap, dict) else None)
    return _apply_env(cfg) | {"profile": profile}

async def save_config(mcp: FastMCP, cfg: Dict[str, Any]) -> None:
    # remove computed fields before saving
    c = dict(cfg); c.pop("profile", None)
    await _kv_set(mcp, CONFIG_DATA_KEY, c)

async def set_active_profile(mcp: FastMCP, name: str) -> Dict[str, Any]:
    prof = _profile_or_default(name)
    await _kv_set(mcp, CONFIG_KEY, prof)
    # wipe snapshot so we get clean defaults next load
    await _kv_set(mcp, CONFIG_DATA_KEY, "{}")
    return {"ok": True, "profile": prof}

def register_config_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def config_get() -> Dict[str, Any]:
        """Return the current effective config (after env overrides)."""
        cfg = await load_config(mcp); return {"ok": True, "config": cfg}

    @mcp.tool()
    async def config_set(values: Dict[str, Any]) -> Dict[str, Any]:
        """Persist overrides for the active profile (e.g., {"read.max_bytes": 2048})."""
        # Load current overrides (persisted snapshot), not the full config
        snap = await _kv_get(mcp, CONFIG_DATA_KEY)
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except Exception:
                snap = {}
        elif not isinstance(snap, dict):
            snap = {}
        # Update only the overrides
        snap.update(values)
        # Remove computed fields if present
        snap.pop("profile", None)
        await save_config(mcp, snap)
        return {"ok": True, "config": await load_config(mcp)}

    @mcp.tool()
    async def config_profile_use(name: str) -> Dict[str, Any]:
        """Switch active profile (e.g., 'dev', 'customerA')."""
        out = await set_active_profile(mcp, name)
        out["config"] = await load_config(mcp)
        return out

    @mcp.tool()
    async def config_profiles() -> Dict[str, Any]:
        """List available default profiles."""
        return {"ok": True, "profiles": list(DEFAULT_PROFILES.keys()), "defaults": DEFAULT_PROFILES}
