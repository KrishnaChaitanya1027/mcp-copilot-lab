# dynamic_plans.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP
from tools.tool_utils import unwrap_tool_result

def _fmt(value: Any, ctx: Dict[str, Any]) -> Any:
    """
    Tiny templating: if 'value' is a str, do .format(**ctx).
    Lets you use {last.file}, {files[0]}, {kv_key}, etc.
    """
    if isinstance(value, str):
        # nested context support: expose 'last' and all step ids
        return value.format(**ctx)
    return value

def _format_args(args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _fmt(v, ctx) for k, v in (args or {}).items()}

def register_dynamic_plan_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def run_plan(steps: List[Dict[str, Any]],
                      save_key: Optional[str] = None,
                      context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a dynamic plan.
        steps: list of { id?: str, tool: str, args: dict (templated strings ok) }
        Example step:
          {"id":"s1","tool":"search_files","args":{"pattern":"{pattern}"}}

        Context variables available to templates:
          - {last.X}: fields from the last step's result
          - {<step_id>.X}: fields from a named step's result
          - Any top-level key you pass in step args (e.g., pattern="*.log")
          - You can carry forward your own variables by writing them to KV first.

        If save_key is set, the full execution result is saved to KV (key=save_key).
        Returns: {"ok": bool, "results": [{"id":..., "tool":..., "result":{...}}, ...]}
        """
        results: List[Dict[str, Any]] = []
        ctx: Dict[str, Any] = {}  # dynamic template context
        if context:
            ctx.update(context)

        for idx, step in enumerate(steps):
            tool = step.get("tool")
            if not tool:
                return {"ok": False, "error": f"step {idx} missing 'tool'"}

            step_id = step.get("id") or f"step{idx+1}"
            fmt_args = _format_args(step.get("args", {}), {**ctx, "last": ctx.get("last", {})})

            # Call the tool via FastMCP
            res = unwrap_tool_result(await mcp.call_tool(tool, fmt_args))

            # Track results & update context
            results.append({"id": step_id, "tool": tool, "args": fmt_args, "result": res})
            ctx[step_id] = res
            ctx["last"] = res  # convenient rolling alias

            # Convenient shorthands for common shapes
            # If the tool returns {files:[...]}, expose {files} directly
            if isinstance(res, dict):
                for k, v in res.items():
                    # don't clobber step ids
                    if k not in ctx:
                        ctx[k] = v

        out = {"ok": True, "results": results}

        if save_key:
            await mcp.call_tool("kv_set", {"key": save_key, "value": str(out)})  # serialize simple
            out["saved_to"] = save_key

        return out
