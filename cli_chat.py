#!/usr/bin/env python3
"""
cli_chat.py — OpenAI ↔ MCP bridge chat (REPL)

- Spawns your MCP server from MCP_SERVER env (stdio transport)
- Performs MCP initialize/initialized handshake (SDK servers)
- Falls back gracefully for legacy JSON servers (no handshake)
- Lists MCP tools and exposes them to OpenAI tool-calling
- REPL with /help /tools /reset /reload /exit
- Logs conversation to logs/chat.log

.env required:
  OPENAI_API_KEY=sk-...
  OPENAI_MODEL=gpt-4o-mini
  MCP_SERVER=python mcp_server.py          # or: uv run mcp run mcp_server.py

Run:
  uv run python cli_chat.py
"""

from __future__ import annotations
import os
import sys
import json
import time
import shlex
import pathlib
import subprocess
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

# ---------- config ----------
load_dotenv()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MCP_CMD = os.getenv("MCP_SERVER", "python mcp_server.py")
LOG_DIR = pathlib.Path("logs"); LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "chat.log"


# ---------- small logger ----------
def log(line: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {line}\n")


# ---------- MCP stdio bridge ----------
class MCPProc:
    """
    Minimal JSON-RPC over stdio bridge with MCP handshake support.

    Compatible with:
      - MCP SDK servers (require initialize/initialized)
      - legacy JSON servers (no handshake)
    """
    def __init__(self, cmd: str) -> None:
        self.cmd = cmd
        self.p: subprocess.Popen[str] | None = None
        self._id = 0
        self.initialized = False

    # ---- process lifecycle ----
    def start(self) -> None:
        if self.p and self.p.poll() is None:
            return
        args = shlex.split(self.cmd)
        self.p = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
        log(f"MCP started: {self.cmd}")
        # Attempt MCP handshake (safe no-op for legacy servers)
        self._try_handshake()

    def stop(self) -> None:
        if self.p and self.p.poll() is None:
            try:
                self.p.terminate()
            except Exception:
                pass
        self.p = None
        self.initialized = False
        log("MCP stopped")

    # ---- low-level json-rpc helpers ----
    def _write(self, obj: dict, expect_response: bool) -> dict | None:
        if not self.p or self.p.poll() is not None:
            raise RuntimeError("MCP server not running")
        line = json.dumps(obj) + "\n"
        assert self.p.stdin is not None
        self.p.stdin.write(line)
        self.p.stdin.flush()

        if not expect_response:
            return None
        assert self.p.stdout is not None
        self.notify("notifications/initialized")
        
        resp_line = self.p.stdout.readline()
        if not resp_line:
            raise RuntimeError("MCP server closed")
        try:
            return json.loads(resp_line)
        except Exception as e:
            raise RuntimeError(f"Invalid JSON from server: {resp_line!r}") from e

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params:
            req["params"] = params
        return self._write(req, expect_response=True)  # dict (result or error)

    def notify(self, method: str, params: dict | None = None) -> None:
        req = {"jsonrpc": "2.0", "method": method}
        if params:
            req["params"] = params
        self._write(req, expect_response=False)

    # ---- MCP handshake for SDK servers ----
    def _try_handshake(self) -> None:
        """
        Perform MCP initialize/initialized. If the server is legacy (no handshake),
        ignore errors and continue.
        """
        if self.initialized:
            return
        try:
            init_resp = self.call("initialize", {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "openai-bridge-cli", "version": "0.1.0"},
                # Minimal client capabilities (empty objects are OK)
                "capabilities": {
                    "roots": {},          # host can advertise roots, we accept
                    "prompts": {},        # we can accept prompts if server provides them
                    "tools": {},          # we use tools
                    "resources": {}       # we can accept resources
                }
            })
            # Expect {"jsonrpc":"2.0","id":...,"result":{...}}
            if isinstance(init_resp, dict) and "result" in init_resp:
                # Correct notification name per MCP SDK
                self.notify("notifications/initialized", {"someField": "someValue"})
                self.initialized = True
                log("MCP handshake complete")
            else:
                raise RuntimeError(f"initialize returned no result: {init_resp}")
        except Exception as e:
            # Legacy server (no handshake) or non-compliant response: continue gracefully
            log(f"MCP handshake skipped/failed (legacy server?): {e}")

    # ---- convenience wrappers ----
    def list_tools(self) -> list[dict]:
        resp = self.call("tools/list")
        if "error" in resp:
            raise RuntimeError(f"tools/list error: {resp['error']}")
        result = resp.get("result")
        if not result or "tools" not in result:
            raise KeyError(f"tools/list missing 'result.tools': {resp}")
        return result["tools"]

    def call_tool(self, name: str, arguments: dict | None = None) -> str:
        resp = self.call("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in resp:
            # Return a texty error so the model can read it
            return f"[mcp-error] {resp['error']}"
        result = resp.get("result", {})
        items = result.get("content") or []
        if items and isinstance(items, list) and isinstance(items[0], dict) and "text" in items[0]:
            return str(items[0]["text"])
        # Fallback: dump whatever came back
        return json.dumps(result)


def mcp_tools_to_openai(tools_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert MCP tool schemas to OpenAI function tool schemas.
    """
    out: List[Dict[str, Any]] = []
    for t in tools_list:
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}})
            }
        })
    return out


# ---------- Chat REPL ----------
def main() -> None:
    # OpenAI client
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Start MCP and load tools
    mcp = MCPProc(MCP_CMD)

    def refresh_tools() -> tuple[list[dict], list[dict]]:
        mcp.start()  # starts proc and performs handshake if supported
        tools = mcp.list_tools()
        return tools, mcp_tools_to_openai(tools)

    try:
        tools_list, oa_tools = refresh_tools()
    except Exception as e:
        print(f"[error] Failed to start/list MCP tools: {e}")
        log(f"ERROR starting MCP/tools: {e}")
        return

    print("CLI Chat ready. Commands: /help /tools /reset /reload /exit")
    messages: List[Dict[str, Any]] = []
    log("=== session start ===")

    def pretty_tools() -> str:
        return "\n".join(f"- {t['name']}: {t.get('description','')}" for t in tools_list)

    while True:
        try:
            user = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user:
            continue

        # Slash commands
        if user in ("/exit", "/quit"):
            break
        if user == "/help":
            print("Commands:")
            print("  /tools   - list available tools from MCP server")
            print("  /reload  - restart MCP server & reload tools")
            print("  /reset   - clear chat history")
            print("  /exit    - quit")
            continue
        if user == "/tools":
            print(pretty_tools())
            continue
        if user == "/reset":
            messages.clear()
            print("[ok] chat history cleared")
            continue
        if user == "/reload":
            try:
                mcp.stop()
                tools_list, oa_tools = refresh_tools()
                print("[ok] MCP reloaded. Tools:")
                print(pretty_tools())
            except Exception as e:
                print(f"[error] reload failed: {e}")
                log(f"ERROR reload: {e}")
            continue

        # Regular user message
        messages.append({"role": "user", "content": user})
        log(f"USER: {user}")

        # Tool-call loop with safety cap
        for _ in range(16):
            try:
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=oa_tools,
                    tool_choice="auto"
                )
                usage = getattr(resp, "usage", None)
                if usage:
                    print(f"[usage] prompt={usage.prompt_tokens} completion={usage.completion_tokens} total={usage.total_tokens}")
                    log(f"USAGE: prompt={usage.prompt_tokens} completion={usage.completion_tokens} total={usage.total_tokens}")

            except Exception as e:
                print(f"[error] OpenAI call failed: {e}")
                log(f"ERROR openai: {e}")
                break

            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            # Final answer

            if not tool_calls:
                # Only log, do not print assistant answer
                answer = msg.content or ""
                # print(f"\nAssistant: {answer}\n")  # <--- commented out, restore to show assistant output
                log(f"ASSIST: {answer}")
                messages.append({
                    "role": "assistant",
                    "content": answer
                })
                break

                # Add assistant message with tool_calls before tool messages
            messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in tool_calls]
                })
            # Execute tool calls via MCP
            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}

                try:
                    text = mcp.call_tool(name, args)
                    print(f"[tool:{name}] {text[:600]}")
                    log(f"TOOL {name}({args}) -> {text[:2000]}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": text
                    })
                except Exception as e:
                    err = f"Tool '{name}' failed: {e}"
                    print(f"[error] {err}")
                    log(f"ERROR tool {name}: {e}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": err
                    })
                    # Let the model decide how to proceed with the error message

    # graceful exit
    log("=== session end ===")
    try:
        mcp.stop()
    except Exception:
        pass
    print("bye 👋")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye 👋")
