"""Gradescope client for the personal MCP server.

Gradescope has no public API; we sign in with the student's email +
password and use a requests Session to fetch + parse HTML pages. The
heavy lifting (BeautifulSoup parsers for the dashboard / course pages)
comes from the `gradescopeapi` package; we wrap login + a small set of
read-only fetches.

Credentials are passed via env (GRADESCOPE_EMAIL + GRADESCOPE_PASSWORD).
The MCP server must NEVER log either value, and the helper here makes
no attempt to print them — the only place plaintext touches the wire is
the login POST.
"""

import logging
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)

GS_BASE = "https://www.gradescope.com"


class GradescopeClient:
    """Thin wrapper over `gradescopeapi`'s parsers.

    Lazy login: connection is established the first time a method needs
    it. Subsequent calls reuse the session. If login fails, every method
    returns the empty / not-configured value.
    """

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        # Typed as Any so we don't need to import GSConnection at module
        # load time (the gradescopeapi package is an optional dep).
        self._conn: Any = None
        self._login_ok: bool | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.email and self.password)

    def _ensure_login(self) -> bool:
        if self._login_ok is True:
            return True
        if self._login_ok is False:
            return False  # don't retry within the same process
        if not self.is_configured:
            self._login_ok = False
            return False
        try:
            from gradescopeapi.classes.connection import GSConnection

            conn = GSConnection()
            conn.login(self.email, self.password)
            self._conn = conn
            self._login_ok = True
            return True
        except Exception as e:
            logger.warning(f"Gradescope login failed: {e}")
            self._login_ok = False
            return False

    def list_courses(self) -> list[dict[str, Any]]:
        if not self._ensure_login():
            return []
        # _ensure_login() returning True guarantees self._conn is set; assert
        # for mypy's narrowing.
        assert self._conn is not None
        try:
            from bs4 import BeautifulSoup
            from gradescopeapi.classes.account import get_courses_info

            r = self._conn.session.get(f"{GS_BASE}/account", timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            info = get_courses_info(soup)
            # info is dict[str, dict[str, Course]] keyed by role
            # ('student' / 'instructor'). Flatten to a single list scoped
            # to the student view; expose a `role` field for clarity.
            out: list[dict[str, Any]] = []
            for role, courses in (info or {}).items():
                for cid, course in (courses or {}).items():
                    # `course` is gradescopeapi's Course dataclass; turn
                    # it into a plain dict via asdict (or fall back to
                    # vars() for any non-dataclass shapes the lib might
                    # return in future versions).
                    if hasattr(course, "__dataclass_fields__"):
                        d: dict[str, Any] = asdict(course)
                    else:
                        d = dict(vars(course))
                    d["id"] = cid
                    d["role"] = role
                    out.append(d)
            return out
        except Exception as e:
            logger.warning(f"Gradescope list_courses failed: {e}")
            return []

    def list_assignments(self, course_id: str) -> list[dict[str, Any]]:
        if not self._ensure_login():
            return []
        assert self._conn is not None
        try:
            from bs4 import BeautifulSoup
            from gradescopeapi.classes.account import get_assignments_student_view

            r = self._conn.session.get(f"{GS_BASE}/courses/{course_id}", timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            assignments = get_assignments_student_view(soup) or []
            out = []
            for a in assignments:
                d = asdict(a) if hasattr(a, "__dataclass_fields__") else dict(a)
                # Stamp the course_id so downstream tooling doesn't need
                # to re-thread it through.
                d["course_id"] = course_id
                out.append(d)
            return out
        except Exception as e:
            logger.warning(f"Gradescope list_assignments({course_id}) failed: {e}")
            return []
