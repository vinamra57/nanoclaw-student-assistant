"""Tests for the EdStem MCP server tools."""

from unittest.mock import patch

from mcp_servers.edstem.server import (
    get_ed_announcements,
    get_ed_pinned,
    get_ed_unread,
    search_ed,
)


@patch.dict("os.environ", {"ED_API_TOKEN": "", "ED_COURSE_ID": "0"})
def test_search_ed_not_configured():
    result = search_ed("test")
    assert "not configured" in result


@patch.dict("os.environ", {"ED_API_TOKEN": "", "ED_COURSE_ID": "0"})
def test_announcements_not_configured():
    result = get_ed_announcements()
    assert "not configured" in result


@patch.dict("os.environ", {"ED_API_TOKEN": "", "ED_COURSE_ID": "0"})
def test_pinned_not_configured():
    result = get_ed_pinned()
    assert "not configured" in result


@patch.dict("os.environ", {"ED_API_TOKEN": "", "ED_COURSE_ID": "0"})
def test_unread_not_configured():
    result = get_ed_unread()
    assert "not configured" in result


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
