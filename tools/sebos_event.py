"""Emit structured Hermes events into sebOS Live Board inbox.

This is a local, file-based handoff. Hermes writes one JSON file per event into
~/.hermes/sebos/inbox/events/ and sebOS ingests it on its own schedule.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from tools.registry import registry

_ALLOWED_SOURCES = {
    "hermes",
    "sebos",
    "close",
    "whoop",
    "monarch",
    "journal",
    "location",
    "reminders",
    "calendar",
    "router",
}
_ALLOWED_LANES = {"Business", "Falconnect", "Personal", "Ideas"}
_ALLOWED_SEVERITIES = {"info", "notice", "warn", "block"}
_ALLOWED_KINDS = {
    "commitment.created",
    "commitment.updated",
    "commitment.cancelled",
    "task.completed",
    "outreach.sent",
    "meeting.held",
    "ship.released",
    "payment.cleared",
    "writeup.published",
    "journal.logged",
    "decision.made",
    "decision.reversed",
    "direction.set",
    "blocker.opened",
    "blocker.escalated",
    "blocker.cleared",
    "signal.health",
    "signal.location",
    "signal.finance",
    "signal.activity",
    "signal.weather",
    "signal.calendar",
    "pattern.detected",
    "meta.suppressed",
    "meta.rebuild",
    "meta.archive_frozen",
    "meta.suppression_set",
    "meta.suppression_cleared",
}
_SECRET_KEY_RE = re.compile(r"(token|secret|password|api_key|authorization)", re.IGNORECASE)
_MAX_PAYLOAD_BYTES = 32 * 1024


def _default_inbox_dir() -> Path:
    return get_hermes_home() / "sebos" / "inbox" / "events"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_string(value: Any, *, field: str, max_len: int | None = None, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    text = str(value).strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if not text:
        return None
    if max_len is not None and len(text) > max_len:
        text = text[:max_len]
    return text


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if _SECRET_KEY_RE.search(key_text):
                out[key_text] = "***redacted***"
            else:
                out[key_text] = _redact_payload(child)
        return out
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    return value


def _stable_event_uid(*, producer: str, kind: str, ts: str, subject: str, actor: str, counterparty: str | None, outcome: str | None) -> str:
    canonical = json.dumps(
        {
            "actor": actor,
            "counterparty": counterparty,
            "kind": kind,
            "outcome": outcome,
            "producer": producer,
            "subject": subject,
            "ts": ts,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    safe_producer = re.sub(r"[^A-Za-z0-9_.:-]+", "_", producer).strip("_:") or "hermes"
    return f"{safe_producer}:{digest}"


def _validate_payload(payload: dict[str, Any]) -> None:
    kind = payload["kind"]
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"invalid kind: {kind}")
    source = payload["source"]
    if source not in _ALLOWED_SOURCES:
        raise ValueError(f"invalid source: {source}")
    lane = payload.get("lane")
    if lane is not None and lane not in _ALLOWED_LANES:
        raise ValueError(f"invalid lane: {lane}")
    severity = payload.get("severity") or "info"
    if severity not in _ALLOWED_SEVERITIES:
        raise ValueError(f"invalid severity: {severity}")
    weight = payload.get("weight", 0)
    if not isinstance(weight, int) or weight < 0 or weight > 200:
        raise ValueError("weight must be an integer from 0 to 200")
    serialized = json.dumps(payload.get("payload") or {}, sort_keys=True, default=str).encode("utf-8")
    if len(serialized) > _MAX_PAYLOAD_BYTES:
        raise ValueError("payload exceeds 32KB serialized limit")


def emit(
    *,
    kind: str,
    subject: str,
    summary: str,
    lane: str | None = None,
    actor: str = "seb",
    counterparty: str | None = None,
    outcome: str | None = None,
    evidence_uri: str | None = None,
    parent_event_uid: str | None = None,
    weight: int = 0,
    severity: str = "info",
    due_at: str | None = None,
    payload: dict[str, Any] | None = None,
    producer: str = "hermes:agent",
    source: str = "hermes",
    ts: str | None = None,
    event_uid: str | None = None,
    inbox_dir: str | Path | None = None,
) -> str:
    """Write one structured event JSON file into sebOS's inbox and return event_uid."""
    clean_kind = _clean_string(kind, field="kind", required=True)
    clean_subject = _clean_string(subject, field="subject", max_len=200, required=True)
    clean_summary = _clean_string(summary, field="summary", required=True)
    assert clean_kind is not None
    assert clean_subject is not None
    assert clean_summary is not None
    clean_actor = _clean_string(actor, field="actor") or "seb"
    clean_producer = _clean_string(producer, field="producer") or "hermes:agent"
    clean_source = _clean_string(source, field="source") or "hermes"
    clean_ts = _clean_string(ts, field="ts") or _now_iso()
    clean_payload = _redact_payload(payload or {})
    uid = _clean_string(event_uid, field="event_uid") or _stable_event_uid(
        producer=clean_producer,
        kind=clean_kind,
        ts=clean_ts,
        subject=clean_subject,
        actor=clean_actor,
        counterparty=_clean_string(counterparty, field="counterparty"),
        outcome=_clean_string(outcome, field="outcome"),
    )

    event = {
        "schema_version": 1,
        "event_uid": uid,
        "ts": clean_ts,
        "source": clean_source,
        "producer": clean_producer,
        "kind": clean_kind,
        "lane": _clean_string(lane, field="lane"),
        "subject": clean_subject,
        "actor": clean_actor,
        "counterparty": _clean_string(counterparty, field="counterparty"),
        "outcome": _clean_string(outcome, field="outcome"),
        "summary": clean_summary,
        "evidence_uri": _clean_string(evidence_uri, field="evidence_uri"),
        "parent_event_uid": _clean_string(parent_event_uid, field="parent_event_uid"),
        "weight": int(weight),
        "severity": _clean_string(severity, field="severity") or "info",
        "due_at": _clean_string(due_at, field="due_at"),
        "payload": clean_payload,
    }
    # Keep explicit nulls in the JSON because sebOS schema validation accepts
    # them and they make the contract stable/readable.
    _validate_payload(event)

    inbox = Path(inbox_dir) if inbox_dir is not None else _default_inbox_dir()
    tmp_dir = inbox / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    unique = uuid.uuid4().hex
    safe_ts = clean_ts.replace(":", "").replace("+", "Z")
    tmp_path = tmp_dir / f"{unique}.json"
    final_path = inbox / f"{safe_ts}-{unique}.json"
    tmp_path.write_text(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp_path, final_path)
    return uid


