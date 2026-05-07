"""Unit tests for the Gradescope client wrapper."""

from unittest.mock import MagicMock, patch

from mcp_servers.gradescope.gs_client import GradescopeClient


def test_not_configured_without_email():
    c = GradescopeClient(email="", password="x")
    assert not c.is_configured
    assert c.list_courses() == []
    assert c.list_assignments("123") == []


def test_not_configured_without_password():
    c = GradescopeClient(email="x@y.com", password="")
    assert not c.is_configured


def test_login_failure_disables_client_for_process():
    """A login failure must NOT retry on every call (defends Gradescope from
    a misconfigured deployment hammering it)."""
    c = GradescopeClient(email="x@y.com", password="bad")
    with patch(
        "gradescopeapi.classes.connection.GSConnection.login",
        side_effect=Exception("auth failed"),
    ) as mock_login:
        assert c.list_courses() == []
        assert c.list_courses() == []
        assert c.list_assignments("99") == []
    # Login attempted exactly once across all three calls.
    assert mock_login.call_count == 1


def test_list_courses_parses_get_courses_info():
    c = GradescopeClient(email="x@y.com", password="ok")
    fake_session = MagicMock()
    fake_resp = MagicMock()
    fake_resp.text = "<html><body>fake</body></html>"
    fake_resp.raise_for_status = MagicMock()
    fake_session.get.return_value = fake_resp

    fake_conn = MagicMock()
    fake_conn.session = fake_session

    # Match what get_courses_info returns: {role: {course_id: Course}}
    from dataclasses import dataclass

    @dataclass
    class FakeCourse:
        name: str
        term: str

    info = {"student": {"99": FakeCourse(name="CSE 452", term="Spring 2026")}}

    with patch(
        "gradescopeapi.classes.connection.GSConnection",
        return_value=fake_conn,
    ), patch(
        "mcp_servers.gradescope.gs_client.GSConnection",
        return_value=fake_conn,
        create=True,
    ), patch(
        "gradescopeapi.classes.account.get_courses_info", return_value=info
    ):
        rows = c.list_courses()
    assert len(rows) == 1
    assert rows[0]["id"] == "99"
    assert rows[0]["role"] == "student"
    assert rows[0]["name"] == "CSE 452"


def test_list_assignments_calls_correct_url():
    c = GradescopeClient(email="x@y.com", password="ok")
    fake_session = MagicMock()
    fake_resp = MagicMock()
    fake_resp.text = "<html></html>"
    fake_resp.raise_for_status = MagicMock()
    fake_session.get.return_value = fake_resp

    fake_conn = MagicMock()
    fake_conn.session = fake_session

    from dataclasses import dataclass

    @dataclass
    class A:
        name: str

    with patch(
        "gradescopeapi.classes.connection.GSConnection",
        return_value=fake_conn,
    ), patch(
        "gradescopeapi.classes.account.get_assignments_student_view",
        return_value=[A(name="PA1"), A(name="PA2")],
    ):
        rows = c.list_assignments("99")
    assert fake_session.get.called
    url_arg = fake_session.get.call_args.args[0]
    assert "/courses/99" in url_arg
    assert len(rows) == 2
    assert rows[0]["course_id"] == "99"
    assert rows[0]["name"] == "PA1"


def test_failure_returns_empty():
    c = GradescopeClient(email="x@y.com", password="ok")
    fake_session = MagicMock()
    fake_session.get.side_effect = Exception("network down")
    fake_conn = MagicMock()
    fake_conn.session = fake_session
    with patch(
        "gradescopeapi.classes.connection.GSConnection",
        return_value=fake_conn,
    ):
        # First call: triggers login (succeeds → True), then list fails.
        assert c.list_courses() == []
        assert c.list_assignments("99") == []
