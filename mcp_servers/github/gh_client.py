"""Thin GitHub REST v3 client.

Wraps `requests` with the student's personal access token from
`provider_credentials`. Each method returns plain dicts/lists — the MCP
layer renders them as JSON to the agent.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_API = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"
_API_VERSION = "2022-11-28"


class GhClient:
    """GitHub REST client scoped to one user's PAT.

    `is_configured` is False when no token is set — tools should surface a
    clean "connect GitHub via /github-key" message in that case rather
    than make unauthenticated calls.
    """

    def __init__(self, token: str = "") -> None:
        self._token = token

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": "studentclaw-github-mcp/1.0",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        r = requests.get(
            f"{_API}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=20,
        )
        if r.status_code == 404:
            return None
        if not r.ok:
            return {"_error": f"HTTP {r.status_code}", "_body": r.text[:200]}
        return r.json()

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        r = requests.post(
            f"{_API}{path}",
            headers=self._headers(),
            json=body,
            timeout=20,
        )
        if not r.ok:
            return {"_error": f"HTTP {r.status_code}", "_body": r.text[:200]}
        return r.json()

    # ── repos ────────────────────────────────────────────────────────
    def list_user_repos(self, limit: int = 30) -> list[dict]:
        out = self._get("/user/repos", {"per_page": min(limit, 100), "sort": "updated"})
        if not isinstance(out, list):
            return []
        return [
            {
                "full_name": r["full_name"],
                "private": r.get("private"),
                "description": r.get("description"),
                "default_branch": r.get("default_branch"),
                "language": r.get("language"),
                "updated_at": r.get("updated_at"),
                "url": r.get("html_url"),
            }
            for r in out[:limit]
        ]

    def get_repo(self, owner: str, repo: str) -> dict | None:
        r = self._get(f"/repos/{owner}/{repo}")
        if not isinstance(r, dict):
            return None
        return {
            "full_name": r.get("full_name"),
            "description": r.get("description"),
            "default_branch": r.get("default_branch"),
            "open_issues_count": r.get("open_issues_count"),
            "stargazers_count": r.get("stargazers_count"),
            "license": (r.get("license") or {}).get("spdx_id"),
            "language": r.get("language"),
            "url": r.get("html_url"),
        }

    # ── issues ───────────────────────────────────────────────────────
    def list_issues(
        self, owner: str, repo: str, state: str = "open", limit: int = 20
    ) -> list[dict]:
        out = self._get(
            f"/repos/{owner}/{repo}/issues",
            {"state": state, "per_page": min(limit, 100)},
        )
        if not isinstance(out, list):
            return []
        return [
            {
                "number": i["number"],
                "title": i.get("title"),
                "state": i.get("state"),
                "labels": [lbl.get("name") for lbl in (i.get("labels") or [])],
                "user": (i.get("user") or {}).get("login"),
                "comments": i.get("comments"),
                "updated_at": i.get("updated_at"),
                "url": i.get("html_url"),
                # PRs come back in the issues list too — keep a flag so
                # the agent can distinguish them from real issues.
                "is_pull_request": "pull_request" in i,
            }
            for i in out[:limit]
            if "pull_request" not in i  # exclude PRs by default
        ]

    def get_issue(self, owner: str, repo: str, number: int) -> dict | None:
        r = self._get(f"/repos/{owner}/{repo}/issues/{number}")
        if not isinstance(r, dict):
            return None
        return {
            "number": r.get("number"),
            "title": r.get("title"),
            "state": r.get("state"),
            "body": r.get("body"),
            "user": (r.get("user") or {}).get("login"),
            "labels": [lbl.get("name") for lbl in (r.get("labels") or [])],
            "comments": r.get("comments"),
            "url": r.get("html_url"),
        }

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        result = self._post(f"/repos/{owner}/{repo}/issues", payload)
        return result if isinstance(result, dict) else {"_error": "unexpected response"}

    # ── pulls ────────────────────────────────────────────────────────
    def list_pulls(
        self, owner: str, repo: str, state: str = "open", limit: int = 20
    ) -> list[dict]:
        out = self._get(
            f"/repos/{owner}/{repo}/pulls",
            {"state": state, "per_page": min(limit, 100)},
        )
        if not isinstance(out, list):
            return []
        return [
            {
                "number": p["number"],
                "title": p.get("title"),
                "state": p.get("state"),
                "user": (p.get("user") or {}).get("login"),
                "head": (p.get("head") or {}).get("ref"),
                "base": (p.get("base") or {}).get("ref"),
                "url": p.get("html_url"),
                "draft": p.get("draft"),
            }
            for p in out[:limit]
        ]

    # ── content ──────────────────────────────────────────────────────
    def get_file_content(
        self, owner: str, repo: str, path: str, ref: str | None = None
    ) -> dict | None:
        params = {"ref": ref} if ref else None
        r = self._get(f"/repos/{owner}/{repo}/contents/{path}", params)
        if not isinstance(r, dict):
            return None
        if r.get("type") != "file":
            return {"_error": f"path is not a file: {r.get('type')}"}
        # Base64-decode; truncate to a sane size so we don't blow agent
        # context on a 10MB JSON blob the student didn't actually want.
        raw_b64 = r.get("content", "")
        encoding = r.get("encoding", "base64")
        text: str | None
        if encoding == "base64":
            try:
                text = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
            except Exception:
                text = None
        else:
            text = raw_b64
        if text and len(text) > 50_000:
            text = text[:50_000] + "\n…[truncated at 50000 chars]"
        return {
            "path": r.get("path"),
            "size": r.get("size"),
            "url": r.get("html_url"),
            "content": text,
        }

    # ── identity ─────────────────────────────────────────────────────
    def get_authenticated_user(self) -> dict | None:
        r = self._get("/user")
        if not isinstance(r, dict):
            return None
        return {
            "login": r.get("login"),
            "name": r.get("name"),
            "public_repos": r.get("public_repos"),
            "total_private_repos": r.get("total_private_repos"),
        }
