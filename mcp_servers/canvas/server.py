"""Personal Canvas LMS MCP server.

Exposes a small set of read-only Canvas tools scoped to the student's own
API token + institution. Wired into NanoClaw via a stdio→HTTP bridge in
mcp_servers/canvas-bridge/, same pattern as edstem.

Usage (stdio, default):
    CANVAS_API_TOKEN=<token> CANVAS_BASE_URL=https://canvas.uw.edu \\
    python -m mcp_servers.canvas.server

Usage (HTTP, cross-platform dev):
    CANVAS_TRANSPORT=streamable-http CANVAS_PORT=8766 \\
    CANVAS_API_TOKEN=<token> CANVAS_BASE_URL=https://canvas.uw.edu \\
    python -m mcp_servers.canvas.server
"""

import json
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_servers.canvas.canvas_client import CanvasClient

# Loopback-only by default; agent containers reach us via host.docker.internal
# which Docker Desktop maps to host loopback on macOS.
_HOST = os.environ.get("CANVAS_HOST", "127.0.0.1")
_PORT = int(os.environ.get("CANVAS_PORT", "8766"))

# Same DNS-rebinding allow-list reasoning as the EdStem server: the default
# blocks `Host: host.docker.internal:<port>` with HTTP 421.
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
    "Canvas Personal",
    host=_HOST,
    port=_PORT,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_ALLOWED_HOSTS,
        allowed_origins=_ALLOWED_ORIGINS,
    ),
)


def _client() -> CanvasClient:
    return CanvasClient(
        api_token=os.environ.get("CANVAS_API_TOKEN", ""),
        base_url=os.environ.get("CANVAS_BASE_URL", ""),
    )


def _not_configured() -> str:
    return (
        "Canvas is not configured. Set CANVAS_API_TOKEN and CANVAS_BASE_URL, "
        "or DM `/canvas-key <token>` to your bot to wire it from chat."
    )


@mcp.tool()
def list_canvas_courses() -> str:
    """List the student's active Canvas courses (id, name, code, term).

    Use this to discover course IDs before calling other Canvas tools.
    """
    c = _client()
    if not c.is_configured:
        return _not_configured()
    courses = c.list_courses()
    if not courses:
        return "No active Canvas courses found."
    return json.dumps(courses, indent=2)


@mcp.tool()
def list_canvas_assignments(course_id: int, limit: int = 25) -> str:
    """List assignments for a Canvas course, ordered by due date.

    Args:
        course_id: Numeric Canvas course id (from list_canvas_courses).
        limit: Max number of assignments (default 25).
    """
    c = _client()
    if not c.is_configured:
        return _not_configured()
    items = c.list_assignments(course_id, limit=limit)
    if not items:
        return f"No assignments returned for course {course_id}."
    return json.dumps(items, indent=2)


@mcp.tool()
def get_canvas_assignment(course_id: int, assignment_id: int) -> str:
    """Fetch full details of a single Canvas assignment."""
    c = _client()
    if not c.is_configured:
        return _not_configured()
    a = c.get_assignment(course_id, assignment_id)
    if not a:
        return f"Assignment {assignment_id} not found in course {course_id}."
    return json.dumps(a, indent=2)


@mcp.tool()
def list_canvas_announcements(course_id: int, limit: int = 10) -> str:
    """List recent Canvas announcements for a course."""
    c = _client()
    if not c.is_configured:
        return _not_configured()
    items = c.list_announcements(course_id, limit=limit)
    if not items:
        return f"No announcements for course {course_id}."
    return json.dumps(items, indent=2)


@mcp.tool()
def list_canvas_grades(course_id: int) -> str:
    """List the student's per-assignment grades for a Canvas course."""
    c = _client()
    if not c.is_configured:
        return _not_configured()
    items = c.list_grades(course_id)
    if not items:
        return f"No graded submissions for course {course_id}."
    return json.dumps(items, indent=2)


@mcp.tool()
def get_canvas_submission(course_id: int, assignment_id: int) -> str:
    """Fetch the student's submission status for one Canvas assignment."""
    c = _client()
    if not c.is_configured:
        return _not_configured()
    s = c.get_submission(course_id, assignment_id)
    if not s:
        return f"No submission record for assignment {assignment_id}."
    return json.dumps(s, indent=2)


if __name__ == "__main__":
    from typing import Literal, cast

    transport = os.environ.get("CANVAS_TRANSPORT", "stdio")
    if transport not in ("stdio", "sse", "streamable-http"):
        raise SystemExit(
            f"CANVAS_TRANSPORT must be one of stdio|sse|streamable-http, got {transport!r}"
        )
    mcp.run(transport=cast(Literal["stdio", "sse", "streamable-http"], transport))
