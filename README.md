# MCP Copilot Lab

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/packaging-uv-brightgreen)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Opinionated **Model Context Protocol (MCP)** sandbox that demonstrates how to graduate a JSON-RPC tutorial server into a modular, stateful copilot equipped with guardrails, memory, automation, and a CLI chat surface.

See `RECENT_FIXES.txt` for the latest incremental changes.

---

## Why This Lab Exists

- Prove out patterns for running an MCP copilot in persistent, stateful environments.
- Ship ready-to-use tooling (kv storage, artifact handling, automation hooks) you can reuse.
- Offer a concise playground for experimenting with server-side guardrails and tool orchestration.

---

## Key Components

- `mcp_server.py` – Feature-rich MCP server with structured responses, guardrails, and dynamic tool packs.
- `hello_mcp_server.py` – Minimal JSON-RPC baseline that mirrors the official SDK tutorial.
- `cli_chat.py` – Lightweight CLI that connects to the server and shows tool traces and token usage.
- `tools/` – Collection of modular tool packs (`kv_store`, `config`, `artifacts`, `plans`, `dynamic_plans`, `progress`, `watchers`, `alerts`, `templates`, etc.).
- `artifacts/`, `data/`, `logs/` – Sample state and storage roots used by the automation features (safe to remove when you want a clean slate).

---

## Prerequisites

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/) for virtualenv and dependency management
- Access to an MCP-capable model (OpenAI example provided)

---

## Quickstart

1. **Create the environment and install deps**
   ```bash
   uv venv
   uv pip install openai python-dotenv textual rich
   ```
2. **Configure your model credentials**
   ```bash
   echo "OPENAI_API_KEY=sk-..." > .env
   echo "OPENAI_MODEL=gpt-4o-mini" >> .env
   ```
   Adjust the model identifier to match your provider.
3. **Run a server**
   ```bash
   python mcp_server.py       # full lab with guardrails + tool packs
   # or
   python hello_mcp_server.py # stripped-down tutorial server
   ```
4. **Talk to it from the CLI**
   ```bash
   uv run python cli_chat.py
   ```
   The CLI prints tool traces and token counts inline. Modify `cli_chat.py` if you prefer conversational prose instead of terse traces.

---

## Feature Highlights

**Guardrails & Configuration**
- Each built-in tool returns `{"ok": bool, ...}` payloads so failures are explicit and machine-checkable.
- Sandbox root defaults to `./artifacts` with extension and size limits (`.log`, `.txt`) for safer file I/O.
- Profile-aware settings live in `tools/config.py`, letting you toggle between `dev`, `customerA`, or custom profiles via environment overrides.

**Persistent Memory & Artifacts**
- `tools/kv_store.py` offers JSON-backed list/get/set/delete helpers for lightweight agent memory.
- `tools/artifacts.py` persists text/JSON/binary outputs and provides readable previews.
- `tools/tool_utils.py` standardises FastMCP response handling so nested tools can compose cleanly.

**Automation & Ops Hooks**
- `tools/plans.py` and `tools/dynamic_plans.py` orchestrate templated, multi-step workflows.
- `tools/progress.py` tracks log offsets to summarise only new bytes on each read.
- `tools/watchers.py` reacts to file fingerprint changes; `tools/alerts.py` triggers when regex thresholds are exceeded.
- `tools/templates.py` turns KV/config/artifact data into incident updates or customer-facing summaries.

---

## Tool Catalogue

Core tools exported by `mcp_server.py`:

- Utility: `say_hello`, `get_time`, `math_eval`
- File ops: `search_files`, `read_file`, `summarize_logs`
- KV store: `kv_set`, `kv_get`, `kv_delete`, `kv_list`
- Configuration: `config_load`, `config_set_profile`, `config_list_profiles`, and related helpers
- Artifacts: `save_text`, `save_json`, `save_bytes`, `list_artifacts`, `read_artifact`, `delete_artifact`
- Plans & watchers: `plan_summarize_logs`, `run_plan`, `watch_file_once`, `watch_file_poll`
- Progress tracking: `track_read`, `track_read_and_summarize`, `offset_read`, `offset_reset`
- Alerts & templates: `alert_count_text`, `alert_track_and_save`, `alert_run_plan_if`, `tpl_*`, `gen_incident_update`

Every tool returns structured JSON so you can chain them safely from an agent or client.

---

## Working Directories

- `artifacts/` – Sandbox root and default artifact directory for tool-generated output.
- `data/kv.json` – Persistent store backing the KV tools (auto-creates and self-heals on corruption).
- `logs/chat.log` – Sample log stream used by progress/summary tools.
- `sandbox/kv.json` – Legacy sandbox state retained for backward compatibility; new flows use `data/`.

Feel free to clear these directories whenever you want to reset the lab environment.

---

## Development & Extension

- Install test tooling with `uv pip install pytest` and run `uv run pytest -q`.
- To add your own tool pack:
  1. Create `tools/<name>.py` with a `register_<name>_tools(mcp)` function.
  2. Import and call the new registrar from `mcp_server.py`.
  3. Reload your client—FastMCP will advertise the updated schema automatically.
- Refer to `RECENT_FIXES.txt` for a concise changelog of recent adjustments.

---

## Troubleshooting

- Server hangs until Ctrl+C? Ensure every tool calls `respond(...)`; FastMCP logs helpful traces to stderr.
- `400 invalid tool name`: stick to `[a-zA-Z0-9_-]+`.
- Missing files? Use recursive glob patterns such as `**/*.log`.
- Textual UI glitches? Upgrade to `textual>=0.52` and confirm your terminal supports rich markup.
