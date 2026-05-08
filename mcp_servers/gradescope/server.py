"""Personal Gradescope MCP server (best-effort).

Gradescope has no public API. This server uses the `gradescopeapi`
package's HTML parsers; it logs in once with the student's email +
password and reuses the requests Session for subsequent calls.

Wired into NanoClaw via stdio→HTTP bridge in mcp_servers/gradescope-bridge/,
same pattern as Edstem and Canvas.

Credentials come from ChatCSE on demand via the
`mcp_servers._shared.credentials` helper — no per-student secrets in this
process's env. The credential value is `email:password` (single string).
Students rotate via Discord `/gradescope-key`. UW students with SSO-only
accounts must first set a Gradescope-local password (see _not_configured
hint).

Usage (stdio, default):
    CHATCSE_AGENT_TOKEN=<token> CHATCSE_BASE_URL=<url> \\
    python -m mcp_servers.gradescope.server

Usage (HTTP, cross-platform dev):
    GRADESCOPE_TRANSPORT=streamable-http GRADESCOPE_PORT=8767 \\
    CHATCSE_AGENT_TOKEN=<token> CHATCSE_BASE_URL=<url> \\
    python -m mcp_servers.gradescope.server
"""

import json
import logging
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_servers.gradescope.gs_client import GradescopeClient

logger = logging.getLogger(__name__)

_HOST = os.environ.get("GRADESCOPE_HOST", "127.0.0.1")
_PORT = int(os.environ.get("GRADESCOPE_PORT", "8767"))

# Same DNS-rebinding guard exemption as the Edstem and Canvas servers.
_ALLOWED_HOSTS = [
    "127.0.0.1:*",
    "localhost:*",
    "[::1]:*",
    "host.docker.internal:*",
]
_ALLOWED_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
    "http://host.docker.internal:*",
]

mcp = FastMCP(
    "Gradescope Personal",
    host=_HOST,
    port=_PORT,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_ALLOWED_HOSTS,
        allowed_origins=_ALLOWED_ORIGINS,
    ),
)


# Cached client — process-lifetime. Re-instantiated only if env changes,
# which we don't expect mid-process. The client lazily logs in on first call.
_client: GradescopeClient | None = None


def _get_client() -> GradescopeClient:
    """Build a GradescopeClient from the student's credential in ChatCSE.

    The credential value is stored as `email:password` (single string).
    Cached client is reused as long as the credentials match — login is
    expensive, so we keep the session alive across calls.
    """
    global _client
    from mcp_servers._shared.credentials import get_provider_credential

    cred = get_provider_credential("gradescope")
    if not cred:
        return GradescopeClient(email="", password="")
    raw, _ = cred
    if ":" not in raw:
        # Credential present but malformed — surface as not-configured.
        return GradescopeClient(email="", password="")
    email, _, password = raw.partition(":")
    if _client is None or _client.email != email or _client.password != password:
        _client = GradescopeClient(email=email, password=password)
    return _client


def _not_configured() -> str:
    return (
        "Gradescope isn't connected yet. UW students need to set a "
        "Gradescope-local password first: open "
        "https://www.gradescope.com/reset_password in an INCOGNITO browser "
        "(regular browser hijacks the redirect via your active SSO "
        "session). Then in Discord, type `/gradescope-key`, enter "
        "`<your-email>:<that-new-password>` in the modal, and submit. The "
        "value never appears in chat history."
    )


@mcp.tool()
def list_gradescope_courses() -> str:
    """List the student's Gradescope courses (id, name, role).

    Use this to discover course_ids before calling list_gradescope_assignments.
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    rows = c.list_courses()
    if not rows:
        return (
            "No Gradescope courses returned. The login may have failed "
            "(check credentials), or the account has no courses.\n\n"
            "If your account is SSO-only (e.g. UW NetID), Gradescope "
            "rejects direct logins. Set a Gradescope-local password by "
            "opening https://www.gradescope.com/reset_password in an "
            "INCOGNITO browser window (regular browser hijacks the "
            "redirect via your active SSO session). After resetting, DM "
            "/gradescope-key <email>:<that-new-password> to update."
        )
    return json.dumps(rows, indent=2, default=str)


@mcp.tool()
def list_gradescope_assignments(course_id: str) -> str:
    """List assignments for a Gradescope course.

    Args:
        course_id: The string Gradescope course id (e.g. "1234567").
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    rows = c.list_assignments(course_id)
    if not rows:
        return f"No assignments found for course {course_id}."
    return json.dumps(rows, indent=2, default=str)


if __name__ == "__main__":
    from typing import Literal, cast

    transport = os.environ.get("GRADESCOPE_TRANSPORT", "stdio")
    if transport not in ("stdio", "sse", "streamable-http"):
        raise SystemExit(
            f"GRADESCOPE_TRANSPORT must be stdio|sse|streamable-http, got {transport!r}"
        )
    mcp.run(transport=cast(Literal["stdio", "sse", "streamable-http"], transport))
