"""Tests for the Canvas MCP server tools."""

from unittest.mock import patch


@patch.dict("os.environ", {"CANVAS_API_TOKEN": "", "CANVAS_BASE_URL": ""})
def test_courses_not_configured():
    from mcp_servers.canvas.server import list_canvas_courses

    out = list_canvas_courses()
    assert "not configured" in out.lower()


@patch.dict("os.environ", {"CANVAS_API_TOKEN": "", "CANVAS_BASE_URL": ""})
def test_assignments_not_configured():
    from mcp_servers.canvas.server import list_canvas_assignments

    assert "not configured" in list_canvas_assignments(99).lower()


@patch.dict("os.environ", {"CANVAS_API_TOKEN": "", "CANVAS_BASE_URL": ""})
def test_announcements_not_configured():
    from mcp_servers.canvas.server import list_canvas_announcements

    assert "not configured" in list_canvas_announcements(99).lower()


@patch.dict("os.environ", {"CANVAS_API_TOKEN": "", "CANVAS_BASE_URL": ""})
def test_grades_not_configured():
    from mcp_servers.canvas.server import list_canvas_grades

    assert "not configured" in list_canvas_grades(99).lower()


@patch.dict("os.environ", {"CANVAS_API_TOKEN": "", "CANVAS_BASE_URL": ""})
def test_get_submission_not_configured():
    from mcp_servers.canvas.server import get_canvas_submission

    assert "not configured" in get_canvas_submission(99, 5).lower()


@patch.dict("os.environ", {"CANVAS_API_TOKEN": "", "CANVAS_BASE_URL": ""})
def test_get_assignment_not_configured():
    from mcp_servers.canvas.server import get_canvas_assignment

    assert "not configured" in get_canvas_assignment(99, 5).lower()


def test_canvas_server_binds_loopback_and_8766_by_default():
    from mcp_servers.canvas.server import mcp

    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 8766


def test_canvas_server_allows_host_docker_internal():
    from mcp_servers.canvas.server import mcp

    sec = mcp.settings.transport_security
    assert sec.enable_dns_rebinding_protection is True
    assert "host.docker.internal:*" in sec.allowed_hosts
