"""Tests for the Gradescope MCP server tools."""

from unittest.mock import patch


@patch.dict("os.environ", {"GRADESCOPE_EMAIL": "", "GRADESCOPE_PASSWORD": ""})
def test_courses_not_configured():
    from mcp_servers.gradescope.server import list_gradescope_courses

    assert "not configured" in list_gradescope_courses().lower()


@patch.dict("os.environ", {"GRADESCOPE_EMAIL": "", "GRADESCOPE_PASSWORD": ""})
def test_assignments_not_configured():
    from mcp_servers.gradescope.server import list_gradescope_assignments

    assert "not configured" in list_gradescope_assignments("99").lower()


def test_gradescope_server_binds_loopback_and_8767_by_default():
    from mcp_servers.gradescope.server import mcp

    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 8767


def test_gradescope_server_allows_host_docker_internal():
    from mcp_servers.gradescope.server import mcp

    sec = mcp.settings.transport_security
    assert sec.enable_dns_rebinding_protection is True
    assert "host.docker.internal:*" in sec.allowed_hosts
