# Quickstart — MCP Copilot Lab

Today the lab graduates from a six-tool demo into an **incident command cockpit**: 20+ guardrailed tools, network diagnostics, forensic watchers, case vaulting, and automated bundles — all from a single chat loop.

## 1. Clone & Bootstrap

```bash
git clone git@github.com:KrishnaChaitanya1027/mcp-copilot-lab.git
cd mcp-copilot-lab
uv venv
uv pip install openai python-dotenv textual rich
echo "OPENAI_API_KEY=sk-..." > .env
echo "OPENAI_MODEL=gpt-4o-mini" >> .env
```

The CLI leans on `textual` + `rich` for the trace UI. Swap the model identifier for your preferred provider (OpenAI, Anthropic, Cohere, etc.).

## 2. Launch the Copilot Stack

```bash
python mcp_server.py          # full guardrailed command center
# or keep it vintage:
python hello_mcp_server.py    # minimal FastMCP tutorial baseline
```

In another terminal, connect the chat client:

```bash
uv run python cli_chat.py
```

Every tool emits JSON with an `ok` flag so you can script confidence checks or daisy-chain outputs into another agent.

## 3. Run the Two-Minute Ops Drill

Follow `scripts/smoke.md` for a cinematic tour:

```text
- Seed a log, watch dir fingerprints, and raise alert loops
- Create a case, attach artifacts, and export zipped evidence
- Blast TLS + HTTP diagnostics and auto-archive the transcripts
```

Prefer to freestyle? In the chat, try:

```text
watch_dir_once glob="logs/*.log"
alert_count_text text="ERROR: boom" pattern="ERROR" threshold=1 comparator=">="
case_create title="Demo Incident" customer="Acme Rocketry"
bundle_latest name="demo_bundle.zip"
```

You’ll find every artifact in `./artifacts` ready to drop into a ticket or postmortem.

## 4. Upgrade or Extend

- `role_set role="owner"` before running tools that mutate state; `role_get` keeps you honest.
- `secret_set` / `secret_get` stash per-session credentials without leaking them into disk configs.
- Add a new playbook by copying `tools/plans.py` or wire in your own tool pack via `mcp_server.py`.

That’s it — you’re live with an MCP copilot that feels more like a mission control deck than a tutorial bot.
