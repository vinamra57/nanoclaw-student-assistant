# Using the assistant (for students)

The assistant is a Discord bot that fronts a personal AI agent. It can
answer course questions, search EdStem, list Canvas assignments, check
Gradescope, and act on Google Workspace via Composio.

## Onboarding

1. **Sign in to ChatCSE** at https://chatcse.vercel.app.
2. **Find your Discord user_id**: open Discord → User Settings →
   Advanced → enable Developer Mode → right-click your avatar → Copy
   User ID.
3. **Spawn your assistant**:
   ```bash
   curl -X POST https://chatcse.vercel.app/api/me/spawn-assistant \
     -H "Authorization: Bearer $YOUR_SUPABASE_JWT" \
     -H "Content-Type: application/json" \
     -d '{"discord_user_id": "<your discord user id>"}'
   ```
   (A web button will replace this curl when the frontend ships.)
4. **DM the shared bot** anything ("hi"). It now routes your messages
   to your own assistant.

## Connecting external accounts (optional)

In a DM with the bot, type `/` and pick a slash command. Discord opens
a private modal — values typed there never appear in chat history.

| Command | What you paste | Where to get it |
|---|---|---|
| `/edstem-key` | Edstem API token | https://edstem.org/us/settings/api-tokens |
| `/canvas-key` | Canvas access token (+ `base_url:https://canvas.uw.edu` in metadata) | Canvas → Account → Settings → New Access Token |
| `/gradescope-key` | `<email>:<gradescope-local-password>` | See "Gradescope SSO note" below |
| `/connect <service>` | (none — opens an OAuth link) | Composio: Gmail, Calendar, Drive, Docs, Notion, Todoist, etc. |

Values are stored encrypted in ChatCSE; the agent fetches them on
demand. None of them are required — the bot will tell you which keys
to add when you ask something that needs one.

## Gradescope SSO note

If your Gradescope account is SSO-only (UW NetID and most schools
default to this), Gradescope rejects API logins. Set a Gradescope-local
password first:

1. Open https://www.gradescope.com/reset_password **in an incognito
   window** — your active SSO session in a regular browser will hijack
   the redirect.
2. Enter your school email; set any password from the email Gradescope
   sends. SSO still works after this.
3. DM the bot: `/gradescope-key <your-email>:<that-local-password>`.

## Asking things

Plain English. Examples:

| You ask | Source |
|---|---|
| "What is Paxos?" | Course Virtual TA — returns transcript + audio + slides |
| "What's new on Ed for 452?" | EdStem |
| "What's due this week on Canvas?" | Canvas |
| "List my Gradescope courses" | Gradescope |
| "What's on my calendar today?" | Composio (Google Calendar) |
| "Add a task to Todoist" | Composio (Todoist) |

Multi-turn works for course follow-ups — the bot remembers the last
few turns of context.

## Things to know

- **Privacy**: your secrets never enter chat history (modals deliver
  them out-of-band) and are never logged. The Virtual TA enforces
  per-user isolation — you only see your own conversation history.
- **Pleasantries** ("hi", "thanks") and off-topic questions ("what's
  the weather") get a short reply or are skipped — the course Virtual
  TA pipeline only fires for course content.
- **Re-spawn** to rotate your agent token: re-call `/api/me/spawn-assistant`.
  The old token stays valid until revoked by an operator (planned
  fix: auto-revoke).
