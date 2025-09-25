# MCP Copilot Lab

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/packaging-uv-brightgreen)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Minimal **Model Context Protocol (MCP)** server + **CLI chat** in Python.  
Exposes safe tools (math eval, time, file search/read, log summarizer) and lets GPT act as a **sandboxed copilot** with guardrails.

---

## ✨ Features

- **MCP server** with 6 tools:
  - `say_hello`, `get_time`, `math_eval`
  - `search_files`, `read_file`, `summarize_logs`
- **CLI chat** client with OpenAI function-calling:
  - auto-discovers tools, chains them per turn
  - shows token usage
- **Guardrails**: sandbox root, traversal checks, extension allow-list, byte caps, per-run cap
- **Observability**: `[mcp stderr]` logs, stage logging, request timeouts

---

## 🚀 Quickstart (with uv)

# 1) clone
git clone git@github.com:KrishnaChaitanya1027/mcp-copilot-lab.git
cd mcp-copilot-lab

# 2) venv + deps
uv venv
uv pip install openai python-dotenv

# 3) env vars
echo "OPENAI_API_KEY=sk-..." > .env
echo "OPENAI_MODEL=gpt-4o-mini" >> .env

# 4) demo data
mkdir -p sandbox/logs
printf "error one\nwarn two\n"  > sandbox/logs/app.log
printf "info one\nerror two\n" > sandbox/logs/other.log

# 5) run
uv run cli_chat.py


Example Prompt
Greet Krishna, tell me the time in America/Toronto,
list **/*.log, and show the first 40 bytes of logs/app.log
### 3) Add `QUICKSTART.md`

💬 Example prompt
Greet Krishna, tell me the time in America/Toronto,
list **/*.log, and show the first 40 bytes of logs/app.log

🧩 Extend with your own tool

Add schema in tools/list

Handle it in tools/call

/reload the chat and call it

Example: word_count is shown in the full README of this repo.

🧪 Testing
uv pip install pytest
uv run pytest -q

🛠 Troubleshooting

Hangs until Ctrl+C: some path didn’t call respond(...) → check [mcp stderr]

400 invalid tool name: only a-zA-Z0-9_- allowed

No .log files found: use recursive pattern: **/*.log
