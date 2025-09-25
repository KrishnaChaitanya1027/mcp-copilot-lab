import os, json, subprocess, sys, uuid
from dotenv import load_dotenv # type: ignore
from openai import OpenAI # type: ignore

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- MCP stdio client (minimal JSON-RPC) ---
class MCP:
    def __init__(self, cmd, args=None, env=None):
        self.p = subprocess.Popen(
            [cmd] + (args or []),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env or os.environ.copy()
        )
        self._id = 0

    def _rpc(self, method, params=None):
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
        # normalize tool result to text
        text = ""
        if isinstance(res, dict) and isinstance(res.get("content"), list):
            parts = [c.get("text","") for c in res["content"] if isinstance(c, dict) and c.get("type")=="text"]
            text = "\n".join([p for p in parts if p])
        return text or json.dumps(res)

# --- Convert MCP tools -> OpenAI tool schema ---
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

def main():
    # 1) start MCP server (your hello script)
    mcp = MCP(cmd=sys.executable, args=["hello_mcp_server.py"])

    # 2) discover tools & prep OpenAI schema
    mcp_tools = mcp.list_tools()
    tools_schema = to_openai_tools_schema(mcp_tools)

    # 3) ask the model
    messages = [
        {"role":"system","content":"You can call MCP tools. Prefer tools over guessing, and explain briefly. Use ** for exponent, not ^ "},
        {"role":"user","content":"Greet Krishna, tell me the time in Toronto, and list app.log files under the sandbox."}
    ]

    # first completion
    resp = client.chat.completions.create(model=MODEL, messages=messages, tools=tools_schema, tool_choice="auto")
    def print_usage(resp):
            u = getattr(resp, "usage", None)
            if u:
                print(f"[usage] prompt={u.prompt_tokens} out={u.completion_tokens} total={u.total_tokens}")
    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None)

    # 4) if tool calls, execute them and loop once
    if tool_calls:
        # append assistant stub (required by OpenAI schema)
        messages.append({"role":"assistant","content":msg.content or "", "tool_calls":[tc.model_dump() for tc in tool_calls]})
        for tc in tool_calls:
            fn = tc.function
            result_text = mcp.call_tool(fn.name, json.loads(fn.arguments or "{}"))
            messages.append({"role":"tool","tool_call_id":tc.id,"content":result_text})

        # ask again with tool results
        resp2 = client.chat.completions.create(model=MODEL, messages=messages)
        def print_usage(resp):
            u = getattr(resp, "usage", None)
            if u:
                print(f"[usage] prompt={u.prompt_tokens} out={u.completion_tokens} total={u.total_tokens}")

        final = resp2.choices[0].message.content
    else:
        final = msg.content

    print("\nASSISTANT:", final)

if __name__ == "__main__":
    main()
