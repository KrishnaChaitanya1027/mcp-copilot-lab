# Smoke Drill (≈2 min)

1. Start the MCP server:
   - `python mcp_server.py`
2. In a second terminal launch the chat client:
   - `uv run python cli_chat.py`
3. Seed a fresh log (within the chat prompt):
   - `save_text filename="logs/smoke.log" text="ERROR: smoke test\nINFO: ok" overwrite=true`
4. Confirm the watcher sees it:
   - `watch_dir_once glob="logs/*.log"`
5. Trigger an alert on the new log slice:
   - `alert_count_text text="ERROR: smoke test\nINFO: ok" pattern="ERROR" threshold=1 comparator=">="`
6. Capture a case and export a summary (note the id from step 6a):
   - `case_create title="Smoke Check" customer="Acme"`
   - `case_export id="<case id>" save_as="smoke_case.txt"`
7. Render the incident template for quick copy/paste:
   - `tpl_render name="incident_email" extra={"art_text":"Smoke drill summary."} save_as="smoke_incident.txt" overwrite=true`
8. Bundle the resulting artifacts:
   - `bundle_latest name="smoke_bundle.zip"`
9. Run TLS and HTTP probes against a known host:
   - `tls_inspect host="www.google.com"`
   - `http_get url="https://www.google.com"`
10. Verify outputs landed in the artifact directory:
    - `list_artifacts`
