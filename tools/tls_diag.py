"""TLS diagnostics helper that shells out to OpenSSL for quick certificate stats."""

from __future__ import annotations

import asyncio
import re
import subprocess
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from tools.artifacts import _safe_name

# Regex compiled once so every run reuses the same matcher.
_PRIVATE_IP_RE = re.compile(
    r"\b("
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}"
    r")\b"
)


def _redact_private_ips(text: str) -> str:
    """Replace RFC1918 address literals so artifacts stay scrubbed."""
    return _PRIVATE_IP_RE.sub("[PRIVATE_IP]", text)


def _safe_host_fragment(host: str) -> str:
    """Fold host into filename-safe characters before passing through _safe_name."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", host or "unknown")


def _extract_first(patterns: List[str], text: str) -> Optional[str]:
    """Search each regex and return the first captured group (stripped)."""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def _parse_sans(text: str) -> List[str]:
    """Find SAN blocks and break them into individual entries."""
    san_line = _extract_first(
        [
            r"SANs?\s*:\s*(.+)",
            r"Subject\s+Alternative\s+Name:\s*(.+)",
            r"X509v3 Subject Alternative Name:\s*(.+)",
        ],
        text,
    )
    if not san_line:
        return []
    parts = [p.strip() for p in re.split(r",\s*", san_line) if p.strip()]
    return parts


def _parse_output(text: str) -> Dict[str, Any]:
    """Pull common TLS attributes out of the OpenSSL text blob."""
    protocol = _extract_first(
        [r"Protocol\s*:\s*([^\n]+)", r"^\s*Protocol\s+:\s*([^\n]+)"],
        text,
    )
    cipher = _extract_first(
        [r"Ciphersuite\s*:\s*([^\n]+)", r"Cipher\s*:\s*([^\n]+)"],
        text,
    )
    common_name = _extract_first(
        [
            r"subject:\s*.*CN\s*=\s*([^,\n/]+)",
            r"subject=/?(?:.*?/)?CN=([^/\n]+)",
        ],
        text,
    )
    not_before = _extract_first(
        [
            r"notBefore\s*=\s*([^\n]+)",
            r"Not\s+Before\s*:\s*([^\n]+)",
            r"start date:\s*([^\n]+)",
        ],
        text,
    )
    not_after = _extract_first(
        [
            r"notAfter\s*=\s*([^\n]+)",
            r"Not\s+After\s*:\s*([^\n]+)",
            r"expire date:\s*([^\n]+)",
        ],
        text,
    )

    chain_length = text.count("-----BEGIN CERTIFICATE-----")
    sans = _parse_sans(text)

    return {
        "protocol": protocol,
        "cipher": cipher,
        "common_name": common_name,
        "not_before": not_before,
        "not_after": not_after,
        "sans": sans,
        "chain_length": chain_length,
    }


def _preview(text: str, limit: int = 600) -> str:
    """Return a compact snippet so callers can inspect a short summary inline."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half].rstrip() + "\n...\n" + text[-half:].lstrip()


async def _run_openssl(host: str, port: int, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run openssl s_client asynchronously so we do not block the event loop."""
    cmd = [
        "openssl",
        "s_client",
        "-connect",
        f"{host}:{port}",
        "-servername",
        host,
        "-showcerts",
        "-brief",
    ]

    def _execute() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            input="",
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return await asyncio.to_thread(_execute)


def register_tls_diag_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def tls_inspect(
        host: str,
        port: int = 443,
        timeout_sec: int = 12,
    ) -> Dict[str, Any]:
        """Inspect a TLS endpoint and stash the raw OpenSSL report."""
        target = host.strip()
        if not target:
            return {"ok": False, "error": "host is required"}

        try:
            proc = await _run_openssl(target, int(port), max(1, int(timeout_sec)))
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "OpenSSL timed out", "host": target}
        except FileNotFoundError:
            return {"ok": False, "error": "openssl binary not available"}
        except Exception as exc:  # pragma: no cover - defensive
            return {"ok": False, "error": f"openssl execution failed: {exc}"}

        combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        sanitized = _redact_private_ips(combined.strip())

        if proc.returncode != 0:
            # Save the evidence even on failure for easier post-mortems.
            preview = _preview(sanitized)
            safe_host = _safe_host_fragment(target)
            artifact_name = f"audit_tls_{safe_host}.txt"
            try:
                _, meta = await mcp.call_tool(
                    "save_text",
                    {
                        "filename": _safe_name(artifact_name),
                        "text": sanitized or "[no output]",
                        "overwrite": True,
                    },
                )
            except Exception:
                meta = None
            saved = (meta or {}).get("result", {})
            return {
                "ok": False,
                "error": f"openssl exited with code {proc.returncode}",
                "path": saved.get("path"),
                "preview": preview,
            }

        parsed = _parse_output(sanitized)
        safe_host = _safe_host_fragment(target)
        artifact_name = f"audit_tls_{safe_host}.txt"

        try:
            _, save_meta = await mcp.call_tool(
                "save_text",
                {
                    "filename": _safe_name(artifact_name),
                    "text": sanitized,
                    "overwrite": True,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            return {"ok": False, "error": f"failed to save artifact: {exc}"}

        save_result = (save_meta or {}).get("result", {})
        if not save_result.get("ok"):
            return {
                "ok": False,
                "error": "saving artifact failed",
                "details": save_result,
            }

        parsed.update(
            {
                "ok": True,
                "path": save_result.get("path"),
                "preview": _preview(sanitized),
            }
        )
        return parsed
