# MCP Copilot Lab

Minimal MCP (Model Context Protocol) server + CLI client in Python. Exposes safe tools
(math eval, time, file search/read, log summarizer) so GPT can act as a sandboxed copilot
with guardrails (path traversal checks, extension allow-list, byte caps, per-turn limits).

## Quickstart
```bash
uv venv
uv pip install openai python-dotenv
echo "OPENAI_API_KEY=sk-..." > .env
echo "OPENAI_MODEL=gpt-4o-mini" >> .env
uv run cli_chat.py
```bash
printf "MIT License\n\nCopyright (c) 2025 Krishna\n" > LICENSE

cat > README.md <<'EOF'
# MCP Copilot Lab

Minimal MCP (Model Context Protocol) server + CLI client in Python. Exposes safe tools
(math eval, time, file search/read, log summarizer) so GPT can act as a sandboxed copilot
with guardrails (path traversal checks, extension allow-list, byte caps, per-turn limits).

## Quickstart
```bash
uv venv
uv pip install openai python-dotenv
echo "OPENAI_API_KEY=sk-..." > .env
echo "OPENAI_MODEL=gpt-4o-mini" >> .env
OR CREATE A .env file and paste the above two lines.
uv run cli_chat.py

cat > README.md <<'EOF'
# MCP Copilot Lab

Minimal MCP (Model Context Protocol) server + CLI client in Python. Exposes safe tools
(math eval, time, file search/read, log summarizer) so GPT can act as a sandboxed copilot
with guardrails (path traversal checks, extension allow-list, byte caps, per-turn limits).

## Quickstart
```bash
uv venv
uv pip install openai python-dotenv
echo "OPENAI_API_KEY=sk-..." > .env
echo "OPENAI_MODEL=gpt-4o-mini" >> .env
uv run cli_chat.py
```bash
printf "MIT License\n\nCopyright (c) 2025 Krishna\n" > LICENSE

cat > README.md <<'EOF'
# MCP Copilot Lab

Minimal MCP (Model Context Protocol) server + CLI client in Python. Exposes safe tools
(math eval, time, file search/read, log summarizer) so GPT can act as a sandboxed copilot
with guardrails (path traversal checks, extension allow-list, byte caps, per-turn limits).

## Quickstart
```bash
uv venv
uv pip install openai python-dotenv
echo "OPENAI_API_KEY=sk-..." > .env
echo "OPENAI_MODEL=gpt-4o-mini" >> .env
uv run cli_chat.py


