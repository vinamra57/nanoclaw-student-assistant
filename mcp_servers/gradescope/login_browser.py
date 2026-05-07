"""Bootstrap a Gradescope session by driving the SSO login flow in a real browser.

Gradescope has no public API and rejects direct email+password POSTs from
SSO-only accounts (which is essentially every university account: UW NetID,
MIT IdP, Stanford SAML, etc.). The only viable path is "log in like a human,
keep the cookies."

This script:
  1. Pops up a Chromium window (Playwright, headless=False) on the user's Mac.
  2. Navigates to https://www.gradescope.com/login.
  3. Waits for the user to click their school, sign in via SSO + 2FA, and
     land on the dashboard.
  4. Captures the post-login cookies for `.gradescope.com`.
  5. Writes them to JSON at `--out` (chmod 600).
  6. Closes the browser.

Usage:
    python -m mcp_servers.gradescope.login_browser \\
        --out ~/.config/chatcse-test-secrets/gradescope-cookies.json

The Gradescope MCP server can then be started with:
    GRADESCOPE_COOKIES_PATH=~/.config/chatcse-test-secrets/gradescope-cookies.json \\
        python -m mcp_servers.gradescope.server

Cookies typically live ~2 weeks (Gradescope's session TTL). When the MCP
server starts seeing 401/login-redirects, re-run this bootstrap.
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

GS_BASE = "https://www.gradescope.com"
LOGIN_URL = f"{GS_BASE}/login"
# The dashboard uses /account for landing after login; some flows hit
# /dashboard instead. Either signals success.
LOGGED_IN_URL_FRAGMENTS = ("/account", "/dashboard", "/courses")


def capture_cookies(out_path: Path, *, max_wait_seconds: int = 600) -> int:
    """Return number of cookies captured, or 0 on timeout."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print(f"[login_browser] opening {LOGIN_URL}")
        print(
            "[login_browser] complete the SSO flow in the browser window — "
            f"you have {max_wait_seconds}s before the script gives up"
        )
        page.goto(LOGIN_URL)

        deadline = time.time() + max_wait_seconds
        last_url = ""
        while time.time() < deadline:
            try:
                cur = page.url
                if cur != last_url:
                    print(f"[login_browser] navigated to {cur}")
                    last_url = cur
                if any(frag in cur for frag in LOGGED_IN_URL_FRAGMENTS):
                    # Give the page a beat to set any post-redirect cookies.
                    time.sleep(2)
                    cookies = context.cookies(GS_BASE)
                    if cookies:
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_text(json.dumps(cookies, indent=2))
                        out_path.chmod(0o600)
                        print(
                            f"[login_browser] captured {len(cookies)} cookies → {out_path}"
                        )
                        browser.close()
                        return len(cookies)
            except Exception as e:
                # Page can transiently throw during navigation; wait and retry.
                print(f"[login_browser] (transient) {e!s}")
            time.sleep(1)

        print(
            f"[login_browser] TIMEOUT after {max_wait_seconds}s — "
            "browser left open so you can inspect; close it manually."
        )
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture Gradescope SSO cookies.")
    ap.add_argument(
        "--out",
        default=os.path.expanduser(
            "~/.config/chatcse-test-secrets/gradescope-cookies.json"
        ),
        help="Where to write the cookie JSON (chmod 600).",
    )
    ap.add_argument(
        "--max-wait-seconds",
        type=int,
        default=600,
        help="Give up if the user hasn't completed login by then.",
    )
    args = ap.parse_args()
    out = Path(args.out).expanduser()
    n = capture_cookies(out, max_wait_seconds=args.max_wait_seconds)
    return 0 if n > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
