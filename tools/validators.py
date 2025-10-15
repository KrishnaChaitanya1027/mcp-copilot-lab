"""Quick input sanity validators for certs, rate limits, and IdP metadata."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from mcp.server.fastmcp import FastMCP


def _summarize(findings: List[str], errors: List[str]) -> str:
    """Reduce detailed findings down to a one-liner."""
    if errors:
        return f"{len(errors)} error(s), {len(findings)} finding(s)"
    return f"{len(findings)} finding(s), no errors"


def _wrap_response(ok: bool, findings: List[str], errors: List[str]) -> Dict[str, Any]:
    """Consistent payload of validation results."""
    return {
        "ok": ok,
        "findings": findings,
        "errors": errors,
        "summary": _summarize(findings, errors),
    }


def register_validator_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def validate_cert_chain(pem_text: str) -> Dict[str, Any]:
        """Confirm PEM formatting basics such as block counts and pairing."""
        text = (pem_text or "").strip()
        findings: List[str] = []
        errors: List[str] = []

        if not text:
            errors.append("Input is empty")
            return _wrap_response(False, findings, errors)

        begins = re.findall(r"-----BEGIN CERTIFICATE-----", text)
        ends = re.findall(r"-----END CERTIFICATE-----", text)
        findings.append(f"BEGIN blocks: {len(begins)}")
        findings.append(f"END blocks: {len(ends)}")

        if len(begins) != len(ends):
            errors.append("Mismatched BEGIN/END certificate blocks")
        if "BEGIN CERTIFICATE" not in text:
            errors.append("No certificate blocks detected")

        return _wrap_response(not errors, findings, errors)

    @mcp.tool()
    def validate_rate_limits(config_json: str) -> Dict[str, Any]:
        """Check rate-limit JSON for sane integer fields."""
        findings: List[str] = []
        errors: List[str] = []
        data: Dict[str, Any] = {}

        try:
            data = json.loads(config_json or "{}")
        except json.JSONDecodeError as exc:
            errors.append(f"JSON parse error: {exc}")
            return _wrap_response(False, findings, errors)

        if not isinstance(data, dict):
            errors.append("Top-level JSON must be an object")
            return _wrap_response(False, findings, errors)

        for key, value in data.items():
            if not isinstance(value, int):
                errors.append(f"{key}: expected integer, got {type(value).__name__}")
                continue
            if value <= 0:
                errors.append(f"{key}: must be positive")
            elif value > 1_000_000:
                findings.append(f"{key}: unusually high value ({value})")
            else:
                findings.append(f"{key}: ok ({value})")

        return _wrap_response(not errors, findings, errors)

    @mcp.tool()
    def validate_idp_metadata(xml_text: str) -> Dict[str, Any]:
        """Look for key IdP metadata markers without full XML parsing."""
        text = (xml_text or "").strip()
        findings: List[str] = []
        errors: List[str] = []

        if not text:
            errors.append("Input is empty")
            return _wrap_response(False, findings, errors)

        entity_id_match = re.search(r'EntityID="([^"]+)"', text, re.IGNORECASE)
        if entity_id_match:
            findings.append(f"EntityID present ({entity_id_match.group(1)})")
        else:
            errors.append("EntityID attribute missing")

        cert_matches = re.findall(r"<X509Certificate>([^<]+)</X509Certificate>", text, re.IGNORECASE)
        findings.append(f"X509Certificate count: {len(cert_matches)}")
        if not cert_matches:
            errors.append("No X509Certificate elements found")

        return _wrap_response(not errors, findings, errors)
