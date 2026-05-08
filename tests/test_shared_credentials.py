"""Tests for the shared credential fetcher used by all per-provider MCP servers."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def clear_cache():
    """Each test starts with an empty credential cache."""
    from mcp_servers._shared.credentials import invalidate

    invalidate()
    yield
    invalidate()


def test_returns_none_when_token_missing(monkeypatch):
    monkeypatch.delenv("CHATCSE_AGENT_TOKEN", raising=False)
    from mcp_servers._shared.credentials import get_provider_credential

    assert get_provider_credential("edstem") is None


def test_returns_none_on_404(monkeypatch):
    monkeypatch.setenv("CHATCSE_AGENT_TOKEN", "fake-token")
    monkeypatch.setenv("CHATCSE_BASE_URL", "http://localhost:8000")
    fake_resp = MagicMock(status_code=404, text="not found")
    with patch("mcp_servers._shared.credentials.requests.get", return_value=fake_resp):
        from mcp_servers._shared.credentials import get_provider_credential

        assert get_provider_credential("edstem") is None


def test_returns_value_and_metadata_on_200(monkeypatch):
    monkeypatch.setenv("CHATCSE_AGENT_TOKEN", "fake-token")
    monkeypatch.setenv("CHATCSE_BASE_URL", "http://localhost:8000")
    fake_resp = MagicMock(
        status_code=200,
        json=MagicMock(
            return_value={"value": "ed-secret", "metadata": {"course_id": 97587}}
        ),
    )
    with patch("mcp_servers._shared.credentials.requests.get", return_value=fake_resp):
        from mcp_servers._shared.credentials import get_provider_credential

        result = get_provider_credential("edstem")
    assert result == ("ed-secret", {"course_id": 97587})


def test_metadata_defaults_to_empty_dict(monkeypatch):
    monkeypatch.setenv("CHATCSE_AGENT_TOKEN", "fake-token")
    fake_resp = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"value": "v", "metadata": None}),
    )
    with patch("mcp_servers._shared.credentials.requests.get", return_value=fake_resp):
        from mcp_servers._shared.credentials import get_provider_credential

        result = get_provider_credential("edstem")
    assert result == ("v", {})


def test_caches_for_ttl(monkeypatch):
    """Two consecutive calls for the same provider hit the network only once."""
    monkeypatch.setenv("CHATCSE_AGENT_TOKEN", "fake-token")
    fake_resp = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"value": "v", "metadata": {}}),
    )
    with patch(
        "mcp_servers._shared.credentials.requests.get", return_value=fake_resp
    ) as mock_get:
        from mcp_servers._shared.credentials import get_provider_credential

        get_provider_credential("edstem")
        get_provider_credential("edstem")
    assert mock_get.call_count == 1


def test_invalidate_clears_cache(monkeypatch):
    """After invalidate, next call hits the network again."""
    monkeypatch.setenv("CHATCSE_AGENT_TOKEN", "fake-token")
    fake_resp = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"value": "v", "metadata": {}}),
    )
    with patch(
        "mcp_servers._shared.credentials.requests.get", return_value=fake_resp
    ) as mock_get:
        from mcp_servers._shared.credentials import get_provider_credential, invalidate

        get_provider_credential("edstem")
        invalidate("edstem")
        get_provider_credential("edstem")
    assert mock_get.call_count == 2


def test_network_error_returns_none(monkeypatch):
    monkeypatch.setenv("CHATCSE_AGENT_TOKEN", "fake-token")
    with patch(
        "mcp_servers._shared.credentials.requests.get",
        side_effect=Exception("connection refused"),
    ):
        from mcp_servers._shared.credentials import get_provider_credential

        assert get_provider_credential("edstem") is None


def test_uses_chatcse_base_url(monkeypatch):
    monkeypatch.setenv("CHATCSE_AGENT_TOKEN", "fake-token")
    monkeypatch.setenv("CHATCSE_BASE_URL", "https://chatcse.example.com")
    captured_url = ""

    def fake_get(url, headers=None, timeout=None):
        nonlocal captured_url
        captured_url = url
        return MagicMock(status_code=200, json=MagicMock(return_value={"value": "v"}))

    with patch("mcp_servers._shared.credentials.requests.get", side_effect=fake_get):
        from mcp_servers._shared.credentials import get_provider_credential

        get_provider_credential("edstem")
    assert captured_url == "https://chatcse.example.com/api/agent/credentials/edstem"


def test_falls_back_from_virtual_ta_url_port(monkeypatch):
    """When CHATCSE_BASE_URL is unset but VIRTUAL_TA_URL is :8001, derive :8000."""
    monkeypatch.setenv("CHATCSE_AGENT_TOKEN", "fake-token")
    monkeypatch.delenv("CHATCSE_BASE_URL", raising=False)
    monkeypatch.setenv("VIRTUAL_TA_URL", "http://host.docker.internal:8001")
    captured_url = ""

    def fake_get(url, headers=None, timeout=None):
        nonlocal captured_url
        captured_url = url
        return MagicMock(status_code=200, json=MagicMock(return_value={"value": "v"}))

    with patch("mcp_servers._shared.credentials.requests.get", side_effect=fake_get):
        from mcp_servers._shared.credentials import get_provider_credential

        get_provider_credential("edstem")
    assert "host.docker.internal:8000" in captured_url
