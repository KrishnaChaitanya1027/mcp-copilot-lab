#Turn all the previous outputs into polished text you can paste into an email or report.
#store re-usable text templates (for customer updates, incident notes, etc.), 
# fill them with data from config + KV + artifacts, and save the rendered note.


# tools/templates.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
from mcp.server.fastmcp import FastMCP
from datetime import datetime
from tools import config
from tools.tool_utils import unwrap_tool_result
import json

# ---------- KV helpers (dict-args style) ----------
async def _kv_get(mcp: FastMCP, key: str) -> Any:
    """kv_get, auto-parse JSON objects/arrays if stored as strings."""
    res = unwrap_tool_result(await mcp.call_tool("kv_get", {"key": key}))
    if isinstance(res, dict) and res.get("found"):
        val = res["value"]
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                pass
        return val
    return None

async def _kv_set(mcp: FastMCP, key: str, value: Any) -> None:
    """kv_set, JSON-encode dict/list for safer round-trips."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    await mcp.call_tool("kv_set", {"key": key, "value": value})

async def _kv_list(mcp: FastMCP, prefix: Optional[str] = None) -> List[str]:
    res = unwrap_tool_result(
        await mcp.call_tool("kv_list", {"prefix": prefix} if prefix else {})
    )
    if isinstance(res, dict) and res.get("keys"):
        return list(res["keys"])
    return []

# ---------- formatting helpers ----------
class _SafeDict(dict):
    def __missing__(self, k):  # keep {placeholder} if missing
        return "{" + k + "}"

def _safe_format(tpl: str, ctx: Dict[str, Any]) -> str:
    """Flatten cfg into top-level and format safely."""
    flat = dict(ctx)
    cfg = ctx.get("cfg", {})
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            flat.setdefault(k, v)
    return tpl.format_map(_SafeDict(flat))

def _name_from_key(k: str) -> Optional[str]:
    if k.startswith("template:") and k != "template:index":
        return k.split("template:", 1)[1]
    return None

# ---------- storage keys ----------
INDEX_KEY = "template:index"            # list[str]
TEMPLATE_KEY = "template:{name}"        # str body

def register_template_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def tpl_save(name: str, body: str, overwrite: bool = False) -> Dict[str, Any]:
        """Save a template by name."""
        idx = await _kv_get(mcp, INDEX_KEY) or []
        if not isinstance(idx, list):
            idx = []
        exists = name in idx
        if exists and not overwrite:
            return {"ok": False, "reason": "exists", "name": name}

        await _kv_set(mcp, TEMPLATE_KEY.format(name=name), body)
        if not exists:
            idx.append(name)
            idx = sorted(set(idx))
            await _kv_set(mcp, INDEX_KEY, idx)
        return {"ok": True, "name": name, "length": len(body)}

    @mcp.tool()
    async def tpl_reindex() -> Dict[str, Any]:
        """Rebuild the template index from KV keys (template:<name>)."""
        res = await mcp.call_tool("kv_list", {"prefix": "template:"})
        keys = (res.get("keys") if isinstance(res, dict) else []) or []
        names = sorted({
            k.split("template:", 1)[1]
            for k in keys
            if k.startswith("template:") and k != "template:index"
        })
        await mcp.call_tool("kv_set", {"key": "template:index", "value": json.dumps(names, ensure_ascii=False)})
        return {"ok": True, "templates": names, "count": len(names)}

    @mcp.tool()
    async def tpl_list() -> Dict[str, Any]:
        """
        Enumerate templates directly from KV keys every time.
        Ignores/doesn't trust 'template:index'.
        """
        res = await mcp.call_tool("kv_list", {"prefix": "template:"})
    
        keys = (res.get("keys") if isinstance(res, dict) else []) or []
        names = sorted({
            k.split("template:", 1)[1]
            for k in keys
            if k.startswith("template:") and k != "template:index"
        })
        return {"ok": True, "templates": names, "kv_count": res.get("count")}



    @mcp.tool()
    async def tpl_delete(name: str) -> Dict[str, Any]:
        """Delete a template (body cleared; index updated)."""
        idx = await _kv_get(mcp, INDEX_KEY) or []
        if not isinstance(idx, list):
            idx = []
        if name not in idx:
            return {"ok": False, "reason": "not_found", "name": name}

        await _kv_set(mcp, TEMPLATE_KEY.format(name=name), "")
        idx = [n for n in idx if n != name]
        await _kv_set(mcp, INDEX_KEY, idx)
        return {"ok": True, "deleted": name}

    @mcp.tool()
    async def tpl_render(
        name: str,
        extra: Optional[Dict[str, Any]] = None,
        kv_keys: Optional[List[str]] = None,
        include_config: bool = True,
        save_as: Optional[str] = None,   # if provided, save via save_text
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        Render a saved template using data from:
          - extra: dict you pass in (wins last)
          - kv_keys: list of KV keys to inject as {<key>} (JSON auto-parsed)
          - cfg: current config (if include_config=True), exposed as {cfg.*} and flattened
        Optionally save the rendered text as an artifact file.
        """
        body = await _kv_get(mcp, TEMPLATE_KEY.format(name=name))
        if not isinstance(body, str) or not body:
            return {"ok": False, "reason": "template_not_found_or_empty", "name": name}

        ctx: Dict[str, Any] = {
            "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "profile": None,
        }
        if include_config:
            cfg = await config.load_config(mcp)
            ctx["cfg"] = cfg
            ctx["profile"] = cfg.get("profile")

        for k in (kv_keys or []):
            val = await _kv_get(mcp, k)
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    pass
            ctx[k] = val
            alias = k.replace(":", "_").replace("/", "_")
            ctx.setdefault("kv_alias", {})[alias] = val
            ctx.setdefault("kv", {})[k] = val
            if alias not in ctx:
                ctx[alias] = val

        if extra:
            ctx.update(extra)

        rendered = _safe_format(body, ctx)
        out: Dict[str, Any] = {"ok": True, "name": name, "rendered": rendered}

        if save_as:
            saved = await mcp.call_tool(
                "save_text",
                {"filename": save_as, "text": rendered, "overwrite": overwrite},
            )
            out["artifact"] = saved

        return out

    @mcp.tool()
    async def gen_incident_update(
        kind: str = "alert",
        template_name: Optional[str] = None,
        save_as: str = "incident_update.txt",
        overwrite: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate an email-ready update from latest artifacts:
          - kind="alert" → KV: 'alert:last_path' or 'alert:last_path:{profile}'
          - kind="watch" → KV: 'artifact:last_watch'
        If template_name is None, renders a sensible default.
        """
        cfg = await config.load_config(mcp)
        prof = cfg.get("profile", "dev")

        kv_candidates = (
            ["alert:last_path", f"alert:last_path:{prof}"]
            if kind == "alert"
            else ["artifact:last_watch"]
        )
        artifact_path = None
        for k in kv_candidates:
            val = await _kv_get(mcp, k)
            if val:
                artifact_path = val
                break

        art_text = ""
        if artifact_path:
            filename = str(artifact_path).split("/")[-1]  # read_artifact expects filename
            rd = await mcp.call_tool("read_artifact", {"filename": filename, "as_text": True})
            if isinstance(rd, dict) and rd.get("ok"):
                art_text = rd.get("text", "") or rd.get("preview", "") or ""

        if template_name:
            return await tpl_render(
                name=template_name,
                extra={"kind": kind, "artifact_path": artifact_path, "art_text": art_text},
                kv_keys=[],
                include_config=True,
                save_as=save_as,
                overwrite=overwrite,
            )

        default_tpl = (
            "Subject: Update — {kind} summary ({profile})\n\n"
            "Time (UTC): {now}\n"
            "Profile: {profile}\n"
            "Artifact: {artifact_path}\n\n"
            "Summary:\n{art_text}\n\n"
            "Next actions:\n- [ ] Confirm remediation\n- [ ] Notify stakeholders\n"
        )
        text = _safe_format(
            default_tpl,
            {
                "kind": kind,
                "profile": prof,
                "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "artifact_path": artifact_path or "(none)",
                "art_text": art_text,
            },
        )
        saved = await mcp.call_tool("save_text", {"filename": save_as, "text": text, "overwrite": overwrite})
        return {"ok": True, "saved": saved, "preview": text[:300]}
    
    @mcp.tool()
    def tpl_where() -> Dict[str, Any]:
        """Return the path of this templates module (to confirm which file is loaded)."""
        return {"ok": True, "module_file": __file__}

    @mcp.tool()
    async def tpl_debug() -> Dict[str, Any]:
        """Show raw KV state for templates namespace."""
        res = await mcp.call_tool("kv_list", {"prefix": "template:"})
        idx = await _kv_get(mcp, "template:index")
        return {"ok": True, "kv_list": res, "index_value": idx}

        # ---------- end of template tools ----------
