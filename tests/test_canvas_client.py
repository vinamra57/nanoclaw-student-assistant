"""Unit tests for the Canvas API client."""

from unittest.mock import MagicMock, patch

from mcp_servers.canvas.canvas_client import CanvasClient


def test_client_not_configured_without_token():
    c = CanvasClient(api_token="", base_url="https://canvas.uw.edu")
    assert not c.is_configured
    assert c.list_courses() == []
    assert c.list_assignments(123) == []
    assert c.get_assignment(123, 456) is None
    assert c.list_announcements(123) == []
    assert c.list_grades(123) == []
    assert c.get_submission(123, 456) is None


def test_client_not_configured_without_base_url():
    c = CanvasClient(api_token="t", base_url="")
    assert not c.is_configured


def test_client_configured_with_both():
    c = CanvasClient(api_token="t", base_url="https://canvas.uw.edu")
    assert c.is_configured
    assert c.api_root == "https://canvas.uw.edu/api/v1"


def test_base_url_trailing_slash_stripped():
    c = CanvasClient(api_token="t", base_url="https://canvas.uw.edu/")
    assert c.api_root == "https://canvas.uw.edu/api/v1"


def test_strip_html_removes_tags_and_unescapes():
    s = "<p>Hello&nbsp;<strong>world</strong></p>"
    assert CanvasClient._strip_html(s) == "Hello world"


def test_list_courses_returns_dicts_on_success():
    c = CanvasClient(api_token="t", base_url="https://canvas.uw.edu")
    fake = MagicMock()
    fake.json.return_value = [
        {
            "id": 99,
            "name": "Distributed Systems",
            "course_code": "CSE 452",
            "term": {"name": "Spring 2026"},
            "workflow_state": "available",
            "start_at": "2026-03-30",
            "end_at": "2026-06-12",
        }
    ]
    fake.raise_for_status = MagicMock()
    with patch.object(c, "_get_session") as mock_sess:
        mock_sess.return_value.get.return_value = fake
        rows = c.list_courses()
    assert len(rows) == 1
    assert rows[0]["id"] == 99
    assert rows[0]["name"] == "Distributed Systems"
    assert rows[0]["term"] == "Spring 2026"


def test_list_assignments_calls_correct_endpoint():
    c = CanvasClient(api_token="t", base_url="https://canvas.uw.edu")
    fake = MagicMock()
    fake.json.return_value = [
        {
            "id": 5,
            "name": "PA1",
            "due_at": "2026-04-15T23:59:00Z",
            "points_possible": 100,
            "html_url": "https://canvas.uw.edu/courses/99/assignments/5",
            "submission_types": ["online_upload"],
            "description": "<p>Implement Paxos</p>",
        }
    ]
    fake.raise_for_status = MagicMock()
    with patch.object(c, "_get_session") as mock_sess:
        mock_sess.return_value.get.return_value = fake
        rows = c.list_assignments(99, limit=10)
    assert mock_sess.return_value.get.called
    url = mock_sess.return_value.get.call_args.args[0]
    assert "/courses/99/assignments" in url
    assert rows[0]["course_id"] == 99
    assert rows[0]["description"] == "Implement Paxos"


def test_list_announcements_without_course_id_returns_empty():
    """Canvas requires context_codes — we refuse the broad query."""
    c = CanvasClient(api_token="t", base_url="https://canvas.uw.edu")
    assert c.list_announcements(course_id=None) == []


def test_list_grades_extracts_assignment_metadata():
    c = CanvasClient(api_token="t", base_url="https://canvas.uw.edu")
    fake = MagicMock()
    fake.json.return_value = [
        {
            "score": 85,
            "grade": "B",
            "submitted_at": "2026-04-15T23:00:00Z",
            "graded_at": "2026-04-17T10:00:00Z",
            "late": False,
            "missing": False,
            "assignment": {"id": 5, "name": "PA1", "points_possible": 100},
        }
    ]
    fake.raise_for_status = MagicMock()
    with patch.object(c, "_get_session") as mock_sess:
        mock_sess.return_value.get.return_value = fake
        rows = c.list_grades(99)
    assert rows[0]["assignment_id"] == 5
    assert rows[0]["score"] == 85
    assert rows[0]["points_possible"] == 100


def test_failure_returns_empty_list_not_exception():
    c = CanvasClient(api_token="t", base_url="https://canvas.uw.edu")
    with patch.object(c, "_get_session") as mock_sess:
        mock_sess.return_value.get.side_effect = Exception("boom")
        # All read methods should swallow and return []
        assert c.list_courses() == []
        assert c.list_assignments(99) == []
        assert c.list_announcements(99) == []
        assert c.list_grades(99) == []


def test_failure_returns_none_for_singleton_methods():
    c = CanvasClient(api_token="t", base_url="https://canvas.uw.edu")
    with patch.object(c, "_get_session") as mock_sess:
        mock_sess.return_value.get.side_effect = Exception("boom")
        assert c.get_assignment(99, 5) is None
        assert c.get_submission(99, 5) is None


def test_session_uses_bearer_auth():
    c = CanvasClient(api_token="my-token", base_url="https://canvas.uw.edu")
    sess = c._get_session()
    assert sess.headers["Authorization"] == "Bearer my-token"
    # Same session reused.
    assert c._get_session() is sess
