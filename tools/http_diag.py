"""HTTP diagnostics helper around curl for quick endpoint inspection."""

from __future__ import annotations

import asyncio
import re
import subprocess
from typing import Any, Dict, List, Tuple

from mcp.server.fastmcp import FastMCP

from tools.artifacts import _safe_name

# Headers whose values should never be echoed back verbatim.
_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key"}


def _redact_value(name: str, value: str) -> str:
    """Replace sensitive header values with a placeholder."""
    if name.lower() in _SENSITIVE_HEADERS:
        return "[REDACTED]"
    return value


def _sanitize_header(name: str, value: str) -> Tuple[str, str]:
    """Clamp header strings to single-line safe values."""
    safe_name = re.sub(r"[\r\n:]", " ", name).strip()
    safe_value = re.sub(r"[\r\n]", " ", value).strip()
    return safe_name, safe_value


async def _run_curl(cmd: List[str], timeout: int) -> subprocess.CompletedProcess[bytes]:
    """Invoke curl in a background thread to keep the event loop responsive."""

    def _execute() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            cmd,
            input=b"",
            capture_output=True,
            text=False,
            timeout=timeout,
            check=False,
        )

    return await asyncio.to_thread(_execute)


def _extract_final_response(raw: str) -> Tuple[str | None, Dict[str, str], str]:
    """Return status, headers, and body from the last HTTP exchange in a curl -i trace."""
    status: str | None = None
    headers: Dict[str, str] = {}
    body = raw

    last_header_idx = -1
    for match in re.finditer(r"^HTTP/\d\.\d[^\r\n]*", raw, re.MULTILINE):
        last_header_idx = match.start()

    if last_header_idx >= 0:
        view = raw[last_header_idx:]
        sep = "\r\n\r\n"
        sep_idx = view.find(sep)
        if sep_idx < 0:
            sep = "\n\n"
            sep_idx = view.find(sep)
        if sep_idx >= 0:
            header_text = view[:sep_idx]
            body = view[sep_idx + len(sep):]
        else:
            header_text = view
            body = ""
        lines = header_text.splitlines()
        if lines:
            status = lines[0].strip()
            for line in lines[1:]:
                if ":" not in line:
                    continue
                name, value = line.split(":", 1)
                name, value = _sanitize_header(name, value)
                headers[name] = value

    return status, headers, body


def _preview(text: str, limit: int = 400) -> str:
    """Compact a potentially large HTTP body for return payloads."""
    if len(text) <= limit:
        return text
    head = text[: limit // 2].rstrip()
    tail = text[-limit // 2 :].lstrip()
    return head + "\n...\n" + tail


async def _append_artifact(mcp: FastMCP, filename: str, entry: str) -> Dict[str, Any]:
    """Append log content to an artifact file (re-save with overwrite)."""
    existing = ""
    try:
        _, read_meta = await mcp.call_tool(
            "read_artifact", {"filename": filename, "as_text": True}
        )
    except Exception:
        read_meta = None
    read_result = (read_meta or {}).get("result", {})
    if read_result.get("ok"):
        existing = read_result.get("text", "") or ""

    combined = (existing.rstrip() + "\n\n" + entry.strip()).strip()

    _, save_meta = await mcp.call_tool(
        "save_text",
        {"filename": filename, "text": combined, "overwrite": True},
    )
    return (save_meta or {}).get("result", {})


def register_http_diag_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def http_get(
        url: str,
        timeout_sec: int = 10,
        headers: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        """Fetch a URL with curl, redact sensitive headers, and log the exchange."""
        target = (url or "").strip()
        if not target:
            return {"ok": False, "error": "url is required"}

        header_args: List[str] = []
        safe_request_headers: Dict[str, str] = {}
        for name, value in (headers or {}).items():
            safe_name, safe_value = _sanitize_header(str(name), str(value))
            header_args.extend(["-H", f"{safe_name}: {safe_value}"])
            safe_request_headers[safe_name] = _redact_value(safe_name, safe_value)

        cmd = [
            "curl",
            "-i",
            "-L",
            "--max-time",
            str(max(1, int(timeout_sec))),
            "-sS",
            target,
        ] + header_args

        try:
            proc = await _run_curl(cmd, max(1, int(timeout_sec)) + 2)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "curl timed out", "url": target}
        except FileNotFoundError:
            return {"ok": False, "error": "curl binary not available"}
        except Exception as exc:  # pragma: no cover - defensive fallback
            return {"ok": False, "error": f"curl execution failed: {exc}"}

        stdout_text = (proc.stdout or b"").decode("utf-8", errors="replace")
        stderr_text = (proc.stderr or b"").decode("utf-8", errors="replace")
        raw_text = stdout_text + ("\n" + stderr_text if stderr_text else "")
        status_line, resp_headers, body = _extract_final_response(raw_text)

        redacted_response_headers = {
            name: _redact_value(name, value) for name, value in resp_headers.items()
        }
        preview = _preview(body.strip())

        log_lines = [
            f"=== HTTP GET {target} ===",
            f"Status: {status_line or 'unknown'}",
            "Request headers:",
        ]
        if safe_request_headers:
            for name, value in safe_request_headers.items():
                log_lines.append(f"{name}: {value}")
        else:
            log_lines.append("(none)")
        log_lines.append("")
        log_lines.append("Response headers:")
        if redacted_response_headers:
            for name, value in redacted_response_headers.items():
                log_lines.append(f"{name}: {value}")
        else:
            log_lines.append("(none)")
        log_lines.append("")
        log_lines.append("Body preview:")
        log_lines.append(preview or "(empty)")

        try:
            save_result = await _append_artifact(
                mcp, _safe_name("audit_http.txt"), "\n".join(log_lines)
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            return {"ok": False, "error": f"failed to write artifact: {exc}"}

        if not save_result.get("ok"):
            return {
                "ok": False,
                "error": "saving artifact failed",
                "details": save_result,
            }

        return {
            "ok": proc.returncode == 0,
            "status": status_line,
            "headers": redacted_response_headers,
            "body_preview": preview,
            "path": save_result.get("path"),
        }
