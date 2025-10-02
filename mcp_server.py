from __future__ import annotations
import os, glob, ast, operator as op, datetime, zoneinfo
from typing import List
from mcp.server.fastmcp import FastMCP

#Server
mcp = FastMCP("Krishnas-MCP-Server")

#Sandbox Limits (AKA) Guardrails
SAFE_ROOT = os.path.abspath("/home/devil/Desktop/my-mcp-project/sandbox")
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
def say_hello(name: str = "friend") -> str:
    """Greets a person."""
    return f"Hello, {name}!"

@mcp.tool()
def get_time(timezone: str = "UTC") -> str:
    """Current local time for a timezone (IANA)."""
    try:
        now = datetime.datetime.now(zoneinfo.ZoneInfo(timezone))
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return "Invalid timezone"

@mcp.tool()
def math_eval(expr: str) -> str:
    """Evaluate a simple arithmetic expression ( + - * / ** % )."""
    try:
        return str(safe_eval_expr(expr))
    except Exception:
        return "Invalid/unsafe expression"

@mcp.tool()
def search_files(pattern: str, max_results: int = 50) -> str:
    """List files under the sandbox matching a glob (e.g., '*.log' or '**/*.txt')."""
    base = SAFE_ROOT
    os.makedirs(base, exist_ok=True)

    # If no directory separator, default to recursive
    if not any(sep in pattern for sep in ("/", os.sep)):
        pattern = f"**/{pattern}"

    if os.path.isabs(pattern):
        return "Pattern must be relative."

    glob_pattern = os.path.join(base, pattern)
    results: List[str] = []
    for path in glob.iglob(glob_pattern, recursive=True):
        p = os.path.abspath(path)
        # stay inside SAFE_ROOT
        if not (p == base or p.startswith(base + os.sep)):
            continue
        if os.path.isfile(p):
            results.append(os.path.relpath(p, base))
        if len(results) >= max_results:
            break

    return "\n".join(results) if results else "(no matches)"

@mcp.tool()
def read_file(path: str, max_bytes: int = 512) -> str:
    """Read first N bytes of a file under the sandbox (UTF-8, errors replaced)."""
    base = SAFE_ROOT
    if os.path.isabs(path):
        return "Path must be relative."
    abs_path = os.path.abspath(os.path.join(base, path))
    if not (abs_path == base or abs_path.startswith(base + os.sep)):
        return "Access denied outside sandbox."
    if not os.path.isfile(abs_path):
        return "File not found."

    # extension allow-list
    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in ALLOW_EXTS:
        return "Extension not allowed"

    n = min(int(max_bytes), MAX_FILE_BYTES)
    with open(abs_path, "rb") as f:
        data = f.read(n)
    suffix = b"" if os.path.getsize(abs_path) <= n else b"...(truncated)"
    return (data + suffix).decode("utf-8", errors="replace")

@mcp.tool()
def summarize_logs(pattern: str, max_files: int = 5, max_bytes_per_file: int = 512) -> str:
    """Summarize up to N matching log files (line count + first/last line)."""
    base = SAFE_ROOT
    os.makedirs(base, exist_ok=True)

    if not any(sep in pattern for sep in ("/", os.sep)):
        pattern = f"**/{pattern}"
    if os.path.isabs(pattern):
        return "Pattern must be relative."

    max_bpf = min(int(max_bytes_per_file), 2048)

    glob_pattern = os.path.join(base, pattern)
    summaries: List[str] = []

    for path in glob.iglob(glob_pattern, recursive=True):
        p = os.path.abspath(path)
        if not (p == base or p.startswith(base + os.sep)):
            continue
        if not os.path.isfile(p):
            continue
        if len(summaries) >= max_files:
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
            # quick count (avoid loading entire file into memory)
            total = sum(1 for _ in open(p, "rb"))
            relp = os.path.relpath(p, base)
            summaries.append(f"{relp} — lines:{total} — first:{first[:80]} — last:{last[:80]}")
        except Exception as e:
            relp = os.path.relpath(p, base)
            summaries.append(f"{relp} — error reading file: {e}")

    return "\n".join(summaries) if summaries else "(no matches)"

# ---- Entry point ----
if __name__ == "__main__":
    # The SDK handles the transport and JSON-RPC for you.
    mcp.run()
