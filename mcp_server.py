from __future__ import annotations
import os, glob, ast, operator as op, datetime, zoneinfo
from typing import List
from mcp.server.fastmcp import FastMCP
import tools
from tools import config

#Server
mcp = FastMCP("Krishnas-MCP-Server")

#Sandbox Limits (AKA) Guardrails
SAFE_ROOT = os.path.abspath("/home/devil/Desktop/my-mcp-project/artifacts")
MAX_TOOL_CALLS_PER_RUN = 6
ALLOW_EXTS = {".log", ".txt"}
MAX_FILE_BYTES = 4096

# ---- Safe math (no eval) ----
ALLOWED_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.Pow: op.pow, ast.Mod: op.mod, ast.USub: lambda x: -x,
}
def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp):
        return ALLOWED_OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp):
        return ALLOWED_OPS[type(node.op)](_eval(node.left), _eval(node.right))
    raise ValueError("Unsupported expression")
def safe_eval_expr(expr: str) -> float:
    return _eval(ast.parse(expr, mode="eval").body)

# ---- Tools ----

@mcp.tool()
def say_hello(name: str = "friend") -> dict:
    return {"ok": True, "message": f"Hello, {name}!"}

@mcp.tool()
def get_time(timezone: str = "UTC") -> dict:
    try:
        now = datetime.datetime.now(zoneinfo.ZoneInfo(timezone))
        return {"ok": True, "timezone": timezone, "time": now.strftime("%Y-%m-%d %H:%M:%S %Z")}
    except Exception:
        return {"ok": False, "error": "Invalid timezone", "timezone": timezone}

@mcp.tool()
def math_eval(expr: str) -> dict:
    try:
        val = safe_eval_expr(expr)
        return {"ok": True, "expr": expr, "value": val}
    except Exception:
        return {"ok": False, "error": "Invalid/unsafe expression", "expr": expr}

@mcp.tool()
def search_files(pattern: str, max_results: int = 50) -> dict:
    """
    Returns {"ok": True, "files": ["rel/path1", ...], "pattern": pattern}
    """
    base = SAFE_ROOT
    os.makedirs(base, exist_ok=True)

    if not any(sep in pattern for sep in ("/", os.sep)):
        pattern = f"**/{pattern}"
    if os.path.isabs(pattern):
        return {"ok": False, "error": "Pattern must be relative", "pattern": pattern}

    glob_pattern = os.path.join(base, pattern)
    results: List[str] = []
    for path in glob.iglob(glob_pattern, recursive=True):
        p = os.path.abspath(path)
        if not (p == base or p.startswith(base + os.sep)):
            continue
        if os.path.isfile(p):
            results.append(os.path.relpath(p, base))
        if len(results) >= max_results:
            break

    return {"ok": True, "files": results, "pattern": pattern}

@mcp.tool()
def read_file(path: str, max_bytes: int = 512) -> dict:
    """
    Returns {"ok": True, "path": rel, "text": "...", "bytes": n, "truncated": bool}
    """
    base = SAFE_ROOT
    if os.path.isabs(path):
        return {"ok": False, "error": "Path must be relative", "path": path}
    abs_path = os.path.abspath(os.path.join(base, path))
    if not (abs_path == base or abs_path.startswith(base + os.sep)):
        return {"ok": False, "error": "Access denied outside sandbox", "path": path}
    if not os.path.isfile(abs_path):
        return {"ok": False, "error": "File not found", "path": path}

    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in ALLOW_EXTS:
        return {"ok": False, "error": "Extension not allowed", "path": path, "ext": ext}

    n = min(int(max_bytes), MAX_FILE_BYTES)
    with open(abs_path, "rb") as f:
        data = f.read(n)
    is_trunc = os.path.getsize(abs_path) > n
    text = (data + (b"" if not is_trunc else b"...(truncated)")).decode("utf-8", errors="replace")
    return {"ok": True, "path": path, "text": text, "bytes": len(data), "truncated": is_trunc}

@mcp.tool()
def summarize_logs(pattern: str, max_files: int = 5, max_bytes_per_file: int = 512) -> dict:
    """
    Returns {"ok": True, "summaries": [ {path, lines, first, last}, ... ], "pattern": pattern}
    """
    base = SAFE_ROOT
    os.makedirs(base, exist_ok=True)

    if not any(sep in pattern for sep in ("/", os.sep)):
        pattern = f"**/{pattern}"
    if os.path.isabs(pattern):
        return {"ok": False, "error": "Pattern must be relative", "pattern": pattern}

    max_bpf = min(int(max_bytes_per_file), 2048)
    items = []

    for path in glob.iglob(os.path.join(base, pattern), recursive=True):
        p = os.path.abspath(path)
        if not (p == base or p.startswith(base + os.sep)):
            continue
        if not os.path.isfile(p):
            continue
        if len(items) >= max_files:
            break

        ext = os.path.splitext(p)[1].lower()
        if ext not in ALLOW_EXTS:
            continue

        try:
            with open(p, "rb") as f:
                data = f.read(max_bpf)
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            first = lines[0] if lines else ""
            last = lines[-1] if lines else ""
            total = sum(1 for _ in open(p, "rb"))
            relp = os.path.relpath(p, base)
            items.append({"path": relp, "lines": total, "first": first[:200], "last": last[:200]})
        except Exception as e:
            relp = os.path.relpath(p, base)
            items.append({"path": relp, "error": str(e)})

    return {"ok": True, "summaries": items, "pattern": pattern}


# ---- Import additional tools instead of defining each tool here.----


from tools.kv_store import register_kv_tools
register_kv_tools(mcp)

from tools import config
config.register_config_tools(mcp)

from tools.dynamic_plans import register_dynamic_plan_tools
register_dynamic_plan_tools(mcp)

from tools.plans import register_plan_tools
register_plan_tools(mcp)

from tools.artifacts import register_artifact_tools
register_artifact_tools(mcp)

from tools.progress import register_progress_tools
register_progress_tools(mcp)

from tools.watchers import register_watch_tools
register_watch_tools(mcp)

from tools.alerts import register_alert_tools
register_alert_tools(mcp)

from tools.templates import register_template_tools
register_template_tools(mcp)





# ---- Entry point ----
if __name__ == "__main__":
    # The SDK handles the transport and JSON-RPC for you.
    mcp.run()
