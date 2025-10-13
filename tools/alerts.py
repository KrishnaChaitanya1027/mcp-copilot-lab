#Goal: scan new log chunks and trigger actions (save a report, pin in KV, or run a plan) 
# only when a regex pattern is seen enough times.
# tools/alerts.py

from __future__ import annotations
from typing import Dict, Any, Optional, List
from pathlib import Path
import re, json, datetime
from mcp.server.fastmcp import FastMCP
from tools.tool_utils import unwrap_tool_result

def _cmp(count: int, threshold: int, op: str) -> bool:
    op = op.strip()
    if op == ">=": return count >= threshold
    if op == ">":  return count >  threshold
    if op == "==": return count == threshold
    if op == "<=": return count <= threshold
    if op == "<":  return count <  threshold
    raise ValueError("Invalid comparator; use one of: >=, >, ==, <=, <")

def _compile(pat: str, case_insensitive: bool) -> re.Pattern:
    flags = re.IGNORECASE if case_insensitive else 0
    return re.compile(pat, flags)

def _count_matches(text: str, rx: re.Pattern) -> Dict[str, Any]:
    # Count matches and capture up to 5 sample lines
    count = 0
    samples: List[str] = []
    for line in text.splitlines():
        if rx.search(line):
            count += 1
            if len(samples) < 5:
                samples.append(line[:300])
    return {"count": count, "samples": samples}

def register_alert_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def alert_count_text(text: str, pattern: str, threshold: int,
                               comparator: str = ">=", case_insensitive: bool = True) -> Dict[str, Any]:
        """
        Count regex 'pattern' in 'text'. Trigger if count (comparator) threshold.
        Returns: {ok, count, triggered, threshold, comparator, samples:[...]}
        """
        rx = _compile(pattern, case_insensitive)
        res = _count_matches(text, rx)
        trig = _cmp(res["count"], int(threshold), comparator)
        return {"ok": True, "count": res["count"], "triggered": trig,
                "threshold": int(threshold), "comparator": comparator, "samples": res["samples"]}

    @mcp.tool()
    async def alert_track_and_save(path: str, pattern: str, threshold: int,
                                   comparator: str = ">=", case_insensitive: bool = True,
                                   max_bytes: int = 65536, key: Optional[str] = None,
                                   filename: str = "alert_report.txt") -> Dict[str, Any]:
        """
        Read only the *new* bytes using track_read(), count matches and if triggered:
          - save a short report via save_text()
          - cache its path in KV at 'alert:last_path' (or 'alert:last_path:{key}')
        Always returns the new offset boundaries and whether it triggered.
        """
        # 1) read new chunk
        tr = unwrap_tool_result(await mcp.call_tool("track_read", {"path": path, "max_bytes": max_bytes}))
        if not (isinstance(tr, dict) and tr.get("ok")):
            return {"ok": False, "error": "track_read failed", "detail": tr}

        chunk = tr.get("chunk", "") or ""
        if not chunk:
            return {"ok": True, "triggered": False, "note": "no new bytes",
                    "path": tr.get("path"), "start": tr.get("start"), "end": tr.get("end"), "eof": tr.get("eof")}

        # 2) count + decide
        rx = _compile(pattern, case_insensitive)
        res = _count_matches(chunk, rx)
        trig = _cmp(res["count"], int(threshold), comparator)

        artifact_path = None
        if trig:
            # 3) build + save a tiny report
            ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            report = [
                f"[{ts}] ALERT for {Path(tr['path']).name}",
                f"Range: {tr['start']}..{tr['end']}  bytes={tr['bytes_read']}",
                f"Pattern: {pattern!r}  comparator: {comparator}  threshold: {threshold}",
                f"Count: {res['count']}",
                "",
                "Samples (up to 5):",
                *res["samples"]
            ]
            saved = unwrap_tool_result(
                await mcp.call_tool("save_text", {"filename": filename, "text": "\n".join(report), "overwrite": True})
            )
            if isinstance(saved, dict) and saved.get("ok"):
                artifact_path = saved.get("path")
                k = f"alert:last_path:{key}" if key else "alert:last_path"
                await mcp.call_tool("kv_set", {"key": k, "value": artifact_path})

        return {
            "ok": True,
            "triggered": trig,
            "count": res["count"],
            "threshold": int(threshold),
            "comparator": comparator,
            "samples": res["samples"],
            "artifact_path": artifact_path,
            "path": tr.get("path"),
            "start": tr.get("start"),
            "end": tr.get("end"),
            "eof": tr.get("eof"),
            "bytes_read": tr.get("bytes_read")
        }

    @mcp.tool()
    async def alert_run_plan_if(path: str, pattern: str, threshold: int,
                                steps: List[Dict[str, Any]],
                                comparator: str = ">=", case_insensitive: bool = True,
                                max_bytes: int = 65536) -> Dict[str, Any]:
        """
        Read new bytes (track_read). If match count meets threshold, run a dynamic plan (steps).
        Returns: {ok, triggered, count, plan?: {...}}
        """
        tr = unwrap_tool_result(await mcp.call_tool("track_read", {"path": path, "max_bytes": max_bytes}))
        if not (isinstance(tr, dict) and tr.get("ok")):
            return {"ok": False, "error": "track_read failed", "detail": tr}

        chunk = tr.get("chunk", "") or ""
        rx = _compile(pattern, case_insensitive)
        res = _count_matches(chunk, rx)
        trig = _cmp(res["count"], int(threshold), comparator)

        plan_out = None
        if trig:
            plan_out = unwrap_tool_result(
                await mcp.call_tool("run_plan", {"steps": steps, "save_key": None})
            )

        return {"ok": True, "triggered": trig, "count": res["count"], "threshold": int(threshold),
                "comparator": comparator, "plan": plan_out}
