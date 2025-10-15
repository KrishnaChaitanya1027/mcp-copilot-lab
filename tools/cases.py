from __future__ import annotations

import json
import secrets
import string
from datetime import datetime, timezone
from typing import Dict, List

from mcp.server.fastmcp import FastMCP

from tools.kv_store import _LOCK, _load_db, _save_db
from tools.artifacts import ART_DIR, _safe_name

ALLOWED_STATUSES = {"open", "monitoring", "closed"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3", "P4"}


def _generate_case_id(ts: datetime) -> str:
    # token of 6 lowercase alphanumerics
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"case-{ts.strftime('%Y%m%d')}-{suffix}"


def _normalize_tags(raw_tags: List[str] | None) -> List[str]:
    if not raw_tags:
        return []
    return [str(tag) for tag in raw_tags if isinstance(tag, str) and tag.strip()]


def _normalize_priority(priority: str) -> str:
    priority = priority.upper()
    if priority not in ALLOWED_PRIORITIES:
        raise ValueError(f"priority must be one of {sorted(ALLOWED_PRIORITIES)}")
    return priority


def _normalize_status(status: str) -> str:
    status = status.lower()
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"status must be one of {sorted(ALLOWED_STATUSES)}")
    return status


def _load_case(db: Dict[str, str], case_id: str) -> Dict[str, object] | None:
    key = f"case:{case_id}"
    payload = db.get(key)
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _ensure_case_defaults(case: Dict[str, object]) -> None:
    case.setdefault("timeline", [])
    case.setdefault("artifacts", [])
    status = case.get("status") or "open"
    try:
        case["status"] = _normalize_status(str(status))
    except ValueError:
        case["status"] = "open"
    priority = case.get("priority") or "P3"
    try:
        case["priority"] = _normalize_priority(str(priority))
    except ValueError:
        case["priority"] = "P3"


def _save_case(db: Dict[str, str], case: Dict[str, object]) -> None:
    _ensure_case_defaults(case)
    key = f"case:{case['id']}"
    db[key] = json.dumps(case, ensure_ascii=False, sort_keys=True)


def _load_index(db: Dict[str, str]) -> List[Dict[str, object]]:
    raw = db.get("case:index")
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return []


def _save_index(db: Dict[str, str], index: List[Dict[str, object]]) -> None:
    db["case:index"] = json.dumps(index, ensure_ascii=False, sort_keys=False)


def _build_index_entry(case: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": case["id"],
        "title": case.get("title"),
        "status": case.get("status"),
        "priority": case.get("priority"),
        "customer": case.get("customer"),
        "updated_at": case.get("updated_at"),
    }


def _upsert_index(db: Dict[str, str], case: Dict[str, object]) -> None:
    index = _load_index(db)
    index = [item for item in index if item.get("id") != case["id"]]
    index.insert(0, _build_index_entry(case))
    _save_index(db, index)


