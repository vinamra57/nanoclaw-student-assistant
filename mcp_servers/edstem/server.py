"""
Personal EdStem MCP server.

Exposes Ed Discussion tools scoped to the student's own API token.
Runs as a standalone MCP server that NanoClaw connects to via mcporter.

Usage (stdio, default — production VM with venv mount):
    ED_API_TOKEN=<token> ED_COURSE_ID=<id> python -m mcp_servers.edstem.server

Usage (HTTP, cross-platform — dev on Mac, agent container connects to host):
    EDSTEM_TRANSPORT=streamable-http EDSTEM_PORT=8765 \\
    ED_API_TOKEN=<token> ED_COURSE_ID=<id> \\
    python -m mcp_servers.edstem.server
"""

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
    """Create an EdClient from environment variables."""
    token = os.environ.get("ED_API_TOKEN", "")
    course_id_str = os.environ.get("ED_COURSE_ID", "0")
    try:
        course_id = int(course_id_str)
    except ValueError:
        course_id = 0
    return EdClient(api_token=token, course_id=course_id)


def _format_thread(t: dict) -> str:
    """Format a thread dict for display."""
    title = t.get("title", "Untitled")
    category = t.get("category", "")
    header = f"**{title}** [{category}]" if category else f"**{title}**"

    parts = [header]
    if url := t.get("url", ""):
        parts.append(f"Link: {url}")
    if created := t.get("created_at", ""):
        parts.append(f"Posted: {created}")
    if content := t.get("content", ""):
        parts.append(content[:1000] + "..." if len(content) > 1000 else content)
    return "\n".join(parts)


@mcp.tool()
def search_ed(query: str, limit: int = 5) -> str:
    """Search Ed Discussion threads by keyword.

    Use this to find relevant student questions, staff answers,
    announcements, or any course-related discussion.

    Args:
        query: Search keywords (e.g., "midterm", "late policy", "office hours")
        limit: Maximum number of results (default 5)
    """
    client = _get_client()
    if not client.is_configured:
        return "Ed Discussion is not configured. Set ED_API_TOKEN and ED_COURSE_ID."

    threads = client.search_threads(query, limit=min(limit, 20))
    if not threads:
        return f"No Ed Discussion threads found for '{query}'."

    results = [f"Found {len(threads)} thread(s) for '{query}':\n"]
    for t in threads:
        results.append(_format_thread(t))
        results.append("---")
    return "\n".join(results)


@mcp.tool()
def get_ed_announcements(limit: int = 10) -> str:
    """Get recent course announcements from Ed Discussion.

    Announcements contain important updates about deadlines, policy changes,
    exam info, and other course logistics.

    Args:
        limit: Maximum number of announcements (default 10)
    """
    client = _get_client()
    if not client.is_configured:
        return "Ed Discussion is not configured. Set ED_API_TOKEN and ED_COURSE_ID."

    announcements = client.get_announcements(limit=limit)
    if not announcements:
        return "No announcements found."

    results = [f"Found {len(announcements)} announcement(s):\n"]
    for a in announcements:
        results.append(_format_thread(a))
        results.append("---")
    return "\n".join(results)


@mcp.tool()
def get_ed_pinned() -> str:
    """Get pinned threads from Ed Discussion.

    Pinned threads typically contain important course information like
    syllabus links, resource lists, FAQ, and logistics.
    """
    client = _get_client()
    if not client.is_configured:
        return "Ed Discussion is not configured. Set ED_API_TOKEN and ED_COURSE_ID."

    pinned = client.get_pinned_threads()
    if not pinned:
        return "No pinned threads found."

    results = [f"Found {len(pinned)} pinned thread(s):\n"]
    for p in pinned:
        results.append(_format_thread(p))
        results.append("---")
    return "\n".join(results)


@mcp.tool()
def get_ed_thread(thread_id: int) -> str:
    """Get the full content of a specific Ed Discussion thread.

    Use this after search_ed to read the full details of a thread,
    including staff answers and comments.

    Args:
        thread_id: The numeric ID of the thread
    """
    client = _get_client()
    if not client.is_configured:
        return "Ed Discussion is not configured. Set ED_API_TOKEN and ED_COURSE_ID."

    thread = client.get_thread_content(thread_id)
    if not thread:
        return f"Thread {thread_id} not found."

    parts = [_format_thread(thread)]
    answers = thread.get("answers", [])
    comments = thread.get("comments", [])
    if answers:
        parts.append("\n**Answers:**")
        for i, a in enumerate(answers, 1):
            parts.append(f"{i}. {a}")
    if comments:
        parts.append("\n**Comments:**")
        for i, c in enumerate(comments, 1):
            parts.append(f"{i}. {c}")
    return "\n".join(parts)


@mcp.tool()
def get_ed_unread(limit: int = 20) -> str:
    """Get unread threads from Ed Discussion.

    Shows new or updated threads that haven't been read yet.
    Useful for answering "what's new on Ed" or "any updates".

    Args:
        limit: Maximum number of unread threads (default 20)
    """
    client = _get_client()
    if not client.is_configured:
        return "Ed Discussion is not configured. Set ED_API_TOKEN and ED_COURSE_ID."

    threads = client.get_unread_threads(limit=limit)
    if not threads:
        return "No unread threads found — you're all caught up!"

    results = [f"Found {len(threads)} unread thread(s):\n"]
    for t in threads:
        results.append(_format_thread(t))
        results.append("---")
    return "\n".join(results)


if __name__ == "__main__":
    transport = os.environ.get("EDSTEM_TRANSPORT", "stdio")
    if transport not in ("stdio", "sse", "streamable-http"):
        raise SystemExit(
            f"EDSTEM_TRANSPORT must be one of stdio|sse|streamable-http, got {transport!r}"
        )
    mcp.run(transport=transport)
