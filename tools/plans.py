"""
plans.py — Multi-step workflow (plan) tool for MCP Copilot Lab

Now that you have a KV store (memory), let’s teach your MCP server how to run multi-step workflows.
Instead of the model manually calling each tool, you can define a plan (sequence of steps).
A plan is like a recipe: step → step → step.

Each step calls one of your existing tools.

The result of one step can be passed to the next.

Example use-case: Search logs → Read them → Summarize → Save to KV store.
"""

# modules/plans.py
from mcp.server.fastmcp import FastMCP
from tools.tool_utils import unwrap_tool_result

def register_plan_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def plan_summarize_logs(file_pattern: str, key: str) -> dict:
        """
        Chain: search_files -> read_file -> summarize_logs -> kv_set
        Saves the summary into KV under 'key'.
        """
        # step 1: search
        search = unwrap_tool_result(await mcp.call_tool("search_files", {"pattern":file_pattern}))
        files = search.get("files") if isinstance(search, dict) else None
        if not files:
            return {"ok": False, "reason": "no files found"}

        target = files[0]  # pick first match

        # step 2: read
        content = unwrap_tool_result(await mcp.call_tool("read_file", {"path": target}))
        content_text = content.get("text", "") if isinstance(content, dict) else str(content)

        # step 3: summarize
        summary = unwrap_tool_result(await mcp.call_tool("summarize_logs", {"text": content_text}))
        summary_text = summary.get("summary") if isinstance(summary, dict) else str(summary)

        # step 4: save
        await mcp.call_tool("kv_set", {"key": "summary:" + key, "value": summary_text})

        return {
            "ok": True,
            "file": target,
            "summary_key": "summary:" + key,
            "preview": summary_text[:120] + "..."
        }
