"""
Ed Discussion API client for the personal EdStem MCP server.

Carries only the student's API token; course id is passed per-call so the
agent can list courses and then drill into whichever one the student is
asking about. (Most students are enrolled in 5-15 courses each term — a
single hardcoded course id was the wrong default for a multi-course chat.)
"""

import html
import logging
import re

import requests

logger = logging.getLogger(__name__)

ED_API_BASE = "https://us.edstem.org/api"


def _thread_query_params(
    *,
    limit: int,
    sort: str = "new",
    search: str | None = None,
    filter_: str | None = None,
) -> dict[str, str]:
    """Build a query-param dict with str values only.

    `requests.Session.get(params=...)` accepts a mixed-typed mapping at
    runtime (it stringifies everything), but its declared type rejects
    `dict[str, int | str]` because the Union collapses to `dict[str,
    object]`. Casting all values to str up front keeps mypy happy without
    changing the wire-level behaviour — Ed expects strings for these
    params anyway.
    """
    params: dict[str, str] = {"limit": str(limit), "sort": sort}
    if search is not None:
        params["search"] = search
    if filter_ is not None:
        params["filter"] = filter_
    return params


class EdClient:
    """Client for the Ed Discussion API.

    Constructed with just the student's API token. Every per-course
    method takes a `course_id: int` argument; agents discover available
    courses via `list_courses()` first.
    """

    def __init__(self, api_token: str):
        self.api_token = api_token
        self._session: requests.Session | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_token)

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"Authorization": f"Bearer {self.api_token}"})
        return self._session

    @staticmethod
    def _clean_content(content: str) -> str:
        """Strip HTML tags from Ed thread content to get plain text."""
        text = re.sub(r"<[^>]+>", " ", content)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _thread_to_dict(thread: dict) -> dict:
        """Convert an Ed thread to a simplified dict."""
        course_id = thread.get("course_id")
        number = thread.get("number")
        url = (
            f"https://edstem.org/us/courses/{course_id}/discussion/{number}"
            if course_id and number
            else ""
        )
        return {
            "id": thread.get("id"),
            "number": number,
            "title": thread.get("title", ""),
            "type": thread.get("type", ""),
            "category": thread.get("category", ""),
            "content": EdClient._clean_content(thread.get("content", "")),
            "is_pinned": thread.get("is_pinned", False),
            "created_at": thread.get("created_at", ""),
            "url": url,
        }

    @staticmethod
    def _course_to_dict(c: dict, role: str | None = None) -> dict:
        return {
            "id": c.get("id"),
            "code": c.get("code", ""),
            "name": c.get("name", ""),
            "year": c.get("year"),
            "session": c.get("session", ""),
            "status": c.get("status", ""),
            "role": role or "",
        }

    def list_courses(self, *, only_active: bool = True) -> list[dict]:
        """Return courses the token owner is enrolled in.

        `/api/user` returns `{user, courses: [{course, role: {...}}]}`. We
        flatten to a list of dicts with id/code/name/role suitable for the
        agent to pick from. By default filters to active enrollments;
        archived courses (last quarter, etc.) are dropped.
        """
        if not self.is_configured:
            return []
        try:
            session = self._get_session()
            resp = session.get(f"{ED_API_BASE}/user", timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            out: list[dict] = []
            for c in payload.get("courses", []):
                course = c.get("course", {})
                role_raw = c.get("role")
                role = (
                    role_raw.get("role")
                    if isinstance(role_raw, dict)
                    else (role_raw or "")
                )
                if only_active and course.get("status") != "active":
                    continue
                out.append(self._course_to_dict(course, role))
            return out
        except Exception as e:
            logger.warning(f"Failed to fetch Ed user/courses: {e}")
            return []

    def get_announcements(self, course_id: int, limit: int = 50) -> list[dict]:
        """Fetch recent announcements for one course."""
        if not self.is_configured:
            return []
        try:
            session = self._get_session()
            resp = session.get(
                f"{ED_API_BASE}/courses/{course_id}/threads",
                params=_thread_query_params(limit=min(limit, 100)),
                timeout=15,
            )
            resp.raise_for_status()
            threads = resp.json().get("threads", [])
            return [
                self._thread_to_dict(t)
                for t in threads
                if t.get("type") == "announcement"
            ]
        except Exception as e:
            logger.warning(f"Failed to fetch Ed announcements: {e}")
            return []

    def get_pinned_threads(self, course_id: int) -> list[dict]:
        """Fetch all pinned threads for one course."""
        if not self.is_configured:
            return []
        try:
            session = self._get_session()
            resp = session.get(
                f"{ED_API_BASE}/courses/{course_id}/threads",
                params=_thread_query_params(limit=100),
                timeout=15,
            )
            resp.raise_for_status()
            threads = resp.json().get("threads", [])
            return [
                self._thread_to_dict(t) for t in threads if t.get("is_pinned", False)
            ]
        except Exception as e:
            logger.warning(f"Failed to fetch Ed pinned threads: {e}")
            return []

    def search_threads(self, course_id: int, query: str, limit: int = 20) -> list[dict]:
        """Search Ed threads in one course by keyword."""
        if not self.is_configured:
            return []
        try:
            session = self._get_session()
            resp = session.get(
                f"{ED_API_BASE}/courses/{course_id}/threads",
                params=_thread_query_params(limit=min(limit, 100), search=query),
                timeout=15,
            )
            if resp.ok:
                threads = resp.json().get("threads", [])
                return [self._thread_to_dict(t) for t in threads]
            return []
        except Exception as e:
            logger.warning(f"Failed to search Ed for '{query}': {e}")
            return []

    def get_thread_content(self, thread_id: int) -> dict | None:
        """Fetch full thread content including answers and comments.

        Course-id-free: thread ids are unique across the whole Ed
        instance so we don't need to know which course the thread lives in.
        """
        if not self.is_configured:
            return None
        try:
            session = self._get_session()
            resp = session.get(
                f"{ED_API_BASE}/threads/{thread_id}",
                timeout=15,
            )
            resp.raise_for_status()
            thread = resp.json().get("thread", resp.json())
            result = self._thread_to_dict(thread)
            result["answers"] = [
                self._clean_content(a.get("content", ""))
                for a in thread.get("answers", [])
            ]
            result["comments"] = [
                self._clean_content(c.get("content", ""))
                for c in thread.get("comments", [])
            ]
            return result
        except Exception as e:
            logger.warning(f"Failed to fetch Ed thread {thread_id}: {e}")
            return None

    def get_unread_threads(self, course_id: int, limit: int = 20) -> list[dict]:
        """Fetch unread threads in one course."""
        if not self.is_configured:
            return []
        try:
            session = self._get_session()
            resp = session.get(
                f"{ED_API_BASE}/courses/{course_id}/threads",
                params=_thread_query_params(limit=min(limit, 100), filter_="unread"),
                timeout=15,
            )
            if resp.ok:
                threads = resp.json().get("threads", [])
                return [self._thread_to_dict(t) for t in threads]
            return []
        except Exception as e:
            logger.warning(f"Failed to fetch unread Ed threads: {e}")
            return []
