"""
Photon Spectrum (iMessage) platform adapter for Hermes Agent.

Both directions of traffic flow through a small supervised Node sidecar
(see ``sidecar/index.mjs``) that runs the ``spectrum-ts`` SDK — the SDK is
TypeScript-only and there is no public HTTP message API, so a sidecar is
unavoidable.

Inbound:
    The SDK's ``app.messages`` is a long-lived **gRPC** stream. The sidecar
    serializes each message to a normalized JSON event and streams it to this
    adapter over a loopback ``GET /inbound`` (NDJSON). A background task here
    consumes that stream, dedupes on ``messageId``, and dispatches a
    ``MessageEvent`` to the gateway via ``BasePlatformAdapter.handle_message``.
    No webhook, no public URL, no signing secret.

Outbound:
    ``send`` posts to the sidecar's loopback control endpoint,
    authenticated with a shared bearer token. Typing indicators and selective
    ack reactions are opt-in because iMessage is Seb's clean personal inbox.
    Outbound media (images, voice notes, video, documents) goes through
    spectrum-ts'
    ``attachment()`` / ``voice()`` content builders via the sidecar's
    ``/send-attachment`` endpoint.
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    # Type checkers see ``httpx`` as the always-imported module, so every use
    # site type-checks cleanly. The runtime fallback below keeps the optional
    # dependency truly optional (each use site is guarded by HTTPX_AVAILABLE).
    import httpx
    HTTPX_AVAILABLE = True
else:
    try:
        import httpx
        HTTPX_AVAILABLE = True
    except ImportError:  # pragma: no cover - httpx is already a Hermes dep
        HTTPX_AVAILABLE = False
        httpx = None

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    ProcessingOutcome,
    SendResult,
)
from gateway.platforms.helpers import strip_markdown

from .auth import load_project_credentials

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants

_DEFAULT_SIDECAR_PORT = 8789
_DEFAULT_SIDECAR_BIND = "127.0.0.1"
_PHOTON_SPECTRUM_API_BASE = "https://spectrum.photon.codes"

# Photon iMessage messages from the SDK side have no documented hard
# limit, but the underlying iMessage protocol limits practical message
# size to ~16 KB.  Keep a conservative cap that matches iMessage delivery limits.
_MAX_MESSAGE_LENGTH = 8000

# Dedup parameters — the gRPC stream is at-least-once, and a sidecar
# reconnect can replay, so keep at least 1k ids for ~48h.
_DEDUP_MAX_SIZE = 4000
_DEDUP_WINDOW_SECONDS = 48 * 3600

_SIDECAR_DIR = Path(__file__).parent / "sidecar"
_SEBOS_ROOT = Path.home() / ".hermes" / "sebos"
_SEBOS_BIN_DIR = _SEBOS_ROOT / "bin"
_SEBOS_DB_PATH = _SEBOS_ROOT / "sebos.db"
_SEBOS_AUDIO_INBOX = _SEBOS_ROOT / "inbox" / "audio"
_DOCUMENT_CACHE_DIR = Path.home() / ".hermes" / "cache" / "documents"
_AUDIO_CACHE_DIRS = (
    Path.home() / ".hermes" / "audio_cache",
    Path.home() / ".hermes" / "cache" / "audio",
)
_HERMES_SEBOS_PHOTON_BOUNDARY = Path.home() / ".hermes" / "plugins" / "hermes-sebos" / "photon_boundary.py"
_SEBOS_FALLBACK_COMMAND_ALLOWLIST = frozenset(
    {
        "sebos-route-command",
        "sebos-board-query",
        "sebos-render-mission-control",
        "sebos-journal-pending-prompt",
        "sebos-add-reminder",
        "sebos-update-reminder",
        "sebos-ingest-journal",
    }
)
_THREAD_START_RE = re.compile(r"^\s*(?:t|thread)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
_THREAD_CONTINUE_RE = re.compile(r"^\s*t\+\s*:?\s*(.*)$", re.IGNORECASE | re.DOTALL)

# Internal-notice text that must never reach the user's iMessage inbox. iMessage
# is a clean personal channel, so any leaked gateway/runtime chatter is replaced
# with a neutral acknowledgement instead of being sent verbatim.
_PHOTON_INTERNAL_NOTICE_RE = re.compile(
    r"(?:Codex gpt-5\.5 caps context|auto-compaction was raised|hermes config set|tool call|tool_call|function call|status_callback|context compression|We need answer|Need load skill|maybe no tool|Load FC skills)",
    re.IGNORECASE,
)


def _outbound_sanitize(text: str) -> str:
    """Shape a final assistant reply before it is sent over Photon/iMessage.

    Redacts secrets (shared gateway helper) and suppresses internal-notice
    text so runtime chatter never lands in the clean personal inbox.
    """
    from gateway.outbound_sanitize import redact_user_facing_secrets

    redacted = redact_user_facing_secrets(str(text))
    if _PHOTON_INTERNAL_NOTICE_RE.search(redacted):
        return "Received."
    return redacted

# Group-chat mention wake words. When ``require_mention`` is enabled, group
# messages are ignored unless they match one of these patterns — same
# behavior and defaults as iMessage channels so the two
# iMessage adapters gate group chats identically.
_DEFAULT_MENTION_PATTERNS = [
    r"(?<![\w@])@?hermes\s+agent\b[,:\-]?",
    r"(?<![\w@])@?hermes\b[,:\-]?",
]


def _load_sebos_photon_boundary() -> Any | None:
    """Load the hermes-sebos Photon facade without changing plugin enablement."""
    if not _HERMES_SEBOS_PHOTON_BOUNDARY.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "hermes_sebos_photon_boundary",
            _HERMES_SEBOS_PHOTON_BOUNDARY,
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        logger.warning("[photon] hermes-sebos Photon boundary unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Module-level helpers — also used by check_fn / standalone send

def _coerce_port(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def check_requirements() -> bool:
    """Return True when both Python deps and the Node sidecar are available."""
    if not HTTPX_AVAILABLE:
        return False
    if not shutil.which(os.getenv("PHOTON_NODE_BIN") or "node"):
        return False
    if not (_SIDECAR_DIR / "node_modules").exists():
        # spectrum-ts not installed yet — `hermes photon setup` will
        # install it.  check_fn still returns False so the gateway
        # surfaces the missing-deps state in `hermes setup` / status.
        return False
    return True


def validate_config(cfg: PlatformConfig) -> bool:
    extra = cfg.extra or {}
    project_id = extra.get("project_id") or os.getenv("PHOTON_PROJECT_ID")
    project_secret = extra.get("project_secret") or os.getenv("PHOTON_PROJECT_SECRET")
    if not project_id or not project_secret:
        # Fall back to auth.json
        stored_id, stored_sec = load_project_credentials()
        return bool(stored_id and stored_sec)
    return True


def is_connected(cfg: PlatformConfig) -> bool:
    return validate_config(cfg)


def _env_enablement() -> Optional[dict]:
    """Seed PlatformConfig.extra from env so env-only setups appear in status.

    The special ``home_channel`` key is handled by the core plugin hook and
    becomes a proper ``HomeChannel`` on ``PlatformConfig``.
    """
    project_id, project_secret = load_project_credentials()
    if not (project_id and project_secret):
        return None
    seed: dict = {"project_id": project_id, "project_secret": project_secret}
    home = os.getenv("PHOTON_HOME_CHANNEL", "").strip()
    if home:
        seed["home_channel"] = {
            "chat_id": home,
            "name": os.getenv("PHOTON_HOME_CHANNEL_NAME", "Home"),
        }
    return seed


def _markdown_enabled() -> bool:
    """Send agent replies as markdown (spectrum-ts ``markdown()`` builder).

    iMessage renders it natively; other Spectrum platforms degrade to
    readable plain text. On-device rendering can't be unit-tested, so
    ``PHOTON_MARKDOWN=false`` is the kill-switch back to stripped plain
    text without a release.
    """
    return os.getenv("PHOTON_MARKDOWN", "true").strip().lower() not in {
        "false", "0", "no",
    }


_TRUTHY_ENV = {"true", "1", "yes", "on"}


def _photon_auth_env_value(key: str) -> str:
    """Read Photon auth env using Hermes' config-backed env helper when present."""
    try:
        from hermes_cli.config import get_env_value
    except Exception:
        return os.getenv(key, "") or ""
    return get_env_value(key) or os.getenv(key, "") or ""


