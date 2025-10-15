# MCP Copilot Lab

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/packaging-uv-brightgreen)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Opinionated **Model Context Protocol (MCP)** sandbox that demonstrates how to graduate a JSON-RPC tutorial server into a modular, stateful copilot equipped with guardrails, memory, automation, and a CLI chat surface.

See `RECENT_FIXES.txt` for the latest incremental changes.

---

## Fresh Drop: Incident Command Upgrade

- **Case vault + export jetpack** – `tools/cases.py` now snapshots chat context, artifacts, and handoffs while `tools/report_bundles.py` zips the whole trail into a handoff-ready bundle in one command.
- **24/7 watchers + alert loops** – `watch_dir`, `watch_dir_summary`, and `alerts` collaborate to fingerprint log rotations, raise structured alerts, and auto-save forensic notes.
- **Network x-ray suite** – `http_diag`, `tls_diag`, and `net_diag` stream redacted probes straight into `artifacts/` so you can hand your SREs packet-ready evidence without leaving the chat.
- **Secrets + roles on lockdown** – Session-aware RBAC with `tools/rbac.py` and encrypted secrets via `tools/secrets.py` mean production keys stay gated behind `role_set` instead of lurking in scripts.
- **Two-minute incident drill** – `scripts/smoke.md` walks the team through a cinematic drill that exercises alerts, cases, bundling, and diagnostics for a full confidence lap.

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
- [uv](https://docs.astral.sh/uv/) for virtualenv and dependency management (or your preferred `pip` wrapper)
- Python packages: `mcp`, `openai`, and `python-dotenv`
- Access to an MCP-capable model (OpenAI example provided)

---

## Quickstart

1. **Create the environment and install deps**
   ```bash
   uv venv
   uv pip install mcp openai python-dotenv
   ```
2. **Configure your model credentials**
   ```bash
   echo "OPENAI_API_KEY=sk-..." > .env
   echo "OPENAI_MODEL=gpt-4o-mini" >> .env
   echo "MCP_SERVER=python mcp_server.py" >> .env   # optional; CLI defaults to this command
   ```
   Adjust the model identifier to match your provider.
3. **Run a server (optional)**
   ```bash
   uv run python mcp_server.py       # full lab with guardrails + tool packs
   # or
   python hello_mcp_server.py # stripped-down tutorial server
   ```
   The CLI can also spawn `mcp_server.py` automatically using `MCP_SERVER`.
4. **Talk to it from the CLI**
   ```bash
   uv run python cli_chat.py
   ```
   The CLI prints tool traces and token counts inline. Modify `cli_chat.py` if you prefer conversational prose instead of terse traces.

> **Heads-up:** The default sandbox locations resolve to the repository's `artifacts/`, `logs/`, and `data/` directories. If you clone the project elsewhere, update the `SAFE_ROOT` constant near the top of `mcp_server.py` (and `hello_mcp_server.py`) to point at the matching path, or export `MCP_SANDBOX_ROOT`/`MCP_ARTIFACTS_DIR` via `.env`.

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

**Diagnostics & Incident Response**
- `tools/cases.py` stores case timelines, artifacts, and exports, while `tools/report_bundles.py` zips recent evidence for handoff.
- `tools/http_diag.py`, `tools/tls_diag.py`, and `tools/net_diag.py` wrap curl/OpenSSL/ping/dig with redaction and audit trails.
- `tools/audit.py` and `tools/watch_dir_summary.py` produce append-only logs summarising monitoring runs.
- `tools.validators.py` provides quick checks for PEM chains, rate-limit JSON, and IdP metadata before escalation.

---

## Tool Catalogue

Core tools exported by `mcp_server.py`, grouped by theme:

- **Utility & File Access**: `say_hello`, `get_time`, `math_eval`, `search_files`, `read_file`, `summarize_logs`.
- **State & Storage**: `kv_set`, `kv_get`, `kv_delete`, `kv_list`, `save_text`, `save_json`, `save_bytes`, `list_artifacts`, `read_artifact`, `delete_artifact`.
- **Configuration & Profiles**: `config_load`, `config_set_profile`, `config_list_profiles`, `config_override`, and helpers surfaced from `tools/config.py`.
- **Plans & Automation**: `plan_summarize_logs`, `run_plan`, `dynamic_plan_create`, `dynamic_plan_run`, plus `watch_file_once`, `watch_file_poll`, `watch_dir_once`, `watch_dir_poll`, and `watch_dir_summary`.
- **Progress Tracking & Alerts**: `track_read`, `track_read_and_summarize`, `offset_read`, `offset_reset`, `alert_count_text`, `alert_track_and_save`, `alert_run_plan_if`.
- **Case Management & Reporting**: `case_create`, `case_get`, `case_list`, `case_note`, `case_attach_artifact`, `case_export`, alongside `bundle_latest` for artifact zips.
- **Diagnostics**: `http_get`, `tls_inspect`, `net_ping`, `net_trace`, `dns_lookup`, each saving redacted traces for later review.
- **Security & Governance**: `secret_set`, `secret_get`, `secret_list`, `role_set`, `role_get`, `audit_append`, plus validators (`validate_cert_chain`, `validate_rate_limits`, `validate_idp_metadata`).
- **Templating**: `tpl_render`, `tpl_list`, `tpl_delete`, and `gen_incident_update` for structured narrative output.

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
- Sandbox permission errors? Update the `SAFE_ROOT` constant or export `MCP_SANDBOX_ROOT` so the server points at your local `artifacts/` directory.
