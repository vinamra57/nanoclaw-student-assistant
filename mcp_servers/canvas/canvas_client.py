"""Canvas LMS API client for the personal Canvas MCP server.

Talks directly to the institution's Canvas REST API at
`{CANVAS_BASE_URL}/api/v1`. Each student supplies their own CANVAS_API_TOKEN
(generated from their Canvas profile under Approved Integrations → New Access
Token); all calls are scoped to that user.

Mirrors the shape of `mcp_servers/edstem/ed_client.py` deliberately:
construct with config, expose `is_configured`, return [] on failure with a
single WARN log so the MCP tool can surface a clean message.
"""

import html
import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)


class CanvasClient:
    """Client for the Canvas LMS API.

    Each student's agent creates a CanvasClient with their personal API
    token + the institution's base URL. All operations are scoped to the
    authenticated user.
    """

    def __init__(self, api_token: str, base_url: str):
        self.api_token = api_token
        self.base_url = base_url.rstrip("/") if base_url else ""
        self._session: requests.Session | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_token and self.base_url)

    @property
    def api_root(self) -> str:
        return f"{self.base_url}/api/v1"

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(
                {"Authorization": f"Bearer {self.api_token}"}
            )
        return self._session

    @staticmethod
    def _strip_html(content: str) -> str:
        if not content:
            return ""
        text = re.sub(r"<[^>]+>", " ", content)
        text = html.unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _course_to_dict(c: dict) -> dict:
        return {
            "id": c.get("id"),
            "name": c.get("name") or c.get("course_code", ""),
            "code": c.get("course_code", ""),
            "term": (c.get("term") or {}).get("name", ""),
            "workflow_state": c.get("workflow_state", ""),
            "start_at": c.get("start_at"),
            "end_at": c.get("end_at"),
        }

    @staticmethod
    def _assignment_to_dict(a: dict, course_id: int | None = None) -> dict:
        return {
            "id": a.get("id"),
            "course_id": a.get("course_id") or course_id,
            "name": a.get("name", ""),
            "description": CanvasClient._strip_html(a.get("description", ""))[:1000],
            "due_at": a.get("due_at"),
            "points_possible": a.get("points_possible"),
            "html_url": a.get("html_url", ""),
            "submission_types": a.get("submission_types", []),
            "has_submitted": (a.get("has_submitted_submissions", False)),
        }

    @staticmethod
    def _announcement_to_dict(a: dict) -> dict:
        return {
            "id": a.get("id"),
            "course_id": a.get("context_code", "").replace("course_", "")
            if a.get("context_code", "").startswith("course_")
            else None,
            "title": a.get("title", ""),
            "message": CanvasClient._strip_html(a.get("message", ""))[:1000],
            "posted_at": a.get("posted_at"),
            "html_url": a.get("html_url", ""),
        }

    # -----------------------------------------------------------------
    # Methods
    # -----------------------------------------------------------------

    def list_courses(self, *, only_active: bool = True) -> list[dict]:
        if not self.is_configured:
            return []
        try:
            params: dict[str, Any] = {"per_page": 50, "include[]": "term"}
            if only_active:
                params["enrollment_state"] = "active"
            r = self._get_session().get(
                f"{self.api_root}/courses", params=params, timeout=15
            )
            r.raise_for_status()
            return [self._course_to_dict(c) for c in r.json()]
        except Exception as e:
            logger.warning(f"Canvas list_courses failed: {e}")
            return []

    def list_assignments(
        self, course_id: int, *, limit: int = 25
    ) -> list[dict]:
        if not self.is_configured:
            return []
        try:
            r = self._get_session().get(
                f"{self.api_root}/courses/{course_id}/assignments",
                params={"per_page": min(limit, 100), "order_by": "due_at"},
                timeout=15,
            )
            r.raise_for_status()
            return [self._assignment_to_dict(a, course_id) for a in r.json()]
        except Exception as e:
            logger.warning(f"Canvas list_assignments failed: {e}")
            return []

    def get_assignment(self, course_id: int, assignment_id: int) -> dict | None:
        if not self.is_configured:
            return None
        try:
            r = self._get_session().get(
                f"{self.api_root}/courses/{course_id}/assignments/{assignment_id}",
                timeout=15,
            )
            r.raise_for_status()
            return self._assignment_to_dict(r.json(), course_id)
        except Exception as e:
            logger.warning(
                f"Canvas get_assignment {course_id}/{assignment_id} failed: {e}"
            )
            return None

    def list_announcements(
        self, course_id: int | None = None, *, limit: int = 10
    ) -> list[dict]:
        if not self.is_configured:
            return []
        try:
            # `context_codes` is required; if no course filter given, we can't
            # query everything cheaply — return [] and let caller specify.
            if course_id is None:
                logger.warning(
                    "Canvas list_announcements called without course_id; returning []"
                )
                return []
            r = self._get_session().get(
                f"{self.api_root}/announcements",
                params={
                    "context_codes[]": f"course_{course_id}",
                    "per_page": min(limit, 50),
                },
                timeout=15,
            )
            r.raise_for_status()
            return [self._announcement_to_dict(a) for a in r.json()]
        except Exception as e:
            logger.warning(f"Canvas list_announcements failed: {e}")
            return []

    def list_grades(self, course_id: int) -> list[dict]:
        """Return per-assignment grades for the current user in a course."""
        if not self.is_configured:
            return []
        try:
            r = self._get_session().get(
                f"{self.api_root}/courses/{course_id}/students/submissions",
                params={
                    "student_ids[]": "self",
                    "include[]": "assignment",
                    "per_page": 100,
                },
                timeout=15,
            )
            r.raise_for_status()
            out: list[dict] = []
            for sub in r.json():
                a = sub.get("assignment") or {}
                out.append(
                    {
                        "assignment_id": a.get("id"),
                        "assignment_name": a.get("name"),
                        "score": sub.get("score"),
                        "grade": sub.get("grade"),
                        "points_possible": a.get("points_possible"),
                        "submitted_at": sub.get("submitted_at"),
                        "graded_at": sub.get("graded_at"),
                        "late": sub.get("late"),
                        "missing": sub.get("missing"),
                    }
                )
            return out
        except Exception as e:
            logger.warning(f"Canvas list_grades failed: {e}")
            return []

    def get_submission(self, course_id: int, assignment_id: int) -> dict | None:
        if not self.is_configured:
            return None
        try:
            r = self._get_session().get(
                f"{self.api_root}/courses/{course_id}/assignments/{assignment_id}/submissions/self",
                timeout=15,
            )
            r.raise_for_status()
            sub = r.json()
            return {
                "assignment_id": assignment_id,
                "course_id": course_id,
                "score": sub.get("score"),
                "grade": sub.get("grade"),
                "submitted_at": sub.get("submitted_at"),
                "graded_at": sub.get("graded_at"),
                "workflow_state": sub.get("workflow_state"),
                "late": sub.get("late"),
                "missing": sub.get("missing"),
                "preview_url": sub.get("preview_url"),
            }
        except Exception as e:
            logger.warning(
                f"Canvas get_submission {course_id}/{assignment_id} failed: {e}"
            )
            return None
