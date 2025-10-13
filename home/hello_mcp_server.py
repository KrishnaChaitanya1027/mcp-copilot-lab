#!/usr/bin/env python3
# Minimal MCP stdio server with 6 tools:
# say_hello, get_time, math_eval, search_files, read_file, summarize_logs
import sys, json, datetime, zoneinfo, ast, operator as op, os, glob

# -------- guardrails --------
MAX_TOOL_CALLS_PER_RUN = 6
ALLOW_EXTS = {".log", ".txt"}
MAX_FILE_BYTES = 4096

# -------- sandbox root --------
SAFE_ROOT = os.path.abspath("/home/devil/Desktop/my-mcp-project/sandbox")
os.makedirs(SAFE_ROOT, exist_ok=True)

# -------- safe math --------
ALLOWED_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.Pow: op.pow, ast.USub: lambda x: -x, ast.Mod: op.mod,
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

# -------- helpers --------
def log(msg: str):
    print(msg, file=sys.stderr, flush=True)

def respond(_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": _id, "result": result}) + "\n")
    sys.stdout.flush()

# -------- main loop --------
tool_calls_so_far = 0  # per-process simple counter

for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")

    if method == "tools/list":
        respond(req["id"], {
            "tools": [
                {
                    "name": "say_hello",
                    "description": "Greets a person",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"]
                    }
                },
                {
                    "name": "get_time",
                    "description": "Current local time for a timezone (IANA).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"timezone": {"type": "string"}},
                        "required": ["timezone"]
                    }
                },
                {
                    "name": "math_eval",
                    "description": "Evaluate an arithmetic expression (+ - * / ** %).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"expr": {"type": "string"}},
                        "required": ["expr"]
                    }
                },
                {
                    "name": "search_files",
                    "description": "List files under sandbox matching a glob (e.g., **/*.log).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Glob like *.txt or **/*.log"},
                            "max_results": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}
                        },
                        "required": ["pattern"]
                    }
                },
                {
                    "name": "read_file",
                    "description": "Read first N bytes of a file under sandbox (UTF-8).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 4096, "default": 512}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "summarize_logs",
                    "description": "Summarize up to N matching log files (line count + first/last line).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Glob like **/*.log"},
                            "max_files": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                            "max_bytes_per_file": {"type": "integer", "minimum": 64, "maximum": 2048, "default": 512}
                        },
                        "required": ["pattern"]
                    }
                }
            ]
        })
        continue

    elif method == "tools/call":
        # guardrail
        tool_calls_so_far += 1
        if tool_calls_so_far > MAX_TOOL_CALLS_PER_RUN:
            respond(req["id"], {"content": [{"type": "text", "text": "Tool-call limit exceeded"}], "isError": True})
            continue

        params = req.get("params", {}) or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        log(f"RX tools/call name={name} args={args}")

        if name == "say_hello":
            who = args.get("name", "friend")
            respond(req["id"], {"content": [{"type": "text", "text": f"Hello, {who}!"}], "isError": False})

        elif name == "get_time":
            tz = args.get("timezone", "UTC")
            try:
                now = datetime.datetime.now(zoneinfo.ZoneInfo(tz))
                text = now.strftime("%Y-%m-%d %H:%M:%S %Z")
                respond(req["id"], {"content": [{"type": "text", "text": text}], "isError": False})
            except Exception:
                respond(req["id"], {"content": [{"type": "text", "text": "Invalid timezone"}], "isError": True})

        elif name == "math_eval":
            expr = str(args.get("expr", "")).strip()
            try:
                val = safe_eval_expr(expr)
                respond(req["id"], {"content": [{"type": "text", "text": str(val)}], "isError": False})
            except Exception:
                respond(req["id"], {"content": [{"type": "text", "text": "Invalid/unsafe expression"}], "isError": True})

        elif name == "search_files":
            pattern = str(args.get("pattern", "")).strip()
            max_results = int(args.get("max_results", 50))
            base = SAFE_ROOT
            os.makedirs(base, exist_ok=True)

            # Default to recursive if no dir separators
            if not any(sep in pattern for sep in ("/", os.sep)):
                pattern = f"**/{pattern}"

            if os.path.isabs(pattern):
                respond(req["id"], {"content": [{"type": "text", "text": "Pattern must be relative."}], "isError": True})
            else:
                glob_pattern = os.path.join(base, pattern)
                results = []
                for path in glob.iglob(glob_pattern, recursive=True):
                    p = os.path.abspath(path)
                    if not (p == base or p.startswith(base + os.sep)):
                        continue
                    if os.path.isfile(p):
                        results.append(os.path.relpath(p, base))
                    if len(results) >= max_results:
                        break
                text = "\n".join(results) if results else "(no matches)"
                respond(req["id"], {"content": [{"type": "text", "text": text}], "isError": False})

        elif name == "read_file":
            rel = str(args.get("path", "")).strip()
            max_bytes = min(int(args.get("max_bytes", 512)), MAX_FILE_BYTES)
            base = SAFE_ROOT
            os.makedirs(base, exist_ok=True)

            if os.path.isabs(rel):
                respond(req["id"], {"content": [{"type": "text", "text": "Path must be relative."}], "isError": True})
            else:
                abs_path = os.path.abspath(os.path.join(base, rel))
                if not (abs_path == base or abs_path.startswith(base + os.sep)):
                    respond(req["id"], {"content": [{"type": "text", "text": "Access denied outside sandbox."}], "isError": True})
                elif not os.path.isfile(abs_path):
                    respond(req["id"], {"content": [{"type": "text", "text": "File not found."}], "isError": True})
                else:
                    ext = os.path.splitext(abs_path)[1].lower()
                    if ext not in ALLOW_EXTS:
                        log(f"DENY read_file path={rel} reason=ext_not_allowed")
                        respond(req["id"], {"content": [{"type": "text", "text": "Extension not allowed"}], "isError": True})
                    else:
                        with open(abs_path, "rb") as f:
                            data = f.read(max_bytes)
                        suffix = b"" if os.path.getsize(abs_path) <= max_bytes else b"...(truncated)"
                        text = (data + suffix).decode("utf-8", errors="replace")
                        respond(req["id"], {"content": [{"type": "text", "text": text}], "isError": False})

        elif name == "summarize_logs":
            pattern = str(args.get("pattern", "")).strip()
            max_files = int(args.get("max_files", 5))
            max_bpf = min(int(args.get("max_bytes_per_file", 512)), 2048)

            base = SAFE_ROOT
            os.makedirs(base, exist_ok=True)

            if not any(sep in pattern for sep in ("/", os.sep)):
                pattern = f"**/{pattern}"
            if os.path.isabs(pattern):
                respond(req["id"], {"content": [{"type": "text", "text": "Pattern must be relative."}], "isError": True})
            else:
                glob_pattern = os.path.join(base, pattern)
                summaries = []
                for path in glob.iglob(glob_pattern, recursive=True):
                    p = os.path.abspath(path)
                    if not (p == base or p.startswith(base + os.sep)):
                        continue
                    if not os.path.isfile(p):
                        continue
                    if len(summaries) >= max_files:
                        break

                    relp = os.path.relpath(p, base)
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
                        summaries.append(f"{relp} — lines:{total} — first:{first[:80]} — last:{last[:80]}")
                    except Exception as e:
                        summaries.append(f"{relp} — error reading file: {e}")

                out = "\n".join(summaries) if summaries else "(no matches)"
                respond(req["id"], {"content": [{"type": "text", "text": out}], "isError": False})

        else:
            respond(req["id"], {"content": [{"type": "text", "text": "unknown tool"}], "isError": True})

    else:
        # Unknown method
        respond(req.get("id"), {"content": [{"type": "text", "text": "unknown method"}], "isError": True})
