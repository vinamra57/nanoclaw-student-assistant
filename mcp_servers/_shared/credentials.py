"""Per-call credential fetcher for MCP servers (Edstem, Canvas, Gradescope).

Each MCP server in this layer used to read its student-personal credential
from process env (ED_API_TOKEN, CANVAS_API_TOKEN, etc.) at startup. That
forced staff to provision per-student container env, defeated the
self-service onboarding model, and required restart-on-rotation. The new
model: ChatCSE owns the credential (encrypted in `provider_credentials`),
and each MCP server fetches its credential on demand using the container's
`CHATCSE_AGENT_TOKEN` (which is the only per-student secret the container
sees). 5-minute cache keeps the per-call cost ~zero.

Trust boundary:
  - The container holds CHATCSE_AGENT_TOKEN (issued by ChatCSE for ONE
    user_id).
  - ChatCSE returns the credential plaintext over HTTPS in the response
    body (the only way the agent can call external APIs as the user).
  - Plaintext is held in memory inside this MCP server process for the
    cache TTL, then re-fetched. Never written to disk; never logged.

Configuration: requires `CHATCSE_AGENT_TOKEN` + `CHATCSE_BASE_URL` in env.
On any failure to fetch, returns None — the calling MCP server should
surface a clean "not configured" message asking the student to
`/edstem-key` (etc.) via Discord.
"""

import logging
import os
import time
from threading import Lock

import requests

logger = logging.getLogger(__name__)

# Cache TTL — long enough to amortize across normal tool-call bursts, short
# enough that a /provider-key update propagates quickly.
_CACHE_TTL_SECONDS = 5 * 60

# Per-process cache: provider → (value, fetched_at_epoch, metadata).
# One entry per provider; in-memory only. Reset on process restart.
_cache: dict[str, tuple[str, float, dict]] = {}
_cache_lock = Lock()


def _env(name: str) -> str:
    """Read an env var or return ''."""
    return os.environ.get(name, "").strip()


def _base_url() -> str:
    """Resolve ChatCSE base URL (where /api/agent/credentials lives).

    Priority: CHATCSE_BASE_URL > VIRTUAL_TA_URL with port shifted from
    8001 → 8000 (MCP vs REST) > host.docker.internal default.
    """
    explicit = _env("CHATCSE_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    vta = _env("VIRTUAL_TA_URL")
    if vta:
        return vta.replace(":8001", ":8000").rstrip("/")
    return "http://host.docker.internal:8000"


def get_provider_credential(provider: str) -> tuple[str, dict] | None:
    """Return `(value, metadata)` for the student's credential, or None.

    `value` is the plaintext (e.g. Edstem token, Canvas token,
    `email:password` for Gradescope). `metadata` is a dict of public
    context (e.g. `{"base_url": "https://canvas.uw.edu"}` for Canvas);
    empty dict if unset.

    Cached for `_CACHE_TTL_SECONDS` per provider. Calls ChatCSE's
    `/api/agent/credentials/<provider>` endpoint with the container's
    `CHATCSE_AGENT_TOKEN`. The endpoint returns 404 if the student hasn't
    set the credential yet; we return None in that case.

    Never logs the value. On HTTP error the warning includes provider +
    status code only.
    """
    now = time.time()
    with _cache_lock:
        cached = _cache.get(provider)
        if cached and (now - cached[1]) < _CACHE_TTL_SECONDS:
            value, _, metadata = cached
            return value, metadata  # type: ignore[return-value]

    token = _env("CHATCSE_AGENT_TOKEN")
    if not token:
        logger.warning("credential fetch skipped — CHATCSE_AGENT_TOKEN not set in env")
        return None

    url = f"{_base_url()}/api/agent/credentials/{provider}"
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"credential fetch network error for {provider}: {e}")
        return None

    if r.status_code == 404:
        # Student hasn't set this credential yet — totally normal.
        return None
    if r.status_code != 200:
        logger.warning(
            f"credential fetch HTTP {r.status_code} for {provider}: "
            f"{(r.text or '')[:120]}"
        )
        return None

    try:
        body = r.json()
        value = body.get("value")
        metadata = body.get("metadata") or {}
    except Exception as e:
        logger.warning(f"credential fetch parse error for {provider}: {e}")
        return None
    if not isinstance(value, str) or not value:
        return None
    if not isinstance(metadata, dict):
        metadata = {}

    with _cache_lock:
        _cache[provider] = (value, now, metadata)  # type: ignore[assignment]
    return value, metadata


def invalidate(provider: str | None = None) -> None:
    """Drop cached value(s). Called by tests; the production path relies on
    the TTL alone."""
    with _cache_lock:
        if provider is None:
            _cache.clear()
        else:
            _cache.pop(provider, None)
