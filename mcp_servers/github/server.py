"""Personal GitHub MCP server.

Exposes a small, focused tool surface over the official GitHub REST v3
API, scoped to a single student via their personal access token. Same
shape as edstem/canvas/gradescope: credential pulled on demand from
ChatCSE `provider_credentials`, streamable-HTTP transport on a fixed
port so the per-student container's bridge can reach us.

Why we wrote our own instead of using `github/github-mcp-server`: the
official one is stdio-only and would have to run inside each per-student
container with Docker-in-Docker. Easier to keep one streamable-HTTP
process on the host like the other providers — same auth model, same
deploy pattern, same audit story.

Usage (stdio default):
    CHATCSE_AGENT_TOKEN=<token> CHATCSE_BASE_URL=<url> \\
    python -m mcp_servers.github.server

Usage (HTTP — dev on Mac, agent container connects to host):
    GITHUB_TRANSPORT=streamable-http GITHUB_PORT=8768 \\
    CHATCSE_AGENT_TOKEN=<token> CHATCSE_BASE_URL=<url> \\
    python -m mcp_servers.github.server
"""

from __future__ import annotations

import json
import os
from typing import Literal, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_servers.github.gh_client import GhClient

_HOST = os.environ.get("GITHUB_HOST", "127.0.0.1")
_PORT = int(os.environ.get("GITHUB_PORT", "8768"))

# DNS-rebinding allowlist — same set as the other host MCPs.
_ALLOWED_HOSTS = [
    "127.0.0.1:*",
    "localhost:*",
    "[::1]:*",
    "host.docker.internal:*",
]
_ALLOWED_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
    "http://host.docker.internal:*",
]

mcp = FastMCP(
    "GitHub Personal",
    host=_HOST,
    port=_PORT,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_ALLOWED_HOSTS,
        allowed_origins=_ALLOWED_ORIGINS,
    ),
)


def _get_client() -> GhClient:
    from mcp_servers._shared.credentials import get_provider_credential

    cred = get_provider_credential("github")
    token = cred[0] if cred else ""
    return GhClient(token=token)


def _not_configured() -> str:
    return (
        "GitHub isn't connected yet. To connect: in Discord, type "
        "`/github-key`, paste a personal access token (create one at "
        "https://github.com/settings/tokens with the `repo` scope) into "
        "the modal, and submit. The token never appears in chat history."
    )


@mcp.tool()
def get_github_user() -> str:
    """Return basic info about the authenticated GitHub user (login, name, repo counts).

    Useful sanity check before any other call — confirms the token is
    valid and identifies the account.
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    info = c.get_authenticated_user()
    if not info:
        return "GitHub token is set but the /user call failed — token may be expired or lack scope."
    return json.dumps(info, indent=2)


@mcp.tool()
def list_github_repos(limit: int = 30) -> str:
    """List the user's repositories, most-recently-updated first.

    Args:
        limit: Maximum number of repos to return (default 30, max 100).
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    repos = c.list_user_repos(limit=min(limit, 100))
    if not repos:
        return "No repos visible to this token."
    return json.dumps(repos, indent=2)


@mcp.tool()
def get_github_repo(owner: str, repo: str) -> str:
    """Get summary info (description, stars, default branch, open issues) for one repo.

    Args:
        owner: Repo owner (user or org name).
        repo: Repo name.
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    info = c.get_repo(owner, repo)
    if not info:
        return f"Repo {owner}/{repo} not found or not visible."
    return json.dumps(info, indent=2)


@mcp.tool()
def list_github_issues(
    owner: str, repo: str, state: str = "open", limit: int = 20
) -> str:
    """List issues for a repo. Excludes pull requests by default.

    Args:
        owner: Repo owner.
        repo: Repo name.
        state: One of "open", "closed", "all" (default "open").
        limit: Maximum number of issues (default 20).
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    issues = c.list_issues(owner, repo, state=state, limit=min(limit, 100))
    if not issues:
        return f"No {state} issues in {owner}/{repo}."
    return json.dumps(issues, indent=2)


@mcp.tool()
def get_github_issue(owner: str, repo: str, number: int) -> str:
    """Get the body, labels, and metadata of one issue.

    Args:
        owner: Repo owner.
        repo: Repo name.
        number: Issue number.
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    issue = c.get_issue(owner, repo, number)
    if not issue:
        return f"Issue {owner}/{repo}#{number} not found."
    return json.dumps(issue, indent=2)


@mcp.tool()
def create_github_issue(
    owner: str, repo: str, title: str, body: str = "", labels: list[str] | None = None
) -> str:
    """Open a new issue. Returns the created issue's JSON.

    Args:
        owner: Repo owner.
        repo: Repo name.
        title: Issue title.
        body: Issue body (markdown). Defaults to empty.
        labels: Optional list of label names to attach.
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    result = c.create_issue(owner, repo, title=title, body=body, labels=labels)
    return json.dumps(result, indent=2)


@mcp.tool()
def list_github_pulls(
    owner: str, repo: str, state: str = "open", limit: int = 20
) -> str:
    """List pull requests for a repo.

    Args:
        owner: Repo owner.
        repo: Repo name.
        state: One of "open", "closed", "all" (default "open").
        limit: Maximum number of PRs (default 20).
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    pulls = c.list_pulls(owner, repo, state=state, limit=min(limit, 100))
    if not pulls:
        return f"No {state} pull requests in {owner}/{repo}."
    return json.dumps(pulls, indent=2)


@mcp.tool()
def get_github_file_content(
    owner: str, repo: str, path: str, ref: str | None = None
) -> str:
    """Fetch a file's contents from a repo. Truncates to 50000 chars.

    Args:
        owner: Repo owner.
        repo: Repo name.
        path: File path within the repo (e.g. "README.md", "src/main.py").
        ref: Optional branch/tag/commit SHA. Defaults to the default branch.
    """
    c = _get_client()
    if not c.is_configured:
        return _not_configured()
    res = c.get_file_content(owner, repo, path, ref=ref)
    if not res:
        return f"File {owner}/{repo}:{path} not found at ref {ref or '(default)'}."
    return json.dumps(res, indent=2)


if __name__ == "__main__":
    transport = os.environ.get("GITHUB_TRANSPORT", "stdio")
    mcp.run(transport=cast(Literal["stdio", "sse", "streamable-http"], transport))
