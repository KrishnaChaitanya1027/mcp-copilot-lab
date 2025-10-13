# MCP Copilot Lab

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/packaging-uv-brightgreen)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Minimal **Model Context Protocol (MCP)** lab that shows how to take a server from “toy demo” to a modular, stateful copilot. The repository now ships opinionated guardrails, persistent memory, artifact management, alerting, and both CLI and TUI chat clients.

- See `RECENT_FIXES.txt` for a running log of the latest improvements.

---

## Components

- `mcp_server.py`: Primary server with structured JSON responses, guardrails, and dynamically registered tool packs.
- `hello_mcp_server.py`: Minimal JSON-RPC sample that stays close to the SDK tutorial.
- `cli_chat.py`: Thin CLI wrapper that connects to the MCP server and prints tool traces/token usage.
- `tui_chat.py`: Experimental Textual UI with streaming responses, slash commands, and a `--self-test` harness.
- `tools/`: Modular tool packs (`kv_store`, `config`, `artifacts`, `plans`, `dynamic_plans`, `progress`, `watchers`, `alerts`, `templates`, etc.).
- `artifacts/`, `data/`, `logs/`: Sample state used by the automation features (safe to delete or regenerate).

---

## Quickstart

1. **Install dependencies**
   ```bash
   uv venv
   uv pip install openai python-dotenv textual rich
   ```
2. **Configure OpenAI (or your MCP-friendly model)**
   ```bash
   echo "OPENAI_API_KEY=sk-..." > .env
   echo "OPENAI_MODEL=gpt-4o-mini" >> .env
   ```
3. **Start a server**
   ```bash
   python mcp_server.py       # full feature set
   # or
   python hello_mcp_server.py # minimal tutorial version
   ```
4. **Chat from the CLI**
   ```bash
   uv run python cli_chat.py
   ```
5. **Try the TUI (optional)**
   ```bash
   python tui_chat.py            # launch interface
   python tui_chat.py --self-test  # run smoke tests without UI
   ```

Tool results and token usage are shown inline. The CLI intentionally suppresses assistant prose; open the TUI or instrument the client if you want rendered responses.

---

## Tooling Highlights

**Guardrails & Configuration**
- All built-in tools return `{"ok": bool, ...}` payloads for predictable error handling.
- Sandbox root defaults to `./artifacts` and enforces extension/size limits (`.log`, `.txt`).
- Profile-aware config (`tools/config.py`) lets you flip between `dev`, `customerA`, or your own profile with environment overrides.

**Persistent Memory & Artifacts**
- `tools/kv_store.py` gives the copilot a simple JSON-backed memory with list/get/set/delete helpers.
- `tools/artifacts.py` persists text/JSON/binary outputs to disk and returns friendly previews.
- `tools/tool_utils.py` standardises how nested tools unwrap FastMCP responses.

**Automation & Ops**
- `tools/plans.py` and `tools/dynamic_plans.py` orchestrate multi-step workflows with templated arguments.
- `tools/progress.py` tracks log offsets so you only read new bytes and can summarise them automatically.
- `tools/watchers.py` executes plans when file fingerprints change; `tools/alerts.py` fires when regex thresholds are met.
- `tools.templates.py` turns KV/config/artifact data into incident updates or customer-ready notes.

---

## Tool Catalogue

Core tools exposed by `mcp_server.py`:

- `say_hello`, `get_time`, `math_eval`
- `search_files`, `read_file`, `summarize_logs`
- `kv_*` (set/get/del/list)
- `config_*` (profiles, overrides)
- `save_text`, `save_json`, `save_bytes`, `list_artifacts`, `read_artifact`, `delete_artifact`
- `plan_summarize_logs`, `run_plan`
- `watch_file_once`, `watch_file_poll`
- `track_read`, `track_read_and_summarize`, `offset_*`
- `alert_count_text`, `alert_track_and_save`, `alert_run_plan_if`
- `tpl_*` helpers plus `gen_incident_update`

Each tool returns structured JSON so you can chain them from the model safely.

---

## Storage Layout

- `artifacts/`: Sandbox root and default artifact directory. Everything written via artifact tools lives here.
- `data/kv.json`: Backing store for the KV tools (auto-creates, recovers from corruption).
- `logs/chat.log`: Sample log stream for experimentation.
- `sandbox/kv.json`: Legacy sandbox state kept for backward compatibility; new features use `data/`.

Feel free to clear these directories to reset the lab.

---

## Development Notes

- Unit tests: `uv pip install pytest` then `uv run pytest -q`.
- When extending with your own tools:
  1. Add a module under `tools/` that defines `register_*_tools(mcp)`.
  2. Import and call it from `mcp_server.py`.
  3. Reload your client; FastMCP re-advertises the new tool schema automatically.
- For a quick tour of what changed recently, open `RECENT_FIXES.txt`.

---

## Troubleshooting

- Hangs until Ctrl+C? Make sure each tool calls `respond(...)` (FastMCP emits a helpful stderr trace).
- `400 invalid tool name`: tool ids must match `[a-zA-Z0-9_-]+`.
- No files found? Use recursive globs like `**/*.log`.
- TUI not rendering? Install `textual>=0.52` and ensure your terminal supports rich markup.
