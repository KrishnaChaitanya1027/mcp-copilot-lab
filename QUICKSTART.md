# Quickstart — MCP Copilot Lab

This project is a minimal **MCP server + CLI chat** with 6 safe tools.

## Run in 60 seconds

```bash
git clone git@github.com:KrishnaChaitanya1027/mcp-copilot-lab.git
cd mcp-copilot-lab
uv venv
uv pip install openai python-dotenv
echo "OPENAI_API_KEY=sk-..." > .env
echo "OPENAI_MODEL=gpt-4o-mini" >> .env
mkdir -p sandbox/logs
printf "error\nwarn\n" > sandbox/logs/app.log
uv run cli_chat.py