SEBOS_EVENT_SCHEMA = {
    "name": "sebos_event",
    "description": (
        "Record a meaningful operational fact for Seb's sebOS Live Board. "
        "Use only for concrete decisions, commitments, completions, blockers, material work shipped, "
        "or behavior patterns. Do not record raw token counts, tool calls, internal planning, or every chat turn."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": sorted(_ALLOWED_KINDS)},
            "subject": {"type": "string", "description": "Short noun phrase, max 200 chars."},
            "summary": {"type": "string", "description": "One operator-facing plain-text sentence."},
            "lane": {"type": "string", "enum": sorted(_ALLOWED_LANES)},
            "actor": {"type": "string", "default": "seb"},
            "counterparty": {"type": "string"},
            "outcome": {"type": "string"},
            "evidence_uri": {"type": "string"},
            "parent_event_uid": {"type": "string"},
            "weight": {"type": "integer", "minimum": 0, "maximum": 200, "default": 0},
            "severity": {"type": "string", "enum": sorted(_ALLOWED_SEVERITIES), "default": "info"},
            "due_at": {"type": "string"},
            "payload": {"type": "object", "additionalProperties": True},
        },
        "required": ["kind", "subject", "summary"],
    },
}


def check_sebos_event_requirements() -> bool:
    return (get_hermes_home() / "sebos").exists()


def sebos_event_tool(args: dict[str, Any], **_: Any) -> str:
    try:
        event_uid = emit(**args)
    except Exception as exc:  # noqa: BLE001 - tool must return JSON, not raise to model.
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps({"success": True, "event_uid": event_uid}, ensure_ascii=False)


registry.register(
    name="sebos_event",
    toolset="sebos",
    schema=SEBOS_EVENT_SCHEMA,
    handler=lambda args, **kw: sebos_event_tool(args, **kw),
    check_fn=check_sebos_event_requirements,
    description="Record high-signal operational events for sebOS Live Board",
    emoji="📋",
)


__all__ = ["emit", "sebos_event_tool", "check_sebos_event_requirements", "SEBOS_EVENT_SCHEMA"]
