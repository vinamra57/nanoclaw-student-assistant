"""Tests for the EdStem MCP server tools (multi-course).

Tools fetch credentials from ChatCSE on demand via the shared
`get_provider_credential` helper — `not configured` paths happen when
the helper returns None.
"""

from unittest.mock import patch


def _mock_helper(returns):
    """Patch the credential helper for a single test."""
    return patch(
        "mcp_servers._shared.credentials.get_provider_credential",
        return_value=returns,
    )


def test_list_ed_courses_not_configured():
    from mcp_servers.edstem.server import list_ed_courses

    with _mock_helper(None):
        result = list_ed_courses()
    assert "isn't connected" in result.lower() or "not configured" in result.lower()


def test_search_ed_not_configured():
    from mcp_servers.edstem.server import search_ed

    with _mock_helper(None):
        result = search_ed(99, "test")
    assert "isn't connected" in result.lower() or "not configured" in result.lower()


def test_announcements_not_configured():
    from mcp_servers.edstem.server import get_ed_announcements

    with _mock_helper(None):
        result = get_ed_announcements(99)
    assert "isn't connected" in result.lower() or "not configured" in result.lower()


def test_pinned_not_configured():
    from mcp_servers.edstem.server import get_ed_pinned

    with _mock_helper(None):
        result = get_ed_pinned(99)
    assert "isn't connected" in result.lower() or "not configured" in result.lower()


def test_unread_not_configured():
    from mcp_servers.edstem.server import get_ed_unread

    with _mock_helper(None):
        result = get_ed_unread(99)
    assert "isn't connected" in result.lower() or "not configured" in result.lower()


def test_get_thread_not_configured():
    from mcp_servers.edstem.server import get_ed_thread

    with _mock_helper(None):
        result = get_ed_thread(12345)
    assert "isn't connected" in result.lower() or "not configured" in result.lower()


def test_server_binds_loopback_and_8765_by_default():
    # Defaults must keep the per-student token off any non-loopback iface.
    from mcp_servers.edstem.server import mcp

    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 8765


def test_server_allows_host_docker_internal_for_container_traffic():
    # Without this exemption agent containers get HTTP 421 from FastMCP's
    # DNS-rebinding guard (the Host header is host.docker.internal).
    from mcp_servers.edstem.server import mcp

    sec = mcp.settings.transport_security
    assert sec.enable_dns_rebinding_protection is True
    assert "host.docker.internal:*" in sec.allowed_hosts
    assert "http://host.docker.internal:*" in sec.allowed_origins
    # Default loopback entries must still be there.
    assert "127.0.0.1:*" in sec.allowed_hosts
    assert "localhost:*" in sec.allowed_hosts


def test_helper_returns_token_passes_to_client():
    """When the helper returns a token, the EdClient is constructed with it."""
    from mcp_servers.edstem import server as srv

    with _mock_helper(("test-token-123", {})):
        client = srv._get_client()
    assert client.api_token == "test-token-123"
    assert client.is_configured