def register_case_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def case_create(
        title: str,
        customer: str,
        env: str = "prod",
        priority: str = "P3",
        tags: List[str] | None = None,
    ) -> Dict[str, object]:
        now = datetime.now(timezone.utc)
        case_id = _generate_case_id(now)
        clean_tags = _normalize_tags(tags)

        try:
            priority_norm = _normalize_priority(priority)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        case = {
            "id": case_id,
            "title": title,
            "customer": customer,
            "env": env,
            "priority": priority_norm,
            "tags": clean_tags,
            "status": _normalize_status("open"),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "timeline": [],
            "artifacts": [],
        }

        with _LOCK:
            db = _load_db()
            _save_case(db, case)
            _upsert_index(db, case)
            _save_db(db)

        return {"ok": True, "id": case_id, "status": "open"}

    @mcp.tool()
    async def case_get(id: str) -> Dict[str, object]:
        with _LOCK:
            db = _load_db()
            case = _load_case(db, id)

        if not case:
            return {"ok": False, "error": "Case not found", "id": id}

        return {"ok": True, "case": case}

    @mcp.tool()
    async def case_list(customer: str = "", status: str = "", limit: int = 50) -> Dict[str, object]:
        safe_limit = max(0, min(int(limit), 200))

        status_filter: str | None = None
        if status:
            try:
                status_filter = _normalize_status(status)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

        with _LOCK:
            db = _load_db()
            index = _load_index(db)

        filtered: List[Dict[str, object]] = []
        for entry in index:
            if customer and str(entry.get("customer", "")).lower() != customer.lower():
                continue
            if status_filter and str(entry.get("status", "")).lower() != status_filter:
                continue
            filtered.append(entry)
            if len(filtered) >= safe_limit:
                break

        return {"ok": True, "total": len(filtered), "cases": filtered}

    @mcp.tool()
    async def case_note(id: str, text: str, by: str = "krishna") -> Dict[str, object]:
        now = datetime.now(timezone.utc).isoformat()
        with _LOCK:
            db = _load_db()
            case = _load_case(db, id)
            if not case:
                return {"ok": False, "error": "Case not found", "id": id}

            _ensure_case_defaults(case)
            case["timeline"].append({
                "type": "note",
                "text": text,
                "by": by,
                "at": now,
            })
            case["updated_at"] = now

            _save_case(db, case)
            _upsert_index(db, case)
            _save_db(db)

        return {"ok": True, "case": case}

    @mcp.tool()
    async def case_attach_artifact(id: str, filename: str) -> Dict[str, object]:
        try:
            safe_name = _safe_name(filename)
        except ValueError:
            return {"ok": False, "error": "Invalid artifact filename", "filename": filename}

        path = ART_DIR / safe_name
        if not path.exists() or not path.is_file():
            return {"ok": False, "error": "Artifact not found", "filename": safe_name}

        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()

        with _LOCK:
            db = _load_db()
            case = _load_case(db, id)
            if not case:
                return {"ok": False, "error": "Case not found", "id": id}

            _ensure_case_defaults(case)
            if safe_name not in case["artifacts"]:
                case["artifacts"].append(safe_name)

            case["timeline"].append({
                "type": "artifact",
                "filename": safe_name,
                "at": now,
            })
            case["updated_at"] = now

            _save_case(db, case)
            _upsert_index(db, case)
            _save_db(db)

        return {"ok": True, "case": case}

    @mcp.tool()
    async def case_export(
        id: str,
        template_name: str | None = None,
        save_as: str | None = None,
    ) -> Dict[str, object]:
        """Export a case summary, optionally rendering through a stored template."""
        with _LOCK:
            db = _load_db()
            case = _load_case(db, id)
            if not case:
                return {"ok": False, "error": "Case not found", "id": id}
            _ensure_case_defaults(case)

        # Reuse existing filenames when the caller omits an explicit artifact name.
        target_name = save_as or f"{case['id']}.txt"

        if template_name:
            # Render via template so reports inherit shared formatting.
            try:
                blocks, meta = await mcp.call_tool(
                    "tpl_render",
                    {"name": template_name, "extra": {"case": case}},
                )
            except Exception as exc:  # pragma: no cover - defensive
                return {"ok": False, "error": f"Template render failed: {exc}"}
            tpl_result = (meta or {}).get("result", {})
            if not tpl_result.get("ok"):
                return {
                    "ok": False,
                    "error": "Template render failed",
                    "details": tpl_result,
                }
            rendered_text = tpl_result.get("rendered", "")
            if not isinstance(rendered_text, str) or not rendered_text:
                return {"ok": False, "error": "Template produced no text"}
        else:
            # Build a readable text summary when no template is supplied.
            tags = ", ".join(case.get("tags", [])) or "none"
            timeline = case.get("timeline", [])
            artifacts = case.get("artifacts", [])
            lines = [
                f"Case ID: {case['id']}",
                f"Title: {case.get('title', '')}",
                f"Customer: {case.get('customer', '')}",
                f"Environment: {case.get('env', '')}",
                f"Priority: {case.get('priority', '')}",
                f"Status: {case.get('status', '')}",
                f"Tags: {tags}",
                f"Created: {case.get('created_at', '')}",
                f"Updated: {case.get('updated_at', '')}",
                "",
                "Artifacts:",
            ]
            if artifacts:
                for art in artifacts:
                    lines.append(f"- {art}")
            else:
                lines.append("- none")
            lines.append("")
            lines.append("Timeline:")
            if timeline:
                for entry in timeline:
                    etype = entry.get("type", "event")
                    at = entry.get("at", "")
                    by = entry.get("by")
                    detail_parts = []
                    if etype == "note":
                        detail_parts.append(entry.get("text", ""))
                        if by:
                            detail_parts.append(f"(by {by})")
                    elif etype == "artifact":
                        detail_parts.append(entry.get("filename", ""))
                    else:
                        detail_parts.append(json.dumps(entry, ensure_ascii=False))
                    detail = " ".join(filter(None, detail_parts))
                    lines.append(f"- [{etype}] {at} {detail}".rstrip())
            else:
                lines.append("- no timeline entries")
            rendered_text = "\n".join(lines)

        try:
            _, save_meta = await mcp.call_tool(
                "save_text",
                {"filename": target_name, "text": rendered_text, "overwrite": True},
            )
        except Exception as exc:  # pragma: no cover - defensive
            return {"ok": False, "error": f"Failed to save export: {exc}"}

        save_result = (save_meta or {}).get("result", {})
        if not save_result.get("ok"):
            return {
                "ok": False,
                "error": "Failed to save export",
                "details": save_result,
            }

        # Mirror save_text output so callers can locate and preview the artifact quickly.
        return {
            "ok": True,
            "path": save_result.get("path"),
            "preview": save_result.get("preview"),
        }
