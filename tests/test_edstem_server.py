"""Tests for the EdStem MCP server tools (multi-course)."""

from unittest.mock import patch


@patch.dict("os.environ", {"ED_API_TOKEN": ""})
def test_list_ed_courses_not_configured():
    from mcp_servers.edstem.server import list_ed_courses

    result = list_ed_courses()
    assert "not configured" in result.lower()


@patch.dict("os.environ", {"ED_API_TOKEN": ""})
def test_search_ed_not_configured():
    from mcp_servers.edstem.server import search_ed

    result = search_ed(99, "test")
    assert "not configured" in result.lower()


@patch.dict("os.environ", {"ED_API_TOKEN": ""})
def test_announcements_not_configured():
    from mcp_servers.edstem.server import get_ed_announcements

    result = get_ed_announcements(99)
    assert "not configured" in result.lower()


@patch.dict("os.environ", {"ED_API_TOKEN": ""})
def test_pinned_not_configured():
    from mcp_servers.edstem.server import get_ed_pinned

    result = get_ed_pinned(99)
    assert "not configured" in result.lower()


@patch.dict("os.environ", {"ED_API_TOKEN": ""})
def test_unread_not_configured():
    from mcp_servers.edstem.server import get_ed_unread

    result = get_ed_unread(99)
    assert "not configured" in result.lower()


@patch.dict("os.environ", {"ED_API_TOKEN": ""})
def test_get_thread_not_configured():
    from mcp_servers.edstem.server import get_ed_thread

    result = get_ed_thread(12345)
    assert "not configured" in result.lower()


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
