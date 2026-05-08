"""Tests for the Gradescope MCP server tools.

Credential is stored as `email:password` in the value field; the server
splits on `:` after fetching from ChatCSE.
"""

from unittest.mock import patch


def _mock_helper(returns):
    return patch(
        "mcp_servers._shared.credentials.get_provider_credential",
        return_value=returns,
    )


def test_courses_not_configured():
    from mcp_servers.gradescope.server import list_gradescope_courses

    with _mock_helper(None):
        assert "isn't connected" in list_gradescope_courses().lower()


def test_assignments_not_configured():
    from mcp_servers.gradescope.server import list_gradescope_assignments

    with _mock_helper(None):
        assert "isn't connected" in list_gradescope_assignments("99").lower()


def test_gradescope_server_binds_loopback_and_8767_by_default():
    from mcp_servers.gradescope.server import mcp

    assert mcp.settings.host == "127.0.0.1"
    assert mcp.settings.port == 8767


def test_gradescope_server_allows_host_docker_internal():
    from mcp_servers.gradescope.server import mcp

    sec = mcp.settings.transport_security
    assert sec.enable_dns_rebinding_protection is True
    assert "host.docker.internal:*" in sec.allowed_hosts


def test_helper_returns_email_password_split():
    """The email:password format is parsed into client.email and client.password."""
    from mcp_servers.gradescope import server as srv

    # Reset the module-level cached client
    srv._client = None
    with _mock_helper(("vinamra1@uw.edu:my-local-pw", {})):
        client = srv._get_client()
    assert client.email == "vinamra1@uw.edu"
    assert client.password == "my-local-pw"


def test_malformed_credential_treated_as_unconfigured():
    """If somehow the value isn't email:password form, return unconfigured."""
    from mcp_servers.gradescope import server as srv

    srv._client = None
    with _mock_helper(("just-a-token-no-colon", {})):
        client = srv._get_client()
    assert not client.is_configured
