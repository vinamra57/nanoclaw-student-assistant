"""Tests for the EdStem client (multi-course)."""

from unittest.mock import MagicMock, patch

from mcp_servers.edstem.ed_client import EdClient


def test_client_not_configured_without_token():
    client = EdClient(api_token="")
    assert not client.is_configured


def test_client_configured_with_token():
    client = EdClient(api_token="test-token")
    assert client.is_configured


def test_clean_content_strips_html():
    raw = "<p>Hello <strong>world</strong></p>"
    assert EdClient._clean_content(raw) == "Hello world"


def test_clean_content_unescapes_entities():
    raw = "Tom &amp; Jerry"
    assert EdClient._clean_content(raw) == "Tom & Jerry"


def test_thread_to_dict_builds_url():
    thread = {
        "id": 1,
        "number": 42,
        "course_id": 100,
        "title": "Test Thread",
        "type": "question",
        "category": "General",
        "content": "<p>Body</p>",
        "is_pinned": False,
        "created_at": "2026-01-01T00:00:00Z",
    }
    result = EdClient._thread_to_dict(thread)
    assert result["url"] == "https://edstem.org/us/courses/100/discussion/42"
    assert result["title"] == "Test Thread"
    assert result["content"] == "Body"


def test_per_course_methods_return_empty_when_not_configured():
    client = EdClient(api_token="")
    assert client.search_threads(99, "test") == []
    assert client.get_announcements(99) == []
    assert client.get_unread_threads(99) == []
    assert client.get_pinned_threads(99) == []
    assert client.get_thread_content(123) is None
    assert client.list_courses() == []


@patch("mcp_servers.edstem.ed_client.requests.Session")
def test_search_threads_calls_api_with_course_id(mock_session_cls):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {
        "threads": [
            {
                "id": 1,
                "number": 10,
                "course_id": 100,
                "title": "Paxos question",
                "type": "question",
                "category": "",
                "content": "How does Paxos work?",
                "is_pinned": False,
                "created_at": "2026-01-01",
            }
        ]
    }
    mock_session.get.return_value = mock_response
    mock_session_cls.return_value = mock_session

    client = EdClient(api_token="test-token")
    results = client.search_threads(100, "Paxos")

    assert len(results) == 1
    assert results[0]["title"] == "Paxos question"
    # Verify URL was built with the course_id we passed.
    url_arg = mock_session.get.call_args.args[0]
    assert "/courses/100/threads" in url_arg


@patch("mcp_servers.edstem.ed_client.requests.Session")
def test_list_courses_filters_to_active(mock_session_cls):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "user": {"id": 1, "name": "Vinamra"},
        "courses": [
            {
                "course": {
                    "id": 97587,
                    "code": "CSE 452",
                    "name": "Distributed Systems",
                    "year": "2026",
                    "session": "Spring",
                    "status": "active",
                },
                "role": {"role": "student"},
            },
            {
                "course": {
                    "id": 56858,
                    "code": "CSE 414",
                    "name": "Databases",
                    "year": "2024",
                    "session": "Spring",
                    "status": "archived",
                },
                "role": {"role": "student"},
            },
        ],
    }
    mock_session.get.return_value = mock_response
    mock_session_cls.return_value = mock_session

    client = EdClient(api_token="test-token")
    courses = client.list_courses()
    assert len(courses) == 1
    assert courses[0]["id"] == 97587
    assert courses[0]["code"] == "CSE 452"
    assert courses[0]["role"] == "student"


@patch("mcp_servers.edstem.ed_client.requests.Session")
def test_list_courses_includes_archived_when_requested(mock_session_cls):
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "courses": [
            {
                "course": {"id": 1, "code": "X", "name": "X", "status": "archived"},
                "role": {"role": "student"},
            },
        ],
    }
    mock_session.get.return_value = mock_response
    mock_session_cls.return_value = mock_session

    client = EdClient(api_token="test-token")
    assert client.list_courses(only_active=False)[0]["id"] == 1


def test_get_thread_content_does_not_need_course_id():
    """Thread IDs are globally unique — get_thread_content takes only thread_id."""
    client = EdClient(api_token="")
    # Just exercise the signature; not_configured returns None.
    assert client.get_thread_content(12345) is None