def _normalize_photon_identity(value: Any) -> str:
    """Normalize Spectrum/iMessage sender or space identifiers for allowlists."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("any;-;"):
        raw = raw[len("any;-;"):]
    elif raw.startswith("iMessage;-;"):
        raw = raw[len("iMessage;-;"):]
    return raw.strip()


def _photon_allowed_user_candidates(*values: Any) -> set[str]:
    candidates: set[str] = set()
    for value in values:
        normalized = _normalize_photon_identity(value)
        if normalized:
            candidates.add(normalized)
    return candidates


# ---------------------------------------------------------------------------
# Adapter

class PhotonAdapter(BasePlatformAdapter):
    """Bidirectional bridge to Photon Spectrum via the Node spectrum-ts sidecar.

    Inbound: consume the sidecar's ``/inbound`` gRPC stream.
    Outbound: loopback POSTs to the sidecar's control channel.
    """

    MAX_MESSAGE_LENGTH = _MAX_MESSAGE_LENGTH
    SUPPORTS_MESSAGE_EDITING = False

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform("photon"))
        extra = config.extra or {}

        # Project credentials (env wins, then config.extra, then auth.json).
        # ``project_id`` here is the project's spectrumProjectId — the value
        # the spectrum-ts SDK authenticates with.
        stored_id, stored_sec = load_project_credentials()
        self._project_id: str = (
            os.getenv("PHOTON_PROJECT_ID")
            or extra.get("project_id")
            or stored_id
            or ""
        )
        self._project_secret: str = (
            os.getenv("PHOTON_PROJECT_SECRET")
            or extra.get("project_secret")
            or stored_sec
            or ""
        )

        # Sidecar
        self._sidecar_port = _coerce_port(
            extra.get("sidecar_port") or os.getenv("PHOTON_SIDECAR_PORT"),
            _DEFAULT_SIDECAR_PORT,
        )
        self._sidecar_bind = _DEFAULT_SIDECAR_BIND
        self._sidecar_token = (
            os.getenv("PHOTON_SIDECAR_TOKEN") or secrets.token_hex(16)
        )
        self._autostart_sidecar = str(
            os.getenv("PHOTON_SIDECAR_AUTOSTART", "true")
        ).lower() not in ("0", "false", "no")
        self._node_bin = os.getenv("PHOTON_NODE_BIN") or shutil.which("node") or "node"
        self._sebos_rules_enabled = str(
            extra.get("sebos_rules") or os.getenv("PHOTON_SEBOS_RULES", "false")
        ).strip().lower() in {"true", "1", "yes", "on"}
        intent_gate_cfg = extra.get("intent_gate")
        if intent_gate_cfg is None:
            intent_gate_cfg = os.getenv("PHOTON_INTENT_GATE", "false")
        self._intent_gate_enabled = str(intent_gate_cfg).strip().lower() in {
            "true", "1", "yes", "on"
        }
        self._intent_gate_provider = str(
            extra.get("intent_gate_provider")
            or os.getenv("PHOTON_INTENT_GATE_PROVIDER")
            or "openai-codex"
        ).strip()
        self._intent_gate_model = str(
            extra.get("intent_gate_model")
            or os.getenv("PHOTON_INTENT_GATE_MODEL")
            or "gpt-5.5"
        ).strip()
        self._intent_gate_min_confidence = float(
            extra.get("intent_gate_min_confidence")
            or os.getenv("PHOTON_INTENT_GATE_MIN_CONFIDENCE")
            or 0.86
        )
        # Photon/Spectrum iMessage typing indicators currently route through
        # Spectrum's typing() content, which calls the low-level
        # ChatsResource.setTyping RPC. That endpoint has proven unreliable on
        # shared Photon routes and can drop calls/log noisy upstream failures.
        # Keep this hard-disabled until a safe implementation exists; user
        # config/env cannot accidentally re-enable the broken path.
        self._typing_indicators_enabled = False
        self._ack_reactions_enabled = str(
            extra.get("ack_reactions")
            or os.getenv("PHOTON_ACK_REACTIONS", "false")
        ).strip().lower() in {"true", "1", "yes", "on"}

        # With markdown on, format_message preserves fences and the sidecar's
        # markdown() builder renders them (or degrades them readably).
        self.supports_code_blocks = _markdown_enabled()

        # Runtime state
        self._sidecar_proc: Optional[subprocess.Popen] = None
        self._sidecar_supervisor_task: Optional[asyncio.Task] = None
        self._inbound_task: Optional[asyncio.Task] = None
        self._inbound_running = False
        self._http_client: Optional["httpx.AsyncClient"] = None
        # Lightweight in-memory dedup. The gRPC stream is at-least-once, so we
        # may see the same messageId more than once (e.g. after a reconnect).
        self._seen_messages: Dict[str, float] = {}
        # Ids of messages WE sent (bounded, insertion-order eviction). Inbound
        # reaction events are only routed to the agent when they target one of
        # these — a tapback on a human↔human message is not addressed to us.
        self._sent_message_ids: Dict[str, float] = {}
        # Latest inbound message id per chat (bounded). Lets the agent-facing
        # react action default to "the message that triggered me" without
        # requiring the model to thread message ids through tool calls.
        self._last_inbound_by_chat: Dict[str, str] = {}
        # Photon/iMessage thread rails. ``t:`` creates a virtual Hermes thread
        # keyed by the triggering inbound message id. Outbound replies are
        # mapped back to that root so native replies to the bot resume the same
        # Hermes session instead of polluting the main command lane.
        self._sent_thread_roots: Dict[str, str] = {}
        self._last_thread_root_by_chat: Dict[str, str] = {}

        # Group-chat mention gating (iMessage parity). When enabled,
        # group messages are ignored unless they match a wake word; DMs are
        # always processed. Config key wins, then env var.
        _require_mention = extra.get("require_mention")
        if _require_mention is None:
            _require_mention = os.getenv("PHOTON_REQUIRE_MENTION")
        self.require_mention = str(_require_mention).strip().lower() in {
            "true", "1", "yes", "on",
        }
        self._mention_patterns = self._compile_mention_patterns(
            extra["mention_patterns"]
            if "mention_patterns" in extra
            else os.getenv("PHOTON_MENTION_PATTERNS")
        )

    def _is_photon_user_allowed_for_sebos(
        self,
        *,
        sender_id: Any = None,
        space_phone: Any = None,
        space_id: Any = None,
    ) -> bool:
        """Fail-closed pre-gateway auth for sebOS Photon side effects.

        Photon sebOS shortcuts execute before the normal gateway
        ``PHOTON_ALLOWED_USERS`` check. Mirror the gateway's Photon auth knobs
        here so audio journal ingest, natural-intent routing, and explicit
        sebOS rules cannot mutate state or send acknowledgements for an
        unauthorized sender.
        """
        if _photon_auth_env_value("PHOTON_ALLOW_ALL_USERS").strip().lower() in _TRUTHY_ENV:
            return True

        raw_allowed = _photon_auth_env_value("PHOTON_ALLOWED_USERS").strip()
        if not raw_allowed:
            return False

        allowed = {
            _normalize_photon_identity(part)
            for part in re.split(r"[,\n]", raw_allowed)
            if _normalize_photon_identity(part)
        }
        if "*" in allowed:
            return True

        candidates = _photon_allowed_user_candidates(sender_id, space_phone, space_id)
        return bool(candidates & allowed)

    # -- Group-mention gating (iMessage parity) -------------------

    @staticmethod
    def _compile_mention_patterns(raw: Any) -> "list[re.Pattern]":
        """Compile group-mention wake words from config/env.

        ``raw`` is a list (config or env JSON), a string (env var: JSON
        list, or comma/newline-separated), or None (use Hermes defaults).
        Matches iMessage behavior so Photon
        accept the same configuration shapes.
        """
        if raw is None:
            patterns = list(_DEFAULT_MENTION_PATTERNS)
        elif isinstance(raw, str):
            text = raw.strip()
            try:
                loaded = json.loads(text) if text else []
            except Exception:
                loaded = None
            patterns = loaded if isinstance(loaded, list) else [
                part.strip()
                for line in text.splitlines()
                for part in line.split(",")
            ]
        elif isinstance(raw, list):
            patterns = raw
        else:
            patterns = [raw]

        compiled: "list[re.Pattern]" = []
        for pattern in patterns:
            text = str(pattern).strip()
            if not text:
                continue
            try:
                compiled.append(re.compile(text, re.IGNORECASE))
            except re.error as exc:
                logger.warning("[photon] Invalid mention pattern %r: %s", text, exc)
        return compiled

    def _message_matches_mention_patterns(self, text: str) -> bool:
        if not text or not self._mention_patterns:
            return False
        return any(pattern.search(text) for pattern in self._mention_patterns)

    def _clean_mention_text(self, text: str) -> str:
        """Strip a leading wake word before dispatch.

        Custom mention patterns are regexes, so we only strip a leading
        match to avoid deleting ordinary words later in the prompt.
        """
        if not text:
            return text
        for pattern in self._mention_patterns:
            match = pattern.match(text.lstrip())
            if match:
                cleaned = text.lstrip()[match.end():].lstrip(" ,:-")
                return cleaned or text
        return text

    async def _run_sebos_json(
        self,
        *args: str,
        stdin: Optional[str] = None,
        timeout: float = 20.0,
    ) -> Dict[str, Any]:
        if not args or not args[0]:
            return {
                "status": "error",
                "error_layer": "router",
                "error": "missing sebOS command",
                "returncode": 127,
            }
        command = args[0]
        if command not in _SEBOS_FALLBACK_COMMAND_ALLOWLIST:
            return {
                "status": "error",
                "error_layer": "router",
                "error": "sebOS fallback command not allowed",
                "returncode": 126,
            }
        exe = _SEBOS_BIN_DIR / command
        if not exe.exists():
            return {"status": "error", "error": f"missing sebOS command: {exe}"}
        proc = await asyncio.create_subprocess_exec(
            str(exe),
            *args[1:],
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_SEBOS_BIN_DIR.parent),
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin.encode() if stdin is not None else None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"status": "error", "error": f"sebOS command timed out: {command}"}
        raw = out.decode("utf-8", "replace").strip()
        stderr = err.decode("utf-8", "replace").strip()
        try:
            parsed = json.loads(raw) if raw else {}
            data: Dict[str, Any] = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except json.JSONDecodeError:
            data = {"status": "ok" if proc.returncode == 0 else "error", "raw": raw}
        if stderr:
            data["stderr"] = stderr
        data["returncode"] = proc.returncode
        return data

    async def _route_explicit_sebos_command(self, text: str) -> Dict[str, Any]:
        """Route explicit sebOS command text through plugin facade with fallback."""
        boundary = _load_sebos_photon_boundary()
        route_text_command = getattr(boundary, "route_text_command", None) if boundary else None
        if route_text_command is not None:
            try:
                return await route_text_command(
                    text,
                    write=True,
                    db_path=str(_SEBOS_DB_PATH),
                    channel="imessage",
                    timeout=45.0,
                )
            except Exception as exc:
                logger.warning(
                    "[photon] hermes-sebos route facade failed; falling back: %s",
                    exc,
                )
        return await self._run_sebos_json(
            "sebos-route-command",
            "--text", "-",
            "--write",
            "--db", str(_SEBOS_DB_PATH),
            "--json",
            stdin=text,
            timeout=45.0,
        )

    async def _render_mission_control(self) -> Dict[str, Any]:
        """Render Mission Control through plugin facade with fallback."""
        boundary = _load_sebos_photon_boundary()
        render_mission_control = getattr(boundary, "render_mission_control", None) if boundary else None
        if render_mission_control is not None:
            try:
                return await render_mission_control(dry_run=True, timeout=25.0)
            except Exception as exc:
                logger.warning(
                    "[photon] hermes-sebos Mission Control facade failed; falling back: %s",
                    exc,
                )
        return await self._run_sebos_json(
            "sebos-render-mission-control",
            "--dry-run",
            "--json",
            timeout=25.0,
        )

    async def _board_query(self, command: str, *args: str) -> Dict[str, Any]:
        """Read Live Board state through the plugin facade with fallback."""
        boundary = _load_sebos_photon_boundary()
        board_query = getattr(boundary, "board_query", None) if boundary else None
        if board_query is not None:
            try:
                return await board_query(command, *args, timeout=25.0)
            except Exception as exc:
                logger.warning(
                    "[photon] hermes-sebos board query facade failed; falling back: %s",
                    exc,
                )
        return await self._run_sebos_json(
            "sebos-board-query",
            "--json",
            command,
            *args,
            timeout=25.0,
        )

    async def _send_quiet(
        self,
        chat_id: str,
        text: str,
        *,
        reply_to: Optional[str] = None,
    ) -> None:
        result = await self._send_with_retry(
            chat_id,
            text,
            reply_to=reply_to,
            max_retries=3,
            base_delay=2.0,
        )
        if not result.success:
            logger.warning("[photon] sebOS rule reply failed: %s", result.error)

    async def _mission_control_text(self) -> str:
        data = await self._board_query("snapshot")
        body = data.get("body") or data.get("raw") or "Mission Control unavailable."
        return str(body).strip()

    @staticmethod
    def _lines_payload_text(payload: Dict[str, Any], key: str, *, empty: str) -> str:
        lines = payload.get(key)
        if not isinstance(lines, list):
            lines = payload.get("lines")
        if not isinstance(lines, list) or not lines:
            return empty
        rendered = "\n".join(f"- {str(item).strip()}" for item in lines if str(item).strip())
        return rendered or empty

    @staticmethod
    def _section_from_board(body: str, label: str, max_items: int) -> str:
        lines = body.splitlines()
        items: List[str] = []
        in_section = False
        for line in lines:
            stripped = line.strip()
            if stripped == label:
                in_section = True
                continue
            if in_section:
                if not stripped:
                    break
                if stripped.startswith("- "):
                    items.append(stripped[2:].strip())
                elif stripped.isupper() and len(stripped) < 40:
                    break
                else:
                    items.append(stripped)
        if not items:
            return f"{label}: empty"
        return f"{label}:\n" + "\n".join(f"- {item}" for item in items[:max_items])

    async def _copy_audio_to_sebos_inbox(
        self,
        path: str,
        message_id: Optional[str],
    ) -> Optional[str]:
        src = Path(path)
        if not src.exists():
            return None
        _SEBOS_AUDIO_INBOX.mkdir(parents=True, exist_ok=True)
        suffix = src.suffix or ".m4a"
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", message_id or str(uuid.uuid4()))[:120]
        dest = _SEBOS_AUDIO_INBOX / f"{safe_id}{suffix}"
        if dest.exists():
            return str(dest)
        try:
            shutil.copy2(src, dest)
            return str(dest)
        except Exception as exc:
            logger.warning("[photon] failed to copy audio into sebOS inbox: %s", exc)
            return None

    def _ack_reactions_enabled_for_sebos(self) -> bool:
        return bool(self._ack_reactions_enabled)

    async def _send_ack_reaction(
        self,
        chat_id: str,
        message_id: Optional[str],
        emoji: str,
    ) -> bool:
        if not self._ack_reactions_enabled_for_sebos() or not message_id:
            return False
        for attempt in range(1, 5):
            if await self._add_reaction(chat_id, message_id, emoji):
                return True
            if attempt < 4:
                delay = 1.5 * attempt
                logger.warning(
                    "[photon] ack reaction failed (attempt %d/4), retrying in %.1fs",
                    attempt,
                    delay,
                )
                await asyncio.sleep(delay)
        return False

    @staticmethod
    def _sebos_ack_emoji(result: Dict[str, Any]) -> Optional[str]:
        """Return the silent confirmation tapback for deterministic sebOS writes."""
        if str(result.get("status") or "") != "ok" or not result.get("mutated"):
            return None
        intent = str(result.get("intent") or "")
        if intent == "journal":
            return "❤️"
        if intent in {
            "reminder",
            "note",
            "suppress",
            "unsuppress",
            "done_working",
        }:
            return "👍"
        return None

    async def _active_journal_prompt_result(self, message_dt: datetime) -> Dict[str, Any]:
        """Probe active journal prompt through plugin facade with fallback."""
        at = message_dt.isoformat()
        boundary = _load_sebos_photon_boundary()
        active_journal_prompt_date = getattr(boundary, "active_journal_prompt_date", None) if boundary else None
        if active_journal_prompt_date is not None:
            try:
                return await active_journal_prompt_date(
                    at,
                    db_path=str(_SEBOS_DB_PATH),
                    timeout=20.0,
                )
            except Exception as exc:
                logger.warning(
                    "[photon] hermes-sebos active journal facade failed; falling back: %s",
                    exc,
                )
        return await self._run_sebos_json(
            "sebos-journal-pending-prompt",
            "--at", at,
            "--db", str(_SEBOS_DB_PATH),
            "--json",
        )

    async def _active_journal_prompt_date(self, message_dt: datetime) -> Optional[str]:
        result = await self._active_journal_prompt_result(message_dt)
        date = result.get("date")
        if isinstance(date, str) and date.strip():
            return date.strip()
        return None

    async def _add_reminder(self, payload: Dict[str, str]) -> Dict[str, Any]:
        """Add a reminder through plugin facade with fallback."""
        boundary = _load_sebos_photon_boundary()
        add_reminder = getattr(boundary, "add_reminder", None) if boundary else None
        if add_reminder is not None:
            try:
                return await add_reminder(
                    payload["title"],
                    due=payload.get("due"),
                    location=payload.get("location"),
                    latitude=payload.get("latitude"),
                    longitude=payload.get("longitude"),
                    radius=payload.get("radius"),
                    proximity=payload.get("proximity"),
                    timeout=45.0,
                )
            except Exception as exc:
                logger.warning(
                    "[photon] hermes-sebos reminder facade failed; falling back: %s",
                    exc,
                )
        return await self._run_sebos_json(
            *self._reminder_payload_args(payload),
            timeout=45.0,
        )

    async def _update_reminder(self, payload: Dict[str, str]) -> Dict[str, Any]:
        """Update a reminder through plugin facade with fallback."""
        boundary = _load_sebos_photon_boundary()
        update_reminder = getattr(boundary, "update_reminder", None) if boundary else None
        if update_reminder is not None:
            try:
                return await update_reminder(
                    payload["query"],
                    due=payload.get("due"),
                    title=payload.get("title"),
                    timeout=45.0,
                )
            except Exception as exc:
                logger.warning(
                    "[photon] hermes-sebos reminder update facade failed; falling back: %s",
                    exc,
                )
        return await self._run_sebos_json(
            *self._reminder_update_payload_args(payload),
            timeout=45.0,
        )

    async def _ingest_journal_payload(
        self,
        payload_path: str,
        *,
        sender_id: str,
        entry_date: str | None = None,
    ) -> Dict[str, Any]:
        """Ingest a prepared journal payload through plugin facade with fallback."""
        boundary = _load_sebos_photon_boundary()
        ingest_journal = getattr(boundary, "ingest_journal", None) if boundary else None
        if ingest_journal is not None:
            try:
                kwargs: Dict[str, Any] = {
                    "source": "photon",
                    "sender": sender_id,
                    "timeout": 360.0,
                }
                if entry_date:
                    kwargs["date"] = entry_date
                return await ingest_journal(payload_path, **kwargs)
            except TypeError as exc:
                logger.warning(
                    "[photon] hermes-sebos journal facade signature failed; falling back: %s",
                    exc,
                )
            except Exception as exc:
                logger.warning(
                    "[photon] hermes-sebos journal ingest facade failed; falling back: %s",
                    exc,
                )
        args = [
            "sebos-ingest-journal",
            payload_path,
            "--source", "photon",
            "--sender", sender_id,
        ]
        if entry_date:
            args.extend(["--date", entry_date])
        return await self._run_sebos_json(*args, timeout=360.0)

    @staticmethod
    def _reminder_payload_args(payload: Dict[str, str]) -> List[str]:
        args = ["sebos-add-reminder", payload["title"]]
        if payload.get("due"):
            args.extend(["--due", payload["due"]])
        if payload.get("location"):
            args.extend(["--location", payload["location"]])
        if payload.get("latitude"):
            args.extend(["--latitude", payload["latitude"]])
        if payload.get("longitude"):
            args.extend(["--longitude", payload["longitude"]])
        if payload.get("radius"):
            args.extend(["--radius", payload["radius"]])
        if payload.get("proximity"):
            args.extend(["--proximity", payload["proximity"]])
        return args

    @staticmethod
    def _reminder_update_payload_args(payload: Dict[str, str]) -> List[str]:
        args = ["sebos-update-reminder", payload["query"]]
        if payload.get("due"):
            args.extend(["--due", payload["due"]])
        if payload.get("title"):
            args.extend(["--title", payload["title"]])
        return args

    @staticmethod
    def _recent_audio_document_for_marker(message_dt: datetime) -> Optional[str]:
        """Return a recent cached iMessage audio file for text-only U+FFFC events.

        Spectrum can surface an iMessage voice note as a text event containing
        only the object-replacement marker while another gateway layer has
        already cached the CAF file under cache/documents. In that shape the
        normalized Photon event has no attachment payload, so recover the audio
        file by timestamp before the normal agent chat path sees a blank marker.
        """
        cache_dirs = [_DOCUMENT_CACHE_DIR, *_AUDIO_CACHE_DIRS]
        if not any(cache_dir.exists() for cache_dir in cache_dirs):
            return None
        exts = {".caf", ".m4a", ".mp3", ".aac", ".mp4", ".wav"}
        candidates: list[tuple[float, Path]] = []
        msg_ts = message_dt.timestamp()
        now = time.time()
        for cache_dir in cache_dirs:
            if not cache_dir.exists():
                continue
            for path in cache_dir.iterdir():
                if not path.is_file() or path.suffix.lower() not in exts:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                delta = abs(stat.st_mtime - msg_ts)
                # Only recover files close to the marker's timestamp and freshly
                # cached. This prevents an unrelated older voice note from being
                # attached to a blank marker after a delayed replay.
                if delta <= 180 and now - stat.st_mtime <= 900:
                    candidates.append((delta, path))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return str(candidates[0][1])

    async def _try_ingest_audio_journal_reply(
        self,
        *,
        space_id: str,
        sender_id: str,
        message_id: Optional[str],
        text: str,
        timestamp: datetime,
        media_urls: List[str],
        media_types: List[str],
    ) -> bool:
        prompt_date = await self._active_journal_prompt_date(timestamp)
        if not prompt_date:
            logger.info(
                "[photon] ingesting preauthorized audio journal without active prompt; using journal default date"
            )
        if not media_urls and "\ufffc" in text:
            # Last-resort recovery only: the docs-correct path is the sidecar
            # promoting audio-named attachments to ``voice`` so the next event
            # for this message arrives with ``media_urls`` already populated.
            # If we still see a marker-only text event with no media (e.g. when
            # Spectrum never emits a follow-up attachment event for an IMCore
            # message that races the attachment row), fall back to scanning the
            # local document cache by mtime \u2014 same as the prior heuristic, but
            # demoted from the primary path.
            recovered = None
            for _ in range(12):
                recovered = self._recent_audio_document_for_marker(timestamp)
                if recovered:
                    break
                await asyncio.sleep(0.25)
            if recovered:
                logger.info(
                    "[photon] last-resort: recovered marker-only audio "
                    "attachment for sebOS journal from cache mtime: %s",
                    recovered,
                )
                media_urls = [recovered]
                media_types = ["audio/x-caf"]
            else:
                logger.warning(
                    "[photon] marker-only journal audio had no recoverable "
                    "cached file near %s",
                    timestamp.isoformat(),
                )
        if not media_urls:
            return False
        # Accept either an audio MIME OR an audio file extension on the cached
        # path. iMessage voice notes commonly arrive with empty MIME and the
        # canonical ``Audio Message.caf`` name, so an extension check is the
        # docs-correct discriminator (see Spectrum content/voice docs).
        is_audio = any(
            (mime or "").lower().startswith("audio/") for mime in media_types
        ) or any(_path_looks_like_audio(path) for path in media_urls)
        if not is_audio:
            return False

        audio_path = media_urls[0]
        retained_path = await self._copy_audio_to_sebos_inbox(audio_path, message_id)
        if retained_path:
            audio_path = retained_path
        mime = media_types[0] if media_types else ""
        if not mime.lower().startswith("audio/"):
            # Upstream MIME was generic (e.g. application/octet-stream on a
            # ``Audio Message.caf``); pick from the file extension instead so
            # sebOS sees a coherent audio MIME.
            mime = _AUDIO_MIME_BY_EXT.get(Path(audio_path).suffix.lower(), "audio/x-caf")
        payload = {
            "messages": [
                {
                    "guid": message_id,
                    "id": message_id,
                    "text": text,
                    "dateCreated": timestamp.isoformat(),
                    "sender": sender_id,
                    "handleAddress": sender_id,
                    "chatGuid": space_id,
                    "attachments": [
                        {
                            "guid": message_id,
                            "path": audio_path,
                            "mimeType": mime,
                            "transferName": Path(audio_path).name,
                        }
                    ],
                }
            ]
        }
        _SEBOS_AUDIO_INBOX.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="photon-audio-journal-", suffix=".json", dir=str(_SEBOS_AUDIO_INBOX))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            result = await self._ingest_journal_payload(
                tmp_name,
                sender_id=sender_id,
                entry_date=prompt_date,
            )
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        logger.info("[photon] sebOS audio journal ingest result: %s", result)
        if int(result.get("inserted") or 0) <= 0:
            return False
        if int(result.get("transcribed_ok") or 0) > 0:
            # Keep chat clean: no full transcript echo. Seb wants the audio saved,
            # then a quiet native-feeling acknowledgement.
            if not await self._send_ack_reaction(space_id, message_id, "❤️"):
                await self._send_quiet(space_id, "Audio journal saved.")
        else:
            await self._send_quiet(space_id, "Audio received, but transcription failed.")
        return True

    async def _handle_sebos_rules(
        self,
        *,
        space_id: str,
        message_id: Optional[str],
        text: str,
        mtype: MessageType,
        media_urls: List[str],
        media_types: List[str],
    ) -> Optional[str]:
        if not self._sebos_rules_enabled:
            return None
        stripped = (text or "").strip()
        lowered = stripped.lower()
        # Voice/audio messages need Hermes nuance: journal dumps can contain
        # themes, reminders, suppressions, and context updates in one ramble.
        # Do not short-circuit them through the deterministic sebOS command
        # router. Let the normal Hermes message path receive the audio payload;
        # sebOS remains the state/write executor when Hermes chooses tools.
        if mtype in {MessageType.AUDIO, MessageType.VOICE} or any(
            (mime or "").lower().startswith("audio/") for mime in media_types
        ):
            return None

        # Legacy explicit assistant escape hatch. ``t:`` / ``thread:`` is the
        # normal iMessage chat path; keep h:/hermes: for manual diagnostics.
        if lowered.startswith("h:"):
            return stripped[2:].strip() or " "
        if lowered.startswith("hermes:"):
            return stripped[len("hermes:"):].strip() or " "

        if lowered == "board":
            await self._send_quiet(
                space_id,
                (await self._mission_control_text())[:_MAX_MESSAGE_LENGTH],
                reply_to=message_id,
            )
            return "handled"
        if lowered == "now":
            payload = await self._board_query("now")
            await self._send_quiet(
                space_id,
                self._lines_payload_text(payload, "now", empty="NOW: empty")[:_MAX_MESSAGE_LENGTH],
                reply_to=message_id,
            )
            return "handled"
        if lowered == "next":
            payload = await self._board_query("next")
            await self._send_quiet(
                space_id,
                self._lines_payload_text(payload, "next", empty="No next item on the board.")[:_MAX_MESSAGE_LENGTH],
                reply_to=message_id,
            )
            return "handled"

        if stripped and self._looks_like_sebos_command(stripped):
            result = await self._route_explicit_sebos_command(stripped)
            logger.info("[photon] sebOS route result: %s", result)
            intent = str(result.get("intent") or "")
            status = str(result.get("status") or "")
            if intent in {"unknown", "ignored", "ask"}:
                return None
            reply = str(result.get("reply") or "").strip()
            ack_emoji = self._sebos_ack_emoji(result)
            if ack_emoji and await self._send_ack_reaction(
                space_id, message_id, ack_emoji
            ):
                return "handled"
            if not reply:
                reply = "Handled." if status != "error" else "Could not handle that."
            await self._send_quiet(space_id, reply[:_MAX_MESSAGE_LENGTH], reply_to=message_id)
            return "handled"
        return None

    @staticmethod
    def _json_object_from_text(text: str) -> Optional[Dict[str, Any]]:
        raw = (text or "").strip()
        if not raw:
            return None
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
            raw = re.sub(r"\s*```$", "", raw).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _should_run_intent_gate(self, text: str, mtype: MessageType) -> bool:
        if not self._intent_gate_enabled or not self._sebos_rules_enabled:
            return False
        if mtype is not MessageType.TEXT:
            return False
        stripped = (text or "").strip()
        lowered = stripped.lower()
        if not stripped or len(stripped) > 240 or "\n" in stripped:
            return False
        if lowered.startswith(("/", "h:", "hermes:", "t:", "thread:", "t+")):
            return False
        if self._looks_like_sebos_command(stripped):
            return False
        return any(
            cue in lowered
            for cue in (
                "remind", "reminder", "remember to", "don't let me forget",
                "dont let me forget", "note", "write this down", "save this",
                "journal", "log this", "board", "control center", "mission control",
                "what's next", "whats next", "what next", "next on the agenda",
                "agenda", "what should i do", "what should i work on",
                "where am i", "where was i", "calendar", "location",
            )
        )

    @staticmethod
    def _deterministic_natural_reminder_intent(
        text: str,
        *,
        timestamp: datetime,
    ) -> Optional[Dict[str, Any]]:
        """Parse stable reminder phrasings without an LLM or side effects.

        This intentionally covers only high-signal shapes that should never
        depend on model interpretation. Anything outside this small matrix falls
        back to the intent LLM (or Hermes) rather than creating a bad reminder.
        """
        raw = (text or "").strip()
        lowered = raw.lower()
        if not lowered or not re.search(r"\bremind(?:er)?\b|\bremember to\b", lowered):
            return None

        def _title(default: str = "Reminder") -> str:
            match = re.search(r"\bto\s+(.+?)\s*$", raw, flags=re.IGNORECASE)
            if not match:
                return default
            candidate = match.group(1).strip(" .")
            # In location-only phrases, the trailing "to the office" is the
            # trigger, not the task title.
            if candidate.lower() in {"office", "the office", "home"}:
                return default
            return candidate[:120] or default

        def _intent(**fields: Any) -> Dict[str, Any]:
            base: Dict[str, Any] = {
                "intent": "reminder",
                "confidence": 0.99,
                "needs_clarification": False,
                "clarification": "",
                "title": _title(),
                "due_datetime": "",
                "location_name": "",
                "latitude": "",
                "longitude": "",
                "radius_meters": "",
                "proximity": "",
            }
            base.update(fields)
            return base

        def _clarify(message: str) -> Dict[str, Any]:
            return _intent(
                confidence=0.99,
                needs_clarification=True,
                clarification=message,
            )

        if re.search(r"\bafter\s+my\s+meeting\b", lowered):
            return _clarify("When should I remind you after your meeting?")

        loc_match = re.search(
            r"\bwhen\s+i\s+(?P<verb>get\s+to|arrive\s+at|reach|leave)\s+(?P<place>.+?)\s*$",
            lowered,
        )
        if loc_match:
            place = loc_match.group("place").strip(" .")
            verb = loc_match.group("verb")
            normalized_place = place.removeprefix("the ").strip()
            if normalized_place == "office":
                return _intent(
                    location_name="Office",
                    proximity="leave" if verb == "leave" else "enter",
                )
            if normalized_place == "home":
                return _intent(
                    location_name="Home",
                    proximity="leave" if verb == "leave" else "enter",
                )
            return _clarify(f"Which location do you mean by {place!r}?")

        base = timestamp.astimezone()
        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }

        def _next_weekday(target: int, *, ordinal: int = 1) -> datetime:
            days = (target - base.weekday()) % 7
            if days == 0:
                days = 7
            days += 7 * max(0, ordinal - 1)
            return base + timedelta(days=days)

        def _due(day: datetime, hour: int = 9, minute: int = 0) -> str:
            return day.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime(
                "%Y-%m-%d %H:%M"
            )

        def _due_from_date_phrase(phrase: str) -> Optional[str]:
            phrase = (phrase or "").strip().lower()
            if re.search(r"\btomorrow\s+morning\b", phrase):
                return _due(base + timedelta(days=1), 9)
            if re.search(r"\btomorrow\b", phrase):
                return _due(base + timedelta(days=1), 9)
            match = re.search(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", phrase)
            if match:
                hour = 14 if re.search(r"\bafternoon\b", phrase) else 9
                return _due(_next_weekday(weekdays[match.group(1)]), hour)
            match = re.search(r"\bin\s+(\d+)\s+(mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays)\b", phrase)
            if match:
                ordinal = max(1, int(match.group(1)))
                weekday = match.group(2).removesuffix("s")
                return _due(_next_weekday(weekdays[weekday], ordinal=ordinal), 9)
            match = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", phrase)
            if match:
                return _due(_next_weekday(weekdays[match.group(1)]), 9)
            return None

        update_match = re.search(
            r"\b(?:adjust|change|move|reschedule|update)\s+(?:the\s+)?(?P<query>.+?)\s+reminder\s+(?:to|for|on|until)\s+(?P<date>.+?)\s*$",
            lowered,
        )
        if update_match:
            due = _due_from_date_phrase(update_match.group("date"))
            query = update_match.group("query").strip(" .")
            query = re.sub(r"^(?:hey\s+)?(?:can\s+you\s+|please\s+|athena\s+)", "", query).strip(" .")
            if due and query:
                return _intent(
                    intent="reminder_update",
                    query=query,
                    due_datetime=due,
                    title="",
                )
            return _clarify("Which reminder should I update, and when should it be due?")

        if re.search(r"\btomorrow\s+morning\b", lowered):
            return _intent(due_datetime=_due(base + timedelta(days=1), 9))

        match = re.search(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lowered)
        if match:
            hour = 14 if re.search(r"\bafternoon\b", lowered) else 9
            return _intent(due_datetime=_due(_next_weekday(weekdays[match.group(1)]), hour))

        match = re.search(r"\bin\s+(\d+)\s+(mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays)\b", lowered)
        if match:
            ordinal = max(1, int(match.group(1)))
            weekday = match.group(2).removesuffix("s")
            return _intent(due_datetime=_due(_next_weekday(weekdays[weekday], ordinal=ordinal), 9))

        match = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lowered)
        if match:
            return _intent(due_datetime=_due(_next_weekday(weekdays[match.group(1)]), 9))

        return None

    async def _classify_natural_intent(
        self,
        text: str,
        *,
        timestamp: datetime,
    ) -> Optional[Dict[str, Any]]:
        deterministic = self._deterministic_natural_reminder_intent(
            text,
            timestamp=timestamp,
        )
        if deterministic is not None:
            return deterministic

        prompt = (
            "Classify one short iMessage from Seb for a tiny personal-OS router. "
            "Return JSON only. Do not chat. Do not invent missing dates. "
            "Use intent chat for questions, advice, planning, unclear notes, or anything messy. "
            "Use intent reminder only when the message asks to be reminded and a concrete due time/date or location trigger can be normalized. "
            "Use intent reminder_update only when Seb asks to adjust, move, reschedule, change, or update an existing reminder and gives both a unique title/query and concrete due time/date. "
            "If Seb gives a date/day without a time, default to 09:00 local; never return 00:00 unless he says midnight, 12am, or start of day. "
            "For vague locations, ask a clarification. For named places like Home or Office, use location_name. "
            "Use proximity=enter unless wording says leaving/when I leave. "
            "Use intent note only when the message asks to save/write/note something. "
            "Use intent journal only when the message explicitly asks to journal/log an entry. "
            "Schema: {\"intent\":\"reminder|reminder_update|note|journal|board|now|chat\","
            "\"confidence\":0.0,"
            "\"needs_clarification\":false,"
            "\"clarification\":\"\","
            "\"title\":\"\","
            "\"query\":\"existing reminder title/query for reminder_update or empty\","
            "\"body\":\"\","
            "\"target\":\"\","
            "\"due_datetime\":\"YYYY-MM-DD HH:MM or empty\","
            "\"location_name\":\"\","
            "\"latitude\":\"\","
            "\"longitude\":\"\","
            "\"radius_meters\":\"\","
            "\"proximity\":\"enter|leave|\"}.\n"
            f"Current local time: {datetime.now().astimezone().isoformat(timespec='minutes')}\n"
            f"Message timestamp: {timestamp.astimezone().isoformat(timespec='minutes')}\n"
            f"Message: {text!r}"
        )

        def _call() -> Optional[Dict[str, Any]]:
            from agent.auxiliary_client import call_llm

            resp = call_llm(
                task="photon_intent",
                provider=self._intent_gate_provider,
                model=self._intent_gate_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=350,
                temperature=0,
                timeout=20,
            )
            content = resp.choices[0].message.content
            return self._json_object_from_text(str(content or ""))

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            logger.warning("[photon] intent gate failed; falling through to Hermes: %s", exc)
            return None

    @staticmethod
    def _intent_due_datetime(intent: Dict[str, Any], original_text: str = "") -> str:
        due = str(intent.get("due_datetime") or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", due):
            return f"{due} 09:00"
        if re.match(r"^\d{4}-\d{2}-\d{2} 00:00$", due):
            lowered = (original_text or "").lower()
            explicit_midnight = any(
                phrase in lowered
                for phrase in ("midnight", "12am", "12:00am", "start of day")
            )
            explicit_time = bool(
                re.search(r"\b(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", lowered)
                or re.search(r"\bnoon\b", lowered)
            )
            if not explicit_midnight and not explicit_time:
                return f"{due[:10]} 09:00"
        return due

    @staticmethod
    def _intent_reminder_payload(intent: Dict[str, Any], original_text: str = "") -> Optional[Dict[str, str]]:
        title = str(intent.get("title") or "").strip()
        due = PhotonAdapter._intent_due_datetime(intent, original_text)
        location = str(intent.get("location_name") or intent.get("location") or "").strip()
        latitude = str(intent.get("latitude") or "").strip()
        longitude = str(intent.get("longitude") or "").strip()
        radius = str(intent.get("radius_meters") or intent.get("radius") or "").strip()
        proximity = str(intent.get("proximity") or "").strip().lower()
        if not title or (not due and not location):
            return None
        payload = {"title": title}
        if due:
            payload["due"] = due
        if location:
            payload["location"] = location
        if latitude:
            payload["latitude"] = latitude
        if longitude:
            payload["longitude"] = longitude
        if radius:
            payload["radius"] = radius
        if proximity in {"enter", "leave"}:
            payload["proximity"] = proximity
        return payload

    @staticmethod
    def _intent_reminder_update_payload(intent: Dict[str, Any], original_text: str = "") -> Optional[Dict[str, str]]:
        query = str(intent.get("query") or intent.get("title") or "").strip()
        due = PhotonAdapter._intent_due_datetime(intent, original_text)
        title = str(intent.get("new_title") or intent.get("updated_title") or "").strip()
        if not query or not due:
            return None
        payload = {"query": query, "due": due}
        if title:
            payload["title"] = title
        return payload

    @staticmethod
    def _intent_reminder_args(intent: Dict[str, Any], original_text: str = "") -> Optional[List[str]]:
        payload = PhotonAdapter._intent_reminder_payload(intent, original_text)
        if not payload:
            return None
        return PhotonAdapter._reminder_payload_args(payload)

    @staticmethod
    def _intent_to_sebos_text(intent: Dict[str, Any]) -> Optional[str]:
        kind = str(intent.get("intent") or "").strip().lower()
        title = str(intent.get("title") or "").strip()
        body = str(intent.get("body") or "").strip()
        target = str(intent.get("target") or "").strip()
        due = PhotonAdapter._intent_due_datetime(intent)
        if kind == "reminder":
            if not title or not due:
                return None
            return f"remind me {due} to {title}"
        if kind == "note":
            content = body or title
            if not content:
                return None
            if target:
                return f"note this under {target}: {content}"
            return f"note this: {content}"
        if kind == "journal":
            content = body or title
            return f"j: {content}" if content else None
        if kind == "board":
            return "board"
        if kind == "now":
            return "now"
        return None

    async def _try_intent_gate(
        self,
        *,
        space_id: str,
        message_id: Optional[str],
        text: str,
        mtype: MessageType,
        timestamp: datetime,
    ) -> Optional[str]:
        if not self._should_run_intent_gate(text, mtype):
            return None
        intent = await self._classify_natural_intent(text, timestamp=timestamp)
        if not intent:
            return None
        kind = str(intent.get("intent") or "").strip().lower()
        confidence = float(intent.get("confidence") or 0)
        needs_clarification = bool(intent.get("needs_clarification"))
        if needs_clarification and str(intent.get("clarification") or "").strip():
            await self._send_quiet(
                space_id,
                str(intent.get("clarification")).strip()[:_MAX_MESSAGE_LENGTH],
                reply_to=message_id,
            )
            return "handled"
        if kind == "chat" or confidence < self._intent_gate_min_confidence:
            return None
        routed_text = self._intent_to_sebos_text(intent)
        if kind == "reminder":
            reminder_payload = self._intent_reminder_payload(intent, text)
            if not reminder_payload:
                return None
            writer = await self._add_reminder(reminder_payload)
            logger.info("[photon] intent gate reminder writer result: %s", writer)
            if writer.get("status") == "ok":
                reply_bits = [f"Reminder added: {writer.get('title', '').strip()}"]
                if writer.get("due"):
                    reply_bits.append(str(writer.get("due")))
                if writer.get("location"):
                    reply_bits.append(f"at {writer.get('location')}")
                reply_text = " (" + ", ".join(reply_bits[1:]) + ")." if len(reply_bits) > 1 else "."
                reply = reply_bits[0] + reply_text
            else:
                reply = f"Reminder failed: {writer.get('error') or writer.get('status')}."
            result = {
                "status": "ok" if writer.get("status") == "ok" else "error",
                "intent": "reminder",
                "mutated": writer.get("status") == "ok",
                "reply": reply,
                "details": {"writer": writer},
                "side_effects": [{"kind": "reminder", "writer": writer}],
                "error_layer": None if writer.get("status") == "ok" else "reminders",
            }
        elif kind == "reminder_update":
            reminder_payload = self._intent_reminder_update_payload(intent, text)
            if not reminder_payload:
                return None
            writer = await self._update_reminder(reminder_payload)
            logger.info("[photon] intent gate reminder update result: %s", writer)
            if writer.get("status") == "ok":
                reply_bits = [f"Reminder updated: {writer.get('title', reminder_payload['query'])}"]
                if writer.get("due"):
                    reply_bits.append(str(writer.get("due")))
                reply_text = " (" + ", ".join(reply_bits[1:]) + ")." if len(reply_bits) > 1 else "."
                reply = reply_bits[0] + reply_text
            elif writer.get("status") == "ambiguous":
                reply = "Which reminder? I found multiple matches."
            elif writer.get("status") == "not_found":
                reply = f"Reminder not found: {reminder_payload['query']}."
            else:
                reply = f"Reminder update failed: {writer.get('error') or writer.get('status')}."
            result = {
                "status": "ok" if writer.get("status") == "ok" else "error",
                "intent": "reminder",
                "mutated": writer.get("status") == "ok",
                "reply": reply,
                "details": {"writer": writer},
                "side_effects": [{"kind": "reminder_update", "writer": writer}],
                "error_layer": None if writer.get("status") == "ok" else "reminders",
            }
        else:
            if not routed_text:
                return None
            result = await self._route_explicit_sebos_command(routed_text)
            logger.info("[photon] intent gate route result: %s", result)
        if (
            kind == "note"
            and str(result.get("status") or "") == "dry_run"
            and str(((result.get("details") or {}).get("reason")) or "") == "no_appender_wired"
        ):
            # Legacy safety for older sebOS builds that staged notes instead of
            # writing them. Current sebOS appends to Mission Control Notes.
            return None
        reply = str(result.get("reply") or "").strip()
        ack_emoji = self._sebos_ack_emoji(result)
        if ack_emoji and await self._send_ack_reaction(space_id, message_id, ack_emoji):
            return "handled"
        if kind == "reminder" and reply:
            await self._send_quiet(space_id, reply[:_MAX_MESSAGE_LENGTH], reply_to=message_id)
            return "handled"
        if not reply:
            status = str(result.get("status") or "")
            reply = "Handled." if status != "error" else "Could not handle that."
        await self._send_quiet(space_id, reply[:_MAX_MESSAGE_LENGTH], reply_to=message_id)
        return "handled"

    @staticmethod
    def _looks_like_sebos_command(text: str) -> bool:
        """Return True for explicit sebOS commands only.

        Plain iMessages should stay conversational. This keeps iMessage clean:
        sebOS handles deterministic actions, Hermes handles normal chat.
        """
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        while True:
            cleaned = re.sub(r"^(?:hey|hi|yo|ok|okay|athena)[,\s]+", "", lowered, count=1).strip()
            if cleaned == lowered:
                break
            lowered = cleaned
        prefixes = (
            "j:",
            "journal:",
            "reminder:",
            "note:",
            "suppress ",
            "hide ",
            "don't mention ",
            "dont mention ",
            "do not mention ",
            "remove this",
            "remove the ",
            "delete reminder ",
        )
        if lowered.startswith(prefixes):
            return True
        if re.search(
            r"\b(?:what(?:'s|s|\s+is)?\s+next|what\s+next|next\s+on\s+(?:the\s+)?agenda|agenda\b|what\s+should\s+i\s+(?:do|work\s+on)|where\s+(?:am|was)\s+i|calendar|location)\b",
            lowered,
        ):
            return True
        exact = {
            "where was i", "where was i?", "where am i", "where am i?",
            "where am i on my tasks", "where am i on my tasks?",
            "what am i doing", "what am i doing?",
            "what reminders do i have", "what reminders do i have?",
            "what are my reminders", "what are my reminders?", "reminders today",
            "reminders this week",
        }
        return lowered in exact

    async def _assert_cloud_project_safe(self) -> bool:
        """Refuse Photon shared-cloud iMessage unless explicitly overridden.

        Shared-pool Photon iMessage can emit server-side fallback/offline texts
        when the gRPC stream drops. Hermes cannot suppress texts it did not
        send, so shared cloud must fail closed for Seb-facing gateway use.
        """
        allow_shared = str(
            os.getenv("PHOTON_ALLOW_SHARED_UNSAFE", "false")
        ).strip().lower() in {"true", "1", "yes", "on"}
        url = (
            f"{_PHOTON_SPECTRUM_API_BASE}/projects/"
            f"{self._project_id}/imessage/"
        )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    url,
                    headers={
                        # Spectrum Cloud REST uses HTTP Basic id:secret (same
                        # scheme the spectrum-ts sidecar uses), NOT Bearer. A
                        # Bearer header 401s here even with valid creds. This
                        # is only the read-only project-type probe; the sidecar
                        # gRPC transport is unaffected by this header.
                        "Authorization": "Basic " + base64.b64encode(
                            f"{self._project_id}:{self._project_secret}".encode(
                                "utf-8"
                            )
                        ).decode("ascii"),
                        "Accept": "application/json",
                    },
                )
        except Exception as exc:
            logger.warning(
                "[photon] could not verify Photon iMessage project type; "
                "continuing because sidecar credentials may still be valid: %s",
                exc,
            )
            return True
        if resp.status_code != 200:
            logger.warning(
                "[photon] Photon iMessage type check returned HTTP %s; "
                "continuing because sidecar credentials may still be valid",
                resp.status_code,
            )
            return True
        try:
            data = resp.json() or {}
        except Exception as exc:
            logger.warning(
                "[photon] Photon iMessage type check returned invalid JSON; "
                "continuing because sidecar credentials may still be valid: %s",
                exc,
            )
            return True
        imessage_type = str(((data.get("data") or {}).get("type") or "")).lower()
        if imessage_type == "dedicated":
            return True
        if imessage_type != "shared":
            logger.warning(
                "[photon] Photon iMessage project type is unknown (%s); "
                "continuing because only confirmed shared-cloud projects are blocked",
                imessage_type or "empty",
            )
            return True
        if imessage_type == "shared" and allow_shared:
            logger.warning(
                "[photon] PHOTON_ALLOW_SHARED_UNSAFE=true — shared-cloud "
                "iMessage can emit server-side fallback/offline texts"
            )
            return True
        self._set_fatal_error(
            "SHARED_CLOUD_UNSAFE",
            "Photon iMessage project is shared-cloud. Shared-pool projects "
            "can emit server-side fallback/offline texts that Hermes cannot "
            "suppress. Use local routing or upgrade Photon to a "
            "dedicated line. Set PHOTON_ALLOW_SHARED_UNSAFE=true only for "
            "isolated diagnostics.",
            retryable=False,
        )
        return False

    # -- Connection lifecycle ---------------------------------------------

    async def connect(self) -> bool:
        if not HTTPX_AVAILABLE:
            self._set_fatal_error(
                "MISSING_DEP", "httpx not installed", retryable=False
            )
            return False
        if not self._project_id or not self._project_secret:
            self._set_fatal_error(
                "MISSING_CREDENTIALS",
                "PHOTON_PROJECT_ID and PHOTON_PROJECT_SECRET are required. "
                "Run: hermes photon setup",
                retryable=False,
            )
            return False
        if not await self._assert_cloud_project_safe():
            return False

        client = httpx.AsyncClient(timeout=30.0)
        self._http_client = client

        # The sidecar holds the gRPC stream for BOTH directions, so it is
        # required now (not just for outbound).
        if self._autostart_sidecar:
            try:
                await self._start_sidecar()
            except Exception as e:
                self._set_fatal_error(
                    "SIDECAR_FAILED",
                    f"failed to start Photon sidecar: {e}",
                    retryable=True,
                )
                await client.aclose()
                self._http_client = None
                return False
        else:
            logger.warning(
                "[photon] sidecar autostart disabled — inbound + outbound will fail"
            )

        # Start consuming the inbound gRPC stream from the sidecar.
        self._inbound_running = True
        self._inbound_task = asyncio.get_event_loop().create_task(
            self._inbound_loop()
        )

        self._mark_connected()
        logger.info(
            "[photon] connected — sidecar on %s:%d, streaming inbound over gRPC",
            self._sidecar_bind, self._sidecar_port,
        )
        return True

    async def disconnect(self) -> None:
        self._inbound_running = False
        if self._inbound_task is not None:
            self._inbound_task.cancel()
            try:
                await self._inbound_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._inbound_task = None
        await self._stop_sidecar()
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None
        self._mark_disconnected()

    # -- Inbound stream consumer ------------------------------------------

    async def _inbound_loop(self) -> None:
        """Consume the sidecar's ``/inbound`` NDJSON stream, with reconnect.

        The sidecar owns the gRPC reconnect/heartbeat to Photon; this loop
        only has to re-open the loopback HTTP stream if it drops (e.g. the
        sidecar restarts).
        """
        client = self._http_client
        if client is None:
            return
        url = f"http://{self._sidecar_bind}:{self._sidecar_port}/inbound"
        headers = {"X-Hermes-Sidecar-Token": self._sidecar_token}
        backoff = 1.0
        while self._inbound_running:
            try:
                async with client.stream(
                    "GET", url, headers=headers, timeout=None,
                ) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"/inbound returned {resp.status_code}")
                    backoff = 1.0  # reset on a successful connect
                    async for line in resp.aiter_lines():
                        if not self._inbound_running:
                            break
                        line = line.strip()
                        if not line:
                            continue  # heartbeat
                        await self._on_inbound_line(line)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not self._inbound_running:
                    break
                logger.warning(
                    "[photon] inbound stream dropped (%s); reconnecting in %.1fs",
                    e, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _on_inbound_line(self, line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("[photon] skipping non-JSON inbound line")
            return
        msg_id = event.get("messageId")
        if msg_id and self._is_duplicate(msg_id):
            return
        try:
            await self._dispatch_inbound(event)
        except Exception:
            logger.exception("[photon] inbound dispatch failed")

    def _is_duplicate(self, msg_id: str) -> bool:
        now = time.time()
        seen = self._seen_messages
        t = seen.get(msg_id)
        if t is not None and now - t < _DEDUP_WINDOW_SECONDS:
            return True  # seen, unexpired
        # New or expired: record and enforce a HARD size bound (evict oldest,
        # insertion-order) so a burst of unique ids within the window can't grow
        # the dict without limit — not just the expired-only prune.
        if msg_id in seen:
            del seen[msg_id]  # refresh insertion order
        seen[msg_id] = now
        if len(seen) > _DEDUP_MAX_SIZE:
            for old in list(seen.keys())[: len(seen) - _DEDUP_MAX_SIZE]:
                del seen[old]
        return False

    async def _dispatch_inbound(self, event: Dict[str, Any]) -> None:
        """Normalize a sidecar inbound event and dispatch it to the gateway.

        Event shape (from ``sidecar/index.mjs``)::

            {
              "messageId": "...",
              "platform": "iMessage",
              "space": {"id": "...", "type": "dm"|"group", "phone": "+E164"},
              "sender": {"id": "+E164"},
              "content": {"type": "text", "text": "..."}
                       | {"type": "attachment"|"voice", "id", "name",
                          "mimeType", "size", "duration"?, "data"?,
                          "encoding"?}
                       | {"type": "reaction", "emoji": "❤️",
                          "targetMessageId": "..." | null,
                          "targetDirection": "inbound"|"outbound" | null},
              "timestamp": "2026-05-14T19:06:32.000Z"

        Attachment and voice content carry the bytes inline as base64 ``data``
        (with ``encoding == "base64"``) when the sidecar could read them
        within its size cap; otherwise only metadata is present and we surface
        a marker.
            }
        """
        space = event.get("space") or {}
        sender = event.get("sender") or {}
        content = event.get("content") or {}

        space_id = space.get("id") or ""
        if not space_id:
            logger.warning("[photon] inbound missing space.id")
            return

        reply_to_message_id = event.get("replyToMessageId")
        thread_root_message_id = event.get("threadRootMessageId")

        # iMessage spaces carry their type directly — no id string-sniffing.
        chat_type = "group" if space.get("type") == "group" else "dm"
        sender_id = sender.get("id") or space.get("phone") or space_id
        sebos_preauth = self._is_photon_user_allowed_for_sebos(
            sender_id=sender_id,
            space_phone=space.get("phone"),
            space_id=space_id,
        )

        ts_str = event.get("timestamp") or ""
        try:
            timestamp = (
                datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts_str
                else datetime.now(tz=timezone.utc)
            )
        except ValueError:
            timestamp = datetime.now(tz=timezone.utc)

        # Media attachments (local cached paths) handed to the agent via the
        # gateway's image-routing path, like other media-capable channels.
        media_urls: List[str] = []
        media_types: List[str] = []

        def _normalize_binary_payload(
            payload: Dict[str, Any]
        ) -> tuple[str, MessageType, List[str], List[str]]:
            # Audio-named attachments without a real MIME (e.g. iMessage's
            # ``Audio Message.caf`` with empty ``mimeType``) are voice notes per
            # the Spectrum content/voice docs (voice and attachment share the
            # same shape). Treat them as audio so the journal ingest gate
            # accepts them and the bytes land in the audio cache, not the
            # generic document cache.
            raw_type = payload.get("type")
            name = payload.get("name") or ("voice" if raw_type == "voice" else "(unnamed)")
            mime = payload.get("mimeType") or ""
            is_audio_named = Path(name).suffix.lower() in _AUDIO_EXTENSIONS
            is_voice = raw_type == "voice" or (
                raw_type == "attachment"
                and (mime.lower().startswith("audio/") or is_audio_named)
            )
            mtype = MessageType.VOICE if is_voice else _attachment_message_type(mime)
            cached = _cache_inbound_attachment(
                payload, name, mime, force_audio=is_voice
            )
            if cached:
                if is_voice:
                    # Infer audio MIME from the cached file extension when the
                    # upstream Spectrum event left ``mimeType`` empty. iMessage
                    # voice notes commonly arrive that way as
                    # ``Audio Message.caf``; ``audio/x-caf`` keeps the journal
                    # ingest MIME coherent with the cached file.
                    fallback_mime = _AUDIO_MIME_BY_EXT.get(
                        Path(cached).suffix.lower(), "audio/x-caf"
                    )
                else:
                    fallback_mime = "application/octet-stream"
                return (
                    "(voice)" if is_voice else "(attachment)",
                    mtype,
                    [cached],
                    [mime or fallback_mime],
                )
            label = "voice" if is_voice else "attachment"
            duration = payload.get("duration")
            duration_text = (
                f", duration: {duration}s"
                if isinstance(duration, (int, float))
                else ""
            )
            return (
                f"[Photon {label} received: {name} "
                f"({mime or 'unknown MIME'}{duration_text})]",
                mtype,
                [],
                [],
            )

        ctype = content.get("type")
        if ctype == "reply":
            reply_to_message_id = reply_to_message_id or content.get("targetMessageId")
            content = content.get("content") or {}
            ctype = content.get("type")
        if ctype == "reaction":
            # Route only tapbacks on messages WE sent — those are implicitly
            # addressed to the bot (feishu precedent: synthetic text event).
            # Reactions on human↔human messages are not for us. Checked before
            # the mention gate: a tapback never carries a wake word.
            target_id = content.get("targetMessageId")
            is_ours = content.get("targetDirection") == "outbound" or (
                target_id and target_id in self._sent_message_ids
            )
            if not is_ours:
                logger.debug(
                    "[photon] ignoring reaction on a message we didn't send"
                )
                return
            emoji = content.get("emoji") or ""
            source = self.build_source(
                chat_id=space_id,
                chat_name=space_id,
                chat_type=chat_type,
                user_id=sender_id,
                user_name=sender_id or None,
            )
            await self.handle_message(
                MessageEvent(
                    text=f"reaction:added:{emoji}",
                    message_type=MessageType.TEXT,
                    source=source,
                    message_id=event.get("messageId"),
                    raw_message=event,
                    timestamp=timestamp,
                )
            )
            return
        # Anything past here is a real (reactable) message — remember it as
        # the chat's latest inbound so `add_reaction` can target it when the
        # caller doesn't pass an explicit message id. Recorded before the
        # mention gate: a reaction to a non-wake-word group message is valid.
        self._record_last_inbound(space_id, event.get("messageId"))
        if ctype == "text":
            text = content.get("text") or ""
            mtype = MessageType.TEXT
        elif ctype in {"attachment", "voice"}:
            text, mtype, media_urls, media_types = _normalize_binary_payload(content)
        elif ctype == "group":
            text_parts: List[str] = []
            mtype = MessageType.TEXT
            for item in content.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_content = item.get("content") or {}
                if not isinstance(item_content, dict):
                    continue
                item_type = item_content.get("type")
                if item_type == "text":
                    item_text = item_content.get("text") or ""
                    if item_text:
                        text_parts.append(item_text)
                    continue
                if item_type in {"attachment", "voice"}:
                    marker, item_mtype, item_urls, item_types = _normalize_binary_payload(
                        item_content
                    )
                    if mtype == MessageType.TEXT:
                        mtype = item_mtype
                    media_urls.extend(item_urls)
                    media_types.extend(item_types)
                    if not item_urls:
                        text_parts.append(marker)
                    continue
                if item_type:
                    text_parts.append(f"[Photon content type not handled: {item_type}]")
            if media_urls and mtype == MessageType.TEXT:
                mtype = MessageType.DOCUMENT
            text = "\n".join(part for part in text_parts if part).strip()
            if not text:
                text = "(attachment)" if media_urls else "[Photon empty group received]"
        else:
            text = f"[Photon content type not handled: {ctype}]"
            mtype = MessageType.TEXT

        # Group-mention gating (iMessage parity). In group chats with
        # require_mention enabled, drop messages that don't hit a wake word;
        # strip the leading wake word from the ones that do. DMs are never
        # gated.
        if chat_type == "group" and self.require_mention:
            if not self._message_matches_mention_patterns(text):
                logger.debug(
                    "[photon] ignoring group message "
                    "(require_mention=true, no mention pattern matched)"
                )
                return
            text = self._clean_mention_text(text)

        # Suppress marker-only text events that arrive with no media. Per the
        # spectrum-ts iMessage inbound mapper, when an IMCore event raises before
        # the attachment row is linked, the message surfaces as text "￼"
        # with empty attachments. A follow-up event (or our last-resort cache
        # recovery in `_try_ingest_audio_journal_reply`) carries the real bytes.
        # Routing the marker through the agent chat path would make the bot
        # answer the placeholder glyph itself.
        stripped = (text or "").strip("￼ \t\r\n")
        if (
            ctype in {"text", "group"}
            and not media_urls
            and "￼" in (text or "")
            and not stripped
        ):
            if sebos_preauth and await self._try_ingest_audio_journal_reply(
                space_id=space_id,
                sender_id=sender_id,
                message_id=event.get("messageId"),
                text=text,
                timestamp=timestamp,
                media_urls=media_urls,
                media_types=media_types,
            ):
                return
            logger.info(
                "[photon] suppressing marker-only text event "
                "(no attachment payload, no journal recovery)"
            )
            return

        thread_root = self._thread_root_for_reply(
            space_id,
            str(reply_to_message_id) if reply_to_message_id else None,
            str(thread_root_message_id) if thread_root_message_id else None,
        )
        thread_start = _THREAD_START_RE.match(text or "")
        if thread_start and event.get("messageId"):
            thread_root = str(event.get("messageId"))
            self._last_thread_root_by_chat[self._normalize_chat_key(space_id)] = thread_root
            text = thread_start.group(1).strip() or " "
        else:
            thread_continue = _THREAD_CONTINUE_RE.match(text or "")
            if thread_continue:
                thread_root = thread_root or self._last_thread_root_by_chat.get(
                    self._normalize_chat_key(space_id)
                )
                text = thread_continue.group(1).strip() or " "

        if sebos_preauth and await self._try_ingest_audio_journal_reply(
            space_id=space_id,
            sender_id=sender_id,
            message_id=event.get("messageId"),
            text=text,
            timestamp=timestamp,
            media_urls=media_urls,
            media_types=media_types,
        ):
            return

        if not thread_root and sebos_preauth:
            gate_result = await self._try_intent_gate(
                space_id=space_id,
                message_id=event.get("messageId"),
                text=text,
                mtype=mtype,
                timestamp=timestamp,
            )
            if gate_result == "handled":
                return

            rule_result = await self._handle_sebos_rules(
                space_id=space_id,
                message_id=event.get("messageId"),
                text=text,
                mtype=mtype,
                media_urls=media_urls,
                media_types=media_types,
            )
            if rule_result == "handled":
                return
            if isinstance(rule_result, str):
                text = rule_result

        source = self.build_source(
            chat_id=space_id,
            chat_name=space_id,
            chat_type=chat_type,
            user_id=sender_id,
            user_name=sender_id or None,
            thread_id=thread_root,
        )
        message_event = MessageEvent(
            text=text,
            message_type=mtype,
            source=source,
            message_id=event.get("messageId"),
            reply_to_message_id=str(reply_to_message_id) if reply_to_message_id else None,
            raw_message=event,
            timestamp=timestamp,
            media_urls=media_urls,
            media_types=media_types,
        )
        await self.handle_message(message_event)

    # -- Sidecar lifecycle -------------------------------------------------

    @staticmethod
    def _find_listener_pids(port: int) -> List[int]:
        """PIDs listening on a local TCP port (empty if none/undeterminable)."""
        try:
            out = subprocess.run(  # noqa: S603, S607
                ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=5.0, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        return [int(tok) for tok in out.stdout.split() if tok.strip().isdigit()]

    @staticmethod
    def _pid_is_sidecar(pid: int) -> bool:
        """True if ``pid``'s command line is a Photon sidecar process."""
        try:
            out = subprocess.run(  # noqa: S603, S607
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True, text=True, timeout=5.0, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        # Checkout-agnostic: any Hermes checkout's sidecar entry point.
        return "photon/sidecar/index.mjs" in out.stdout

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)  # windows-footgun: ok — only called from _reap_stale_sidecar which win32-guards early
            return True
        except OSError:
            return False

    async def _reap_stale_sidecar(self) -> None:
        """Kill an orphaned sidecar squatting our port before spawning ours.

        A hard gateway exit (crash, SIGKILL, supervisor restart) used to leave
        the detached sidecar running with a token the new gateway doesn't
        know, so it can't be told to ``/shutdown`` — and every replacement
        spawn died on EADDRINUSE, failing each reconnect attempt. The
        stdin-EOF watch prevents new orphans; this reclaims the port from
        orphans that predate it (or survived it). Listeners are verified by
        command line before being signalled.
        """
        if sys.platform == "win32":  # lsof/ps; orphaning is a POSIX-only path
            return
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(
                    f"http://{self._sidecar_bind}:{self._sidecar_port}/healthz",
                    headers={"X-Hermes-Sidecar-Token": self._sidecar_token},
                )
        except httpx.RequestError:
            return  # nothing listening — the normal case
        pids = self._find_listener_pids(self._sidecar_port)
        stale = [pid for pid in pids if self._pid_is_sidecar(pid)]
        foreign = [pid for pid in pids if pid not in stale]
        if not stale:
            raise RuntimeError(
                f"port {self._sidecar_port} is in use by another process "
                f"(pids: {foreign or 'unknown'}, not a Photon sidecar) — "
                f"free it or set PHOTON_SIDECAR_PORT to a different port"
            )
        for pid in stale:
            logger.warning(
                "[photon] reaping orphaned sidecar (pid %d) on port %d",
                pid, self._sidecar_port,
            )
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.time() + 3.0
        while time.time() < deadline and any(self._pid_alive(p) for p in stale):
            await asyncio.sleep(0.1)
        for pid in stale:
            if self._pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)  # windows-footgun: ok — unreachable on win32 (early return above)
                except OSError:
                    pass
        # Give the OS a beat to release the listening socket.
        await asyncio.sleep(0.2)
        if foreign:
            raise RuntimeError(
                f"port {self._sidecar_port} is also held by non-sidecar "
                f"processes (pids: {foreign}) — free it or set "
                f"PHOTON_SIDECAR_PORT to a different port"
            )

    async def _start_sidecar(self) -> None:
        if not (_SIDECAR_DIR / "node_modules").exists():
            raise RuntimeError(
                f"Photon sidecar deps not installed. Run: "
                f"cd {_SIDECAR_DIR} && npm install   (or `hermes photon setup`)"
            )
        await self._reap_stale_sidecar()

        env = os.environ.copy()
        env["PHOTON_PROJECT_ID"] = self._project_id
        env["PHOTON_PROJECT_SECRET"] = self._project_secret
        env["PHOTON_SIDECAR_PORT"] = str(self._sidecar_port)
        env["PHOTON_SIDECAR_BIND"] = self._sidecar_bind
        env["PHOTON_SIDECAR_TOKEN"] = self._sidecar_token
        # The sidecar exits when its stdin (the pipe below) hits EOF, so a
        # gateway death of ANY kind — including SIGKILL, where disconnect()
        # never runs — can't leave it orphaned on the port.
        env["PHOTON_SIDECAR_WATCH_STDIN"] = "1"

        try:
            patch = subprocess.run(  # noqa: S603
                [
                    self._node_bin,
                    str(_SIDECAR_DIR / "patch-spectrum-mixed-attachments.mjs"),
                    str(_SIDECAR_DIR),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if patch.returncode != 0:
                raise RuntimeError((patch.stderr or patch.stdout or "").strip())
            if patch.stderr.strip():
                logger.debug("[photon] %s", patch.stderr.strip())
        except Exception as exc:
            logger.warning(
                "[photon] failed to apply Spectrum mixed attachment patch: %s",
                exc,
            )

        self._sidecar_proc = subprocess.Popen(  # noqa: S603
            [self._node_bin, str(_SIDECAR_DIR / "index.mjs")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=(sys.platform != "win32"),
        )

        # Pump sidecar stderr/stdout into our logger so users see crashes.
        loop = asyncio.get_event_loop()
        self._sidecar_supervisor_task = loop.create_task(
            self._supervise_sidecar(self._sidecar_proc)
        )

        # Wait for /healthz to come up — give it up to 15s on cold start.
        deadline = time.time() + 15.0
        last_err: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=2.0) as client:
            while time.time() < deadline:
                if self._sidecar_proc.poll() is not None:
                    raise RuntimeError(
                        f"Photon sidecar exited with code "
                        f"{self._sidecar_proc.returncode} before becoming ready"
                    )
                try:
                    resp = await client.post(
                        f"http://{self._sidecar_bind}:{self._sidecar_port}/healthz",
                        headers={"X-Hermes-Sidecar-Token": self._sidecar_token},
                    )
                    if resp.status_code == 200:
                        return
                except httpx.RequestError as e:
                    last_err = e
                await asyncio.sleep(0.2)
        raise RuntimeError(
            f"Photon sidecar did not become ready within 15s: {last_err}"
        )

    async def _supervise_sidecar(self, proc: subprocess.Popen) -> None:
        """Pump the sidecar's stdout/stderr into our logger."""
        if proc.stdout is None:  # subprocess was launched without stdout=PIPE
            return
        stdout = proc.stdout
        loop = asyncio.get_event_loop()
        try:
            while True:
                line = await loop.run_in_executor(None, stdout.readline)
                if not line:
                    break
                logger.info("[photon-sidecar] %s", line.decode("utf-8", "replace").rstrip())
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[photon-sidecar] supervisor exited: %s", e)

    async def _stop_sidecar(self) -> None:
        proc = self._sidecar_proc
        if proc is None:
            return
        try:
            # Closing our end of the stdin pipe is itself a shutdown signal
            # (the sidecar watches for EOF), and covers the case where the
            # HTTP call below can't get through.
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            # Polite shutdown first.
            if self._http_client is not None:
                try:
                    await self._http_client.post(
                        f"http://{self._sidecar_bind}:{self._sidecar_port}/shutdown",
                        headers={"X-Hermes-Sidecar-Token": self._sidecar_token},
                        timeout=2.0,
                    )
                except Exception:
                    pass
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                if sys.platform != "win32":
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)  # windows-footgun: ok
                    except (ProcessLookupError, PermissionError):
                        proc.terminate()
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
        finally:
            self._sidecar_proc = None
            if self._sidecar_supervisor_task is not None:
                self._sidecar_supervisor_task.cancel()
                self._sidecar_supervisor_task = None

    # -- Outbound ----------------------------------------------------------

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        return await self._sidecar_send(chat_id, self.format_message(content), reply_to=reply_to)

    # -- Outbound media (iMessage parity) -----
    #
    # Photon ships outbound attachments via spectrum-ts' `attachment()` /
    # `voice()` content builders. The sidecar's `/send-attachment` endpoint
    # wraps `space.send(attachment(path, {...}))`. These overrides mirror
    # URL-based helpers cache to a local path first, file-based
    # helpers pass the path straight through.

    async def send_image(
        self,
        chat_id: str,
        image_url: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        try:
            from gateway.platforms.base import cache_image_from_url

            local_path = await cache_image_from_url(image_url)
        except Exception:
            # Couldn't fetch the URL — fall back to sending it as text.
            return await super().send_image(chat_id, image_url, caption, reply_to)
        return await self._sidecar_send_attachment(
            chat_id, local_path, caption=caption, reply_to=reply_to,
        )

    async def send_image_file(
        self,
        chat_id: str,
        image_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> SendResult:
        return await self._sidecar_send_attachment(
            chat_id, image_path, caption=caption, reply_to=reply_to,
        )

    async def send_voice(
        self,
        chat_id: str,
        audio_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> SendResult:
        return await self._sidecar_send_attachment(
            chat_id, audio_path, caption=caption, kind="voice", reply_to=reply_to,
        )

    async def send_video(
        self,
        chat_id: str,
        video_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> SendResult:
        return await self._sidecar_send_attachment(
            chat_id, video_path, caption=caption, reply_to=reply_to,
        )

    async def send_document(
        self,
        chat_id: str,
        file_path: str,
        caption: Optional[str] = None,
        file_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> SendResult:
        return await self._sidecar_send_attachment(
            chat_id, file_path, name=file_name, caption=caption, reply_to=reply_to,
        )

    async def send_animation(
        self,
        chat_id: str,
        animation_url: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        # iMessage renders GIFs inline as ordinary image attachments.
        return await self.send_image(
            chat_id, animation_url, caption, reply_to, metadata,
        )

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        # Deliberate no-op: Photon typing currently maps to Spectrum
        # ``typing()`` -> low-level ``ChatsResource.setTyping``, which is not
        # reliable enough for normal operation. Do not consult config/env here;
        # re-enabling requires replacing this with an explicitly safe path.
        del chat_id, metadata
        return None

    async def stop_typing(self, chat_id: str) -> None:
        # See send_typing(): stopping would hit the same unreliable Photon
        # setTyping route, so this remains a no-op too.
        del chat_id
        return None

    # -- Reactions (tapbacks) -----------------------------------------------
    #
    # Same lifecycle-hook pattern as Telegram/Discord: 👀 while processing,
    # swapped for 👍/👎 on completion. Opt-in via PHOTON_REACTIONS — iMessage
    # is a personal-texting channel, and a tapback on every text is noisy.

    _SENT_IDS_MAX = 1000
    _LAST_INBOUND_CHATS_MAX = 200

    def _record_sent_message(self, message_id: Optional[str]) -> None:
        if not message_id:
            return
        sent = self._sent_message_ids
        if message_id in sent:
            del sent[message_id]  # refresh insertion order
        sent[message_id] = time.time()
        if len(sent) > self._SENT_IDS_MAX:
            for old in list(sent.keys())[: len(sent) - self._SENT_IDS_MAX]:
                del sent[old]

    def _record_sent_thread_root(
        self, message_id: Optional[str], reply_to: Optional[str]
    ) -> None:
        if not message_id or not reply_to:
            return
        root = self._sent_thread_roots.get(reply_to) or reply_to
        roots = self._sent_thread_roots
        if message_id in roots:
            del roots[message_id]
        roots[message_id] = root
        if len(roots) > self._SENT_IDS_MAX:
            for old in list(roots.keys())[: len(roots) - self._SENT_IDS_MAX]:
                del roots[old]

    def _thread_root_for_reply(
        self,
        chat_id: str,
        reply_to_message_id: Optional[str],
        thread_root_message_id: Optional[str],
    ) -> Optional[str]:
        root = thread_root_message_id or None
        if reply_to_message_id:
            root = root or self._sent_thread_roots.get(reply_to_message_id) or reply_to_message_id
        if root:
            self._last_thread_root_by_chat[self._normalize_chat_key(chat_id)] = root
        return root

    # A DM space is addressable two ways — the chat GUID (`any;-;+1555...`)
    # that inbound events carry, and the bare E.164 phone that home-channel
    # config typically uses. The sidecar's resolveSpace treats them as the
    # same space; normalize to the bare phone so the last-inbound tracker
    # does too (mirrors phoneTargetFromSpaceId in sidecar/index.mjs).
    _DM_CHAT_GUID_RE = re.compile(r"^any;-;(\+\d{6,})$")

    @classmethod
    def _normalize_chat_key(cls, chat_id: str) -> str:
        match = cls._DM_CHAT_GUID_RE.match(chat_id)
        return match.group(1) if match else chat_id

    def _record_last_inbound(
        self, chat_id: Optional[str], message_id: Optional[str]
    ) -> None:
        if not chat_id or not message_id:
            return
        key = self._normalize_chat_key(chat_id)
        last = self._last_inbound_by_chat
        if key in last:
            del last[key]  # refresh insertion order
        last[key] = message_id
        if len(last) > self._LAST_INBOUND_CHATS_MAX:
            for old in list(last.keys())[
                : len(last) - self._LAST_INBOUND_CHATS_MAX
            ]:
                del last[old]

    def _reactions_enabled(self) -> bool:
        return os.getenv("PHOTON_REACTIONS", "false").strip().lower() in {
            "true", "1", "yes", "on",
        }

    async def _add_reaction(
        self, chat_id: str, message_id: str, emoji: str
    ) -> bool:
        """Tapback ``emoji`` onto a message. Soft-fails (False), never raises."""
        try:
            await self._sidecar_call(
                "/react",
                {"spaceId": chat_id, "messageId": message_id, "emoji": emoji},
            )
            return True
        except Exception as e:
            logger.debug("[photon] add_reaction failed: %s", e)
            return False

    async def _remove_reaction(self, chat_id: str, message_id: str) -> bool:
        """Retract our tapback from a message. Soft-fails (False), never raises.

        The sidecar tracks one reaction handle per target message; after a
        sidecar restart the handle is gone and removal is best-effort (the
        stale tapback self-heals when the next reaction replaces it).
        """
        try:
            await self._sidecar_call(
                "/unreact", {"spaceId": chat_id, "messageId": message_id},
            )
            return True
        except Exception as e:
            logger.debug("[photon] remove_reaction failed: %s", e)
            return False

    # -- Agent-facing reactions (send_message action="react") ---------------
    #
    # Unlike the lifecycle hooks below, these are deliberate agent intents,
    # so they are NOT gated by PHOTON_REACTIONS (that env var exists to mute
    # the automatic per-message tapback noise, not explicit requests).

    async def add_reaction(
        self,
        chat_id: str,
        emoji: str,
        message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Tapback ``emoji`` onto a message in ``chat_id``.

        Without ``message_id``, targets the chat's most recent inbound
        message (typically the one the agent is responding to). iMessage
        maps ❤️👍👎😂‼️❓ to native tapbacks; anything else uses Apple's
        custom-emoji reaction.
        """
        target = message_id or self._last_inbound_by_chat.get(
            self._normalize_chat_key(chat_id)
        )
        if not target:
            return {
                "success": False,
                "error": "no message to react to — pass message_id (no "
                "inbound message seen in this chat since the gateway started)",
            }
        ok = await self._add_reaction(chat_id, target, emoji)
        if not ok:
            return {
                "success": False,
                "error": "reaction failed (see gateway debug log)",
            }
        return {"success": True, "message_id": target}

    async def remove_reaction(
        self, chat_id: str, message_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retract our tapback from a message (best-effort)."""
        target = message_id or self._last_inbound_by_chat.get(
            self._normalize_chat_key(chat_id)
        )
        if not target:
            return {
                "success": False,
                "error": "no message to unreact — pass message_id",
            }
        ok = await self._remove_reaction(chat_id, target)
        if not ok:
            return {
                "success": False,
                "error": "unreact failed (see gateway debug log)",
            }
        return {"success": True, "message_id": target}

    async def on_processing_start(self, event: MessageEvent) -> None:
        """Tapback 👀 on the triggering message while the agent works."""
        if not self._reactions_enabled():
            return
        chat_id = getattr(event.source, "chat_id", None)
        message_id = getattr(event, "message_id", None)
        if chat_id and message_id:
            await self._add_reaction(chat_id, message_id, "\U0001f440")

    async def on_processing_complete(
        self, event: MessageEvent, outcome: ProcessingOutcome
    ) -> None:
        """Swap the 👀 progress tapback for a 👍/👎 result.

        Remove-then-add rather than a bare replace: deterministic whether the
        platform replaces a sender's previous tapback or stacks them, and it
        keeps the sidecar's reaction-handle slot coherent.
        """
        if not self._reactions_enabled():
            return
        chat_id = getattr(event.source, "chat_id", None)
        message_id = getattr(event, "message_id", None)
        if not chat_id or not message_id:
            return
        await self._remove_reaction(chat_id, message_id)
        if outcome == ProcessingOutcome.SUCCESS:
            await self._add_reaction(chat_id, message_id, "\U0001f44d")
        elif outcome == ProcessingOutcome.FAILURE:
            await self._add_reaction(chat_id, message_id, "\U0001f44e")
        # CANCELLED: leave the message unreacted.

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Return whatever we know about a Spectrum space id.

        Photon's ``space.id`` is opaque; the inbound event also carries the
        DM/group type, but here we only have the id, so infer conservatively.
        """
        return {"name": chat_id, "type": "dm", "id": chat_id}

    def format_message(self, content: str) -> str:
        # Markdown is passed through verbatim — the sidecar sends it with the
        # markdown() builder and iMessage renders it. The strip path remains
        # as the PHOTON_MARKDOWN=false kill-switch.
        if _markdown_enabled():
            return content
        return strip_markdown(content)

    async def _send_with_retry(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Any = None,
        max_retries: int = 2,
        base_delay: float = 2.0,
    ) -> SendResult:
        """Retry sends without the generic Markdown banner.

        Photon replies are markdown (rendered by iMessage) or stripped plain
        text under ``PHOTON_MARKDOWN=false`` — either way the gateway's
        generic banner never applies.
        """
        text = self.format_message(content)
        result = await self.send(
            chat_id=chat_id,
            content=text,
            reply_to=reply_to,
            metadata=metadata,
        )
        if result.success:
            return result

        error_str = result.error or ""
        is_network = result.retryable or self._is_retryable_error(error_str)
        if not is_network and self._is_timeout_error(error_str):
            return result

        if is_network:
            for attempt in range(1, max_retries + 1):
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "[photon] Send failed (attempt %d/%d, retrying in %.1fs): %s",
                    attempt, max_retries, delay, error_str,
                )
                await asyncio.sleep(delay)
                result = await self.send(
                    chat_id=chat_id,
                    content=text,
                    reply_to=reply_to,
                    metadata=metadata,
                )
                if result.success:
                    return result
                error_str = result.error or ""
                if not (result.retryable or self._is_retryable_error(error_str)):
                    break
            else:
                logger.error(
                    "[photon] Failed to deliver response after %d retries: %s",
                    max_retries, error_str,
                )
                return result

        logger.warning(
            "[photon] Send failed: %s - retrying plain-text message",
            error_str,
        )
        fallback_result = await self.send(
            chat_id=chat_id,
            content=text[: self.MAX_MESSAGE_LENGTH],
            reply_to=reply_to,
            metadata=metadata,
        )
        if not fallback_result.success:
            logger.error("[photon] Plain-text retry also failed: %s", fallback_result.error)
        return fallback_result

    async def _sidecar_send(
        self,
        space_id: str,
        text: str,
        *,
        reply_to: Optional[str] = None,
    ) -> SendResult:
        if len(text) > self.MAX_MESSAGE_LENGTH:
            logger.warning(
                "[photon] truncating outbound from %d to %d chars",
                len(text), self.MAX_MESSAGE_LENGTH,
            )
            text = text[: self.MAX_MESSAGE_LENGTH]
        body: Dict[str, Any] = {"spaceId": space_id, "text": text}
        if reply_to:
            body["replyToMessageId"] = reply_to
        # Omit the key when disabled so an older sidecar (pre-`format`)
        # keeps accepting the body during a half-upgraded restart.
        if _markdown_enabled():
            body["format"] = "markdown"
        try:
            data = await self._sidecar_call("/send", body)
        except Exception as e:
            return SendResult(success=False, error=str(e))
        self._record_sent_message(data.get("messageId"))
        self._record_sent_thread_root(data.get("messageId"), reply_to)
        return SendResult(success=True, message_id=data.get("messageId"))

    async def _sidecar_send_attachment(
        self,
        space_id: str,
        path: str,
        *,
        name: Optional[str] = None,
        mime_type: Optional[str] = None,
        caption: Optional[str] = None,
        kind: str = "attachment",
        reply_to: Optional[str] = None,
    ) -> SendResult:
        """POST a local file to the sidecar's ``/send-attachment`` endpoint.

        ``kind`` is ``"voice"`` for audio sent as a voice note (downgrades
        to a plain audio attachment on platforms without voice notes),
        otherwise ``"attachment"``. spectrum-ts infers ``name`` and
        ``mimeType`` from the file extension; we only pass overrides when
        Hermes supplied them.
        """
        # Defense-in-depth: re-validate the path before handing it to the
        # Node sidecar. The gateway already filters MEDIA paths, but
        # send_*_file / cron callers may pass arbitrary strings.
        safe_path = self.validate_media_delivery_path(str(path))
        if not safe_path:
            return SendResult(
                success=False, error=f"unsafe or missing attachment path: {path}"
            )
        if not mime_type:
            import mimetypes

            guessed, _ = mimetypes.guess_type(safe_path)
            mime_type = guessed or None
        body: Dict[str, Any] = {
            "spaceId": space_id,
            "path": safe_path,
            "kind": "voice" if kind == "voice" else "attachment",
        }
        if name:
            body["name"] = name
        if mime_type:
            body["mimeType"] = mime_type
        if caption:
            body["caption"] = caption
        if reply_to:
            body["replyToMessageId"] = reply_to
        try:
            data = await self._sidecar_call("/send-attachment", body)
        except Exception as e:
            return SendResult(success=False, error=str(e))
        self._record_sent_message(data.get("messageId"))
        self._record_sent_thread_root(data.get("messageId"), reply_to)
        return SendResult(success=True, message_id=data.get("messageId"))

    async def _sidecar_call(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        # Guard: adapter not yet connected (no sidecar address known).
        if self._http_client is None:
            raise RuntimeError("Photon adapter not connected")
        # Use a fresh client per call so this method is safe when invoked from
        # a worker thread that owns a different event loop than the one the
        # persistent _http_client was created on (e.g. via _run_async in
        # send_message_tool).  The inbound streaming loop continues to use
        # _http_client directly — it always runs on the gateway's loop.
        url = f"http://{self._sidecar_bind}:{self._sidecar_port}{path}"
        headers = {"X-Hermes-Sidecar-Token": self._sidecar_token}
        resp: Any = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(1, 4):
                resp = await client.post(url, json=body, headers=headers)
                if resp.status_code == 200:
                    break
                text = resp.text[:200]
                retryable = resp.status_code in {500, 502, 503, 504} and path in {
                    "/send",
                    "/react",
                }
                if not retryable or attempt >= 3:
                    raise RuntimeError(
                        f"Photon sidecar {path} returned {resp.status_code}: {text}"
                    )
                logger.warning(
                    "[photon] sidecar %s returned %d (attempt %d/3), retrying: %s",
                    path,
                    resp.status_code,
                    attempt,
                    text,
                )
                await asyncio.sleep(1.5 * attempt)
        assert resp is not None
        if resp.status_code != 200:
            raise RuntimeError(
                f"Photon sidecar {path} returned {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json() or {}
        if not data.get("ok"):
            raise RuntimeError(
                f"Photon sidecar {path} reported error: {data.get('error')}"
            )
        return data


# ---------------------------------------------------------------------------
# Helpers

def _attachment_message_type(mime: str) -> MessageType:
    mime = (mime or "").lower()
    if mime.startswith("image/"):
        return MessageType.PHOTO
    if mime.startswith("video/"):
        return MessageType.VIDEO
    if mime.startswith("audio/"):
        return MessageType.AUDIO
    if mime.startswith("application/"):
        return MessageType.DOCUMENT
    return MessageType.DOCUMENT


# MIME → file-extension maps for caching inbound attachment bytes. These mirror
# iMessage media naming.
_IMAGE_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/heic": ".jpg",
    "image/heif": ".jpg",
    "image/tiff": ".jpg",
}
_AUDIO_EXT_BY_MIME = {
    "audio/mp3": ".mp3",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-caf": ".caf",
    "audio/mp4": ".m4a",
    "audio/aac": ".m4a",
    "audio/amr": ".amr",
    "audio/aiff": ".aiff",
    "audio/opus": ".opus",
    "audio/flac": ".flac",
}

# Extension → audio MIME, used as a fallback when the inbound Spectrum event
# carries an audio file (e.g. ``Audio Message.caf``) but the MIME field is empty
# or generic. Keeps sebOS ingest's MIME coherent with the cached file.
_AUDIO_MIME_BY_EXT = {
    ".caf": "audio/x-caf",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".aac": "audio/aac",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".amr": "audio/amr",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".flac": "audio/flac",
}

# File extensions Hermes treats as audio for the journal ingest gate even when
# the upstream MIME is missing or generic. iMessage voice notes commonly arrive
# as ``Audio Message.caf`` with no MIME populated on the Spectrum event.
_AUDIO_EXTENSIONS = frozenset(_AUDIO_MIME_BY_EXT.keys())


def _path_looks_like_audio(path: Optional[str]) -> bool:
    """Return True when ``path`` carries an audio extension Hermes recognizes."""
    if not path:
        return False
    return Path(path).suffix.lower() in _AUDIO_EXTENSIONS


def _cache_inbound_attachment(
    content: Dict[str, Any],
    name: str,
    mime: str,
    *,
    force_audio: bool = False,
) -> Optional[str]:
    """Decode a base64-inlined inbound attachment and cache it locally.

    The sidecar inlines the attachment bytes as ``content["data"]`` (base64).
    We decode them and route to the shared media cache by MIME type, returning
    the cached absolute path so the caller can populate ``media_urls`` (which
    the gateway then hands to the model). Returns ``None`` when there are no
    bytes (over the sidecar's inline cap or a failed read) or when caching
    fails, so the caller can fall back to a text marker.
    """
    data_b64 = content.get("data")
    if not data_b64:
        return None
    try:
        raw = base64.b64decode(data_b64)
    except (ValueError, TypeError) as exc:
        logger.warning("[photon] failed to decode inbound attachment bytes: %s", exc)
        return None

    from gateway.platforms.base import (
        cache_audio_from_bytes,
        cache_document_from_bytes,
        cache_image_from_bytes,
    )

    mime = (mime or "").lower()
    # Prefer the real extension from the filename; fall back to the MIME map.
    suffix = Path(name).suffix if name else ""
    try:
        if mime.startswith("image/"):
            ext = suffix or _IMAGE_EXT_BY_MIME.get(mime, ".jpg")
            try:
                return cache_image_from_bytes(raw, ext)
            except ValueError:
                # Bytes don't look like a supported image (e.g. HEIC magic) —
                # still deliver them as a document rather than dropping them.
                return cache_document_from_bytes(raw, name)
        if force_audio or mime.startswith("audio/"):
            ext = suffix or _AUDIO_EXT_BY_MIME.get(
                mime, ".m4a" if force_audio else ".mp3"
            )
            return cache_audio_from_bytes(raw, ext)
        # Video, application/*, and everything else → document cache.
        return cache_document_from_bytes(raw, name)
    except Exception as exc:
        logger.warning("[photon] failed to cache inbound attachment %s: %s", name, exc)
        return None


# ---------------------------------------------------------------------------
# Standalone (out-of-process) send for cron deliveries when the gateway
# is not co-resident.  Reuses a live sidecar already listening on the
# configured port (cron processes cannot spawn the sidecar themselves).

async def _standalone_send(
    pconfig: PlatformConfig,
    chat_id: str,
    message: str,
    *,
    thread_id: Optional[str] = None,  # noqa: ARG001 — Spectrum has no threads yet
    media_files: Optional[list] = None,
    force_document: bool = False,  # noqa: ARG001 — iMessage auto-detects file kind
) -> Dict[str, Any]:
    if not HTTPX_AVAILABLE:
        return {"error": "httpx not installed"}
    port = _coerce_port(
        (pconfig.extra or {}).get("sidecar_port") or os.getenv("PHOTON_SIDECAR_PORT"),
        _DEFAULT_SIDECAR_PORT,
    )
    token = os.getenv("PHOTON_SIDECAR_TOKEN")
    if not token:
        return {
            "error": (
                "Photon standalone send requires a running sidecar with "
                "PHOTON_SIDECAR_TOKEN set in the environment. Cron processes "
                "cannot spawn the sidecar themselves."
            )
        }
    base = f"http://{_DEFAULT_SIDECAR_BIND}:{port}"
    headers = {"X-Hermes-Sidecar-Token": token}
    last_message_id: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Text body first (if any), so it leads the conversation.
            if message:
                send_body: Dict[str, Any] = {
                    "spaceId": chat_id,
                    "text": message[:_MAX_MESSAGE_LENGTH],
                }
                if _markdown_enabled():
                    send_body["format"] = "markdown"
                resp = await client.post(
                    f"{base}/send", json=send_body, headers=headers,
                )
                if resp.status_code != 200:
                    return {"error": f"sidecar returned {resp.status_code}: {resp.text[:200]}"}
                data = resp.json() or {}
                if not data.get("ok"):
                    return {"error": data.get("error") or "sidecar reported failure"}
                last_message_id = data.get("messageId")

            # 2. Each attachment as a separate /send-attachment call.
            #    media_files is List[Tuple[path, is_voice]] (see
            #    BasePlatformAdapter.filter_media_delivery_paths).
            import mimetypes

            for media_path, is_voice in media_files or []:
                safe_path = BasePlatformAdapter.validate_media_delivery_path(str(media_path))
                if not safe_path:
                    logger.warning("[photon] standalone send skipping unsafe path")
                    continue
                guessed, _ = mimetypes.guess_type(safe_path)
                att_body: Dict[str, Any] = {
                    "spaceId": chat_id,
                    "path": safe_path,
                    "kind": "voice" if is_voice else "attachment",
                }
                if guessed:
                    att_body["mimeType"] = guessed
                resp = await client.post(
                    f"{base}/send-attachment", json=att_body, headers=headers,
                )
                if resp.status_code != 200:
                    return {"error": f"sidecar returned {resp.status_code}: {resp.text[:200]}"}
                data = resp.json() or {}
                if not data.get("ok"):
                    return {"error": data.get("error") or "sidecar reported failure"}
                last_message_id = data.get("messageId") or last_message_id

        return {"success": True, "message_id": last_message_id}
    except Exception as e:
        return {"error": f"Photon standalone send failed: {e}"}


# ---------------------------------------------------------------------------
# Plugin entry point

def register(ctx) -> None:
    """Called by the Hermes plugin loader at startup."""
    # Local import to avoid argparse work at module load; reused for both the
    # gateway-setup hook and the `hermes photon` CLI command below.
    from . import cli as _cli

    ctx.register_platform(
        name="photon",
        label="iMessage via Photon",
        adapter_factory=lambda cfg: PhotonAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=["PHOTON_PROJECT_ID", "PHOTON_PROJECT_SECRET"],
        install_hint=(
            "Run: hermes photon setup  (logs in via device flow, creates a "
            "Spectrum project, links your phone number, installs the "
            "spectrum-ts sidecar)."
        ),
        # Surfaces Photon in `hermes gateway setup` alongside every other
        # channel — same unified onboarding wizard, no Photon-only detour.
        setup_fn=_cli.gateway_setup,
        env_enablement_fn=_env_enablement,
        cron_deliver_env_var="PHOTON_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        allowed_users_env="PHOTON_ALLOWED_USERS",
        allow_all_env="PHOTON_ALLOW_ALL_USERS",
        max_message_length=_MAX_MESSAGE_LENGTH,
        emoji="📱",
        # iMessage carries E.164 phone numbers — treat session descriptions
        # as PII-sensitive so they get redacted before reaching the LLM
        # (matches iMessage handling in _PII_SAFE_PLATFORMS).
        pii_safe=True,
        # iMessage is Seb's clean personal inbox: suppress status/progress/
        # lifecycle chatter and never nag it to become a cron home channel.
        clean_inbox=True,
        # Own Photon outbound shaping (secret redaction + internal-notice
        # suppression) instead of a hardcoded core branch.
        outbound_sanitize_fn=_outbound_sanitize,
        allow_update_command=True,
        platform_hint=(
            "You are communicating via Photon Spectrum (iMessage). "
            "Treat replies like regular text messages — short and friendly. "
            "Markdown is rendered (bold, italics, lists, code), but keep "
            "formatting light and conversational. Recipient identifiers are "
            "E.164 phone numbers; never expose them in responses unless the "
            "user asked. Attachments arrive as metadata only."
        ),
    )

    # Register CLI subcommands — `hermes photon ...`
    ctx.register_cli_command(
        name="photon",
        help="Set up and manage the Photon iMessage integration",
        setup_fn=_cli.register_cli,
        handler_fn=_cli.dispatch,
    )
