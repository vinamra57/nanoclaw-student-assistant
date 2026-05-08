"""Tests for the Canvas MCP server tools.

Tools fetch credentials from ChatCSE on demand via the shared
`get_provider_credential` helper. `not configured` paths happen when
the helper returns None.
"""

from unittest.mock import patch


def _mock_helper(returns):
    return patch(
        "mcp_servers._shared.credentials.get_provider_credential",
        return_value=returns,
    )


def test_courses_not_configured():
    from mcp_servers.canvas.server import list_canvas_courses

    with _mock_helper(None):
        assert "isn't connected" in list_canvas_courses().lower()


def test_assignments_not_configured():
    from mcp_servers.canvas.server import list_canvas_assignments

    with _mock_helper(None):
        assert "isn't connected" in list_canvas_assignments(99).lower()


def test_announcements_not_configured():
    from mcp_servers.canvas.server import list_canvas_announcements

    with _mock_helper(None):
        assert "isn't connected" in list_canvas_announcements(99).lower()


def test_grades_not_configured():
    from mcp_servers.canvas.server import list_canvas_grades

    with _mock_helper(None):
        assert "isn't connected" in list_canvas_grades(99).lower()


def test_get_submission_not_configured():
    from mcp_servers.canvas.server import get_canvas_submission

    with _mock_helper(None):
        assert "isn't connected" in get_canvas_submission(99, 5).lower()


def test_get_assignment_not_configured():
    from mcp_servers.canvas.server import get_canvas_assignment

    with _mock_helper(None):
        assert "isn't connected" in get_canvas_assignment(99, 5).lower()


def test_canvas_server_binds_loopback_and_8766_by_default():
    from mcp_servers.canvas.server import mcp

    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 8766


def test_canvas_server_allows_host_docker_internal():
    from mcp_servers.canvas.server import mcp

    sec = mcp.settings.transport_security
    assert sec.enable_dns_rebinding_protection is True
    assert "host.docker.internal:*" in sec.allowed_hosts


def test_helper_returns_token_and_base_url_propagate():
    """Helper returns (value, metadata={'base_url': ...}); both must reach the client."""
    from mcp_servers.canvas import server as srv

    with _mock_helper(("test-canvas-token", {"base_url": "https://canvas.uw.edu"})):
        client = srv._client()
    assert client.api_token == "test-canvas-token"
    assert client.base_url == "https://canvas.uw.edu"
    assert client.is_configured


def test_helper_with_missing_base_url_yields_unconfigured_client():
    """Token without base_url metadata can't actually call Canvas — surface as unconfigured."""
    from mcp_servers.canvas import server as srv

    with _mock_helper(("test-canvas-token", {})):
        client = srv._client()
    assert not client.is_configured  # base_url empty → not configured
