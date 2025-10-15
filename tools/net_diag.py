"""Network diagnostics wrappers around system utilities."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from typing import Any, Dict, Iterable, List, Optional

from mcp.server.fastmcp import FastMCP

from tools.tool_utils import unwrap_tool_result

_TOKEN_RE = re.compile(
    r"(?i)(api[-_ ]?key|token|secret)\s*[:=]\s*([^\s]+)"
)
_PRIVATE_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3})\b"
)


def _which_or(candidates: Iterable[str]) -> Optional[str]:
    """Return the first command available in PATH."""
    for name in candidates:
        if shutil.which(name):
            return name
    return None


def _redact(text: str) -> str:
    """Mask tokens and private IP addresses in diagnostic output."""
    if not text:
        return text
    redacted = _TOKEN_RE.sub(r"\1=[REDACTED]", text)
    redacted = _PRIVATE_IP_RE.sub("[PRIVATE_IP]", redacted)
    return redacted


def _compact(text: str, limit: int = 2000) -> str:
    """Clip large output blocks to keep responses manageable."""
    if len(text) <= limit:
        return text
    head = text[: limit // 2].rstrip()
    tail = text[-limit // 2 :].lstrip()
    return head + "\n...\n" + tail


async def _append_audit(mcp: FastMCP, filename: str, payload: Dict[str, Any]) -> None:
    """Append a JSON line to an audit artifact."""
    line = json.dumps(payload, ensure_ascii=False)
    initial = unwrap_tool_result(
        await mcp.call_tool(
            "save_text",
            {"filename": filename, "text": line + "\n", "overwrite": False},
        )
    )
    if isinstance(initial, dict) and initial.get("ok"):
        return
    if isinstance(initial, dict) and initial.get("reason") == "exists":
        current = ""
        read_res = unwrap_tool_result(
            await mcp.call_tool(
                "read_artifact", {"filename": filename, "as_text": True}
            )
        )
        if isinstance(read_res, dict) and read_res.get("ok"):
            current = read_res.get("text", "") or ""
        combined = (current.rstrip("\n") + "\n" + line).strip("\n") + "\n"
        unwrap_tool_result(
            await mcp.call_tool(
                "save_text",
                {"filename": filename, "text": combined, "overwrite": True},
            )
        )


async def _run(cmd: List[str], timeout: int) -> Dict[str, Any]:
    """Execute a system command with a timeout and collect redacted output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "error": f"{cmd[0]} not executable",
            "cmd": " ".join(cmd),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "error": str(exc), "cmd": " ".join(cmd)}

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "ok": False,
            "error": "process timeout",
            "cmd": " ".join(cmd),
            "timeout": timeout,
        }

    stdout = _redact(stdout_bytes.decode("utf-8", errors="replace"))
    stderr = _redact(stderr_bytes.decode("utf-8", errors="replace"))
    result = {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": _compact(stdout),
        "stderr": _compact(stderr),
        "cmd": " ".join(cmd),
    }
    return result


def register_net_diag_tools(mcp: FastMCP) -> None:
    """Register ping, trace, and DNS lookup tools."""

    @mcp.tool()
    async def net_ping(
        host: str, count: int = 3, deadline_sec: int = 10
    ) -> Dict[str, Any]:
        """Run a constrained ICMP ping."""
        pattern = re.compile(r"^[A-Za-z0-9._:-]+$")
        candidate = (host or "").strip()
        if not candidate or not pattern.fullmatch(candidate):
            return {"ok": False, "error": "invalid host"}

        binary = _which_or(["ping"])
        if not binary:
            payload = {"ok": False, "error": "ping not found"}
            await _append_audit(mcp, "audit_net_ping.txt", payload)
            return payload

        safe_count = max(1, min(int(count), 10))
        safe_deadline = max(2, int(deadline_sec))

        cmd = [
            binary,
            "-c",
            str(safe_count),
            "-w",
            str(safe_deadline),
            candidate,
        ]
        result = await _run(cmd, timeout=safe_deadline + 5)
        await _append_audit(mcp, "audit_net_ping.txt", result)
        return result

    @mcp.tool()
    async def net_trace(
        host: str, max_hops: int = 20, deadline_sec: int = 20
    ) -> Dict[str, Any]:
        """Run traceroute or tracepath with conservative defaults."""
        pattern = re.compile(r"^[A-Za-z0-9._:-]+$")
        candidate = (host or "").strip()
        if not candidate or not pattern.fullmatch(candidate):
            return {"ok": False, "error": "invalid host"}

        binary = _which_or(["traceroute", "tracepath"])
        if not binary:
            payload = {"ok": False, "error": "traceroute/tracepath not found"}
            await _append_audit(mcp, "audit_net_trace.txt", payload)
            return payload

        safe_hops = max(1, min(int(max_hops), 64))
        safe_deadline = max(5, int(deadline_sec))

        if binary.endswith("tracepath"):
            cmd = [binary, "-m", str(safe_hops), candidate]
        else:
            cmd = [binary, "-m", str(safe_hops), "-w", "3", candidate]

        result = await _run(cmd, timeout=safe_deadline + 5)
        await _append_audit(mcp, "audit_net_trace.txt", result)
        return result

    @mcp.tool()
    async def dns_lookup(
        name: str,
        rrtype: str = "A",
        server: Optional[str] = None,
        deadline_sec: int = 10,
    ) -> Dict[str, Any]:
        """Perform a DNS lookup with dig or nslookup."""
        name_pattern = re.compile(r"^[A-Za-z0-9.-]+$")
        candidate = (name or "").strip()
        if not candidate or not name_pattern.fullmatch(candidate):
            return {"ok": False, "error": "invalid name"}

        server_pattern = re.compile(r"^[A-Za-z0-9._:-]+$")
        server_clean = None
        if server:
            server_clean = server.strip()
            if not server_clean or not server_pattern.fullmatch(server_clean):
                return {"ok": False, "error": "invalid server"}

        safe_rr = (rrtype or "A").strip().upper()
        safe_deadline = max(2, int(deadline_sec))

        dig_bin = _which_or(["dig"])
        ns_bin = _which_or(["nslookup"])
        binary = dig_bin or ns_bin
        if not binary:
            payload = {"ok": False, "error": "dig/nslookup not found"}
            await _append_audit(mcp, "audit_dns_lookup.txt", payload)
            return payload

        if binary == dig_bin:
            cmd = [
                binary,
                "+time=3",
                "+tries=1",
                candidate,
                safe_rr,
            ]
            if server_clean:
                cmd.append(f"@{server_clean}")
        else:
            cmd = [binary, candidate, safe_rr]
            if server_clean:
                cmd.append(server_clean)

        result = await _run(cmd, timeout=safe_deadline + 5)
        await _append_audit(mcp, "audit_dns_lookup.txt", result)
        return result
