#!/usr/bin/env python3
import os, sys, json, subprocess, signal, time
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI, RateLimitError

# ---------- config ----------
SYSTEM_PROMPT = "You are a helpful assistant. Prefer MCP tools over guessing. Be concise."
MODEL_DEFAULT = "gpt-4o-mini"
MCP_CMD = sys.executable           # python
MCP_ARGS = ["hello_mcp_server.py"] # your server script
TOOL_CALL_MAX = 6                  # safety cap per user turn

# ---------- utils ----------
def print_usage(resp):
    u = getattr(resp, "usage", None)
    if u:
        print(f"[usage] prompt={u.prompt_tokens} out={u.completion_tokens} total={u.total_tokens}")

def chat_with_retry(client, **kwargs):
    delay = 1.5
    for _ in range(5):
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError as e:
            ra = getattr(e, "response", None)
            retry_after = None
            if ra and hasattr(ra, "headers"):
                retry_after = ra.headers.get("retry-after")
            time.sleep(float(retry_after or delay))
            delay = min(delay * 2, 30)
    raise

# ---------- minimal MCP stdio client ----------
class MCP:
    def __init__(self, cmd, args=None, env=None):
        self.cmd = cmd
        self.args = args or []
        self.env = env or os.environ.copy()
        self.p = None
        self._id = 0

    def start(self):
        if self.p and self.p.poll() is None:
            return
        self.p = subprocess.Popen([self.cmd] + self.args,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, env=self.env)

    def stop(self):
        if self.p and self.p.poll() is None:
            try:
                self.p.terminate()
                self.p.wait(timeout=2)
            except Exception:
                self.p.kill()

    def _rpc(self, method, params=None):
        if not self.p or self.p.poll() is not None:
            raise RuntimeError("MCP server not running")
        self._id += 1
        req = {"jsonrpc":"2.0","id":self._id,"method":method}
        if params is not None:
            req["params"] = params
        self.p.stdin.write(json.dumps(req) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed")
        resp = json.loads(line)
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]

    def list_tools(self):
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, name, arguments):
        res = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        # normalize result to text
        text = ""
        if isinstance(res, dict) and isinstance(res.get("content"), list):
            parts = [c.get("text","") for c in res["content"]
                     if isinstance(c, dict) and c.get("type")=="text"]
            text = "\n".join([p for p in parts if p])
        return text or json.dumps(res)

def to_openai_tools_schema(mcp_tools):
    tools = []
    for t in mcp_tools:
        params = t.get("inputSchema") or {"type":"object","properties":{}}
        if isinstance(params, dict) and params.get("$schema"):
            params = {k:v for k,v in params.items() if k != "$schema"}
        tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description",""),
                "parameters": params
            }
        })
    return tools

# ---------- main REPL ----------
def main():
    # env & clients
    load_dotenv(find_dotenv(), override=True)
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    model = (os.getenv("OPENAI_MODEL") or MODEL_DEFAULT).strip()
    if not api_key:
        print("Error: OPENAI_API_KEY is missing. Add it to .env", file=sys.stderr)
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    # start MCP
    mcp = MCP(MCP_CMD, MCP_ARGS)
    mcp.start()
    mcp_tools = mcp.list_tools()
    tools_schema = to_openai_tools_schema(mcp_tools)
    print(f"[mcp] attached {len(mcp_tools)} tool(s): " + ", ".join(t["name"] for t in mcp_tools))

    # chat state
    messages = [{"role":"system","content":SYSTEM_PROMPT}]
    print("CLI chat ready. Type your message. Commands: /reset, /reload, /exit")

    # graceful exit on Ctrl+C
    signal.signal(signal.SIGINT, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))

    while True:
        try:
            user = input("\nYou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[bye]")
            break

        # commands
        if user in ("/exit", "/quit"):
            break
        if user == "/reset":
            messages = [{"role":"system","content":SYSTEM_PROMPT}]
            print("[state] conversation reset")
            continue
        if user == "/reload":
            # restart mcp & refresh tools
            mcp.stop(); mcp.start()
            mcp_tools = mcp.list_tools()
            tools_schema = to_openai_tools_schema(mcp_tools)
            print(f"[mcp] reloaded {len(mcp_tools)} tool(s)")
            continue
        if not user:
            continue

        messages.append({"role":"user","content":user})

        # first completion (let the model decide tools)
        resp = chat_with_retry(client,
            model=model, messages=messages,
            tools=tools_schema, tool_choice="auto"
        )
        print_usage(resp)
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        # if tool calls: execute (bounded) and send results back
        tool_call_count = 0
        if tool_calls:
            # append assistant stub with tool_calls (OpenAI schema requirement)
            messages.append({
                "role":"assistant",
                "content": msg.content or "",
                "tool_calls":[tc.model_dump() for tc in tool_calls]
            })
            for tc in tool_calls:
                if tool_call_count >= TOOL_CALL_MAX:
                    messages.append({"role":"tool","tool_call_id":tc.id,
                                     "content":"Tool-call limit exceeded"})
                    continue
                fn = tc.function
                args = {}
                try:
                    args = json.loads(fn.arguments or "{}")
                except Exception:
                    pass
                result_text = mcp.call_tool(fn.name, args)
                messages.append({"role":"tool","tool_call_id":tc.id,"content":result_text})
                tool_call_count += 1

            # final completion with tool results
            resp2 = chat_with_retry(client, model=model, messages=messages)
            print_usage(resp2)
            final = resp2.choices[0].message.content
        else:
            final = msg.content

        print(f"Assistant > {final}")

    mcp.stop()

if __name__ == "__main__":
    main()
