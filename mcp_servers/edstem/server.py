"""
Personal EdStem MCP server.

Multi-course: agent first calls `list_ed_courses` to discover what the
student is enrolled in, then drills into a specific course via
`search_ed`, `get_ed_announcements`, etc. (all per-course tools take
`course_id` as a required parameter).

Credentials come from ChatCSE on demand via the `mcp_servers._shared.credentials`
helper — no per-student secrets in this process's env. The only secret
this server needs is `CHATCSE_AGENT_TOKEN` (which authenticates it to
ChatCSE for the credential fetch). Students rotate their Edstem token via
the Discord `/edstem-key` command, and the change propagates within the
helper's 5-minute cache TTL.

Usage (stdio, default):
    CHATCSE_AGENT_TOKEN=<token> CHATCSE_BASE_URL=<url> \\
    python -m mcp_servers.edstem.server

Usage (HTTP, cross-platform — dev on Mac, agent container connects to host):
    EDSTEM_TRANSPORT=streamable-http EDSTEM_PORT=8765 \\
    CHATCSE_AGENT_TOKEN=<token> CHATCSE_BASE_URL=<url> \\
    python -m mcp_servers.edstem.server
"""

import json
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_servers.edstem.ed_client import EdClient

# Bind loopback by default — the agent container reaches us via
# host.docker.internal, which Docker maps to the host's loopback interface.
# Exposing on 0.0.0.0 would let any host on the network call this server
# with the student's Ed token.
_HOST = os.environ.get("EDSTEM_HOST", "127.0.0.1")
_PORT = int(os.environ.get("EDSTEM_PORT", "8765"))

# FastMCP enables DNS-rebinding protection by default, allowing only Host
# headers matching localhost/loopback. Agent containers reach us through
# the docker host gateway with `Host: host.docker.internal:<port>`, which
# the default policy rejects with HTTP 421. We add that one host while
# keeping protection on for everything else.
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
    "EdStem Personal",
    host=_HOST,
    port=_PORT,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_ALLOWED_HOSTS,
        allowed_origins=_ALLOWED_ORIGINS,
    ),
)


def _get_client() -> EdClient:
    """Build an EdClient from the student's credential in ChatCSE.

    Fetches the token via the credential helper (5-min cache) — no env
    var dependency. Returns a not-configured client when the credential
    is missing so the tool surface degrades cleanly instead of crashing.
    """
    from mcp_servers._shared.credentials import get_provider_credential

    cred = get_provider_credential("edstem")
    token = cred[0] if cred else ""
    return EdClient(api_token=token)


def _not_configured() -> str:
    return (
        "Ed Discussion isn't connected yet. To connect: in Discord, type "
        "`/edstem-key`, paste your Ed API token (from "
        "https://edstem.org/us/settings/api-tokens) into the modal, and "
        "submit. The token never appears in chat history."
    )


@mcp.tool()
def list_ed_courses() -> str:
    """List the student's active Ed Discussion courses.

    Use this first to find the course_id for any other Ed tool. Returns
    JSON with id/code/name/year/session/role for each enrollment.
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    courses = c.list_courses()
    if not courses:
        return "No active Ed courses found for this token."
    return json.dumps(courses, indent=2)


@mcp.tool()
def search_ed(course_id: int, query: str, limit: int = 5) -> str:
    """Search Ed Discussion threads in one course by keyword.

    Use this to find relevant student questions, staff answers,
    announcements, or any course-related discussion.

    Args:
        course_id: Numeric Ed course id (from list_ed_courses).
        query: Search keywords (e.g., "midterm", "late policy").
        limit: Maximum number of results (default 5).
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()

    threads = c.search_threads(course_id, query, limit=min(limit, 20))
    if not threads:
        return f"No Ed threads in course {course_id} for '{query}'."
    return json.dumps(threads, indent=2)


@mcp.tool()
def get_ed_announcements(course_id: int, limit: int = 10) -> str:
    """Get recent announcements from one Ed course.

    Args:
        course_id: Numeric Ed course id (from list_ed_courses).
        limit: Maximum number of announcements (default 10).
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()

    items = c.get_announcements(course_id, limit=limit)
    if not items:
        return f"No announcements in course {course_id}."
    return json.dumps(items, indent=2)


@mcp.tool()
def get_ed_pinned(course_id: int) -> str:
    """Get pinned threads from one Ed course.

    Args:
        course_id: Numeric Ed course id (from list_ed_courses).
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()

    items = c.get_pinned_threads(course_id)
    if not items:
        return f"No pinned threads in course {course_id}."
    return json.dumps(items, indent=2)


@mcp.tool()
def get_ed_thread(thread_id: int) -> str:
    """Get the full content of a specific Ed thread.

    Use this after search_ed to read full details including answers
    and comments. Thread IDs are globally unique across courses, so no
    course_id is needed.

    Args:
        thread_id: Numeric Ed thread id.
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()

    thread = c.get_thread_content(thread_id)
    if not thread:
        return f"Thread {thread_id} not found."
    return json.dumps(thread, indent=2)


@mcp.tool()
def get_ed_unread(course_id: int, limit: int = 20) -> str:
    """Get unread threads in one Ed course.

    Args:
        course_id: Numeric Ed course id (from list_ed_courses).
        limit: Maximum number of unread threads (default 20).
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()

    threads = c.get_unread_threads(course_id, limit=limit)
    if not threads:
        return f"No unread threads in course {course_id} — all caught up."
    return json.dumps(threads, indent=2)


if __name__ == "__main__":
    from typing import Literal, cast

    transport = os.environ.get("EDSTEM_TRANSPORT", "stdio")
    if transport not in ("stdio", "sse", "streamable-http"):
        raise SystemExit(
            f"EDSTEM_TRANSPORT must be one of stdio|sse|streamable-http, got {transport!r}"
        )
    mcp.run(transport=cast(Literal["stdio", "sse", "streamable-http"], transport))
