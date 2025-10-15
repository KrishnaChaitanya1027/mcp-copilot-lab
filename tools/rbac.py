"""Role-based session helpers and tools."""
from __future__ import annotations

from typing import Iterable, Optional, Set

from mcp.server.fastmcp import FastMCP

from tools.tool_utils import unwrap_tool_result

SESSION_ROLE_KEY = "session:role"
VALID_ROLES: Set[str] = {"owner", "reader"}


async def get_current_role(mcp: FastMCP) -> Optional[str]:
    """Fetch the current session role from KV."""
    res = unwrap_tool_result(
        await mcp.call_tool("kv_get", {"key": SESSION_ROLE_KEY})
    )
    if isinstance(res, dict) and res.get("found"):
        value = res.get("value")
        if isinstance(value, str):
            return value
    return None


async def ensure_role(mcp: FastMCP, allowed_roles: Iterable[str]) -> str:
    """
    Ensure the current session role is allowed.

    Returns the role on success, raises PermissionError otherwise.
    """
    allowed = set(allowed_roles)
    if not allowed:
        raise ValueError("allowed_roles must contain at least one role")

    current = await get_current_role(mcp)
    if current is None:
        raise PermissionError(f"session role not set; allowed roles: {sorted(allowed)}")
    if current not in allowed:
        raise PermissionError(
            f"required role in {sorted(allowed)}, current role is {current!r}"
        )
    return current


def register_rbac_tools(mcp: FastMCP) -> None:
    """Register role management tools."""

    @mcp.tool()
    async def role_set(role: str) -> dict:
        """
        Set the current session role.

        Stores the normalized role (lowercase) in KV under session:role.
        """
        normalized = role.strip().lower()
        if not normalized:
            raise ValueError("role must be non-empty")
        if normalized not in VALID_ROLES:
            raise ValueError(f"role must be one of: {sorted(VALID_ROLES)}")

        res = unwrap_tool_result(
            await mcp.call_tool(
                "kv_set", {"key": SESSION_ROLE_KEY, "value": normalized}
            )
        )
        ok = isinstance(res, dict) and res.get("ok", False)
        if not ok:
            raise RuntimeError("kv_set failed to store the role")

        return {"ok": True, "role": normalized}

    @mcp.tool()
    async def role_get() -> dict:
        """
        Get the current session role.

        Returns {"ok": true, "role": str | None, "found": bool}.
        """
        current = await get_current_role(mcp)
        return {"ok": True, "role": current, "found": current is not None}

