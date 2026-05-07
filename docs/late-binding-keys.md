# Late-binding API keys

The container is provisioned with a fixed set of credentials at setup time
(Anthropic, Discord, Virtual TA agent token). Anything optional — Edstem,
Canvas, Gradescope — can be added LATER via a slash command in the bot's
DM, without re-provisioning the container.

## Recommended: Discord slash commands + modals

In any Discord DM with the bot, type `/` and pick `/edstem-key`,
`/canvas-key`, or `/gradescope-key`. Discord opens a **private modal**
prompting for the value; the value you type is delivered to the bot via
an interaction payload and **never appears as a chat message**. There is
nothing to delete afterwards — the secret literally never enters chat
history.

This is the production path. It works in DMs and in guilds, requires no
special permissions, and is the only flow safe for sensitive keys.

The bot acknowledges with an ephemeral reply ("✅ Your edstem key is
saved...") that only you can see and which auto-disappears from view as
the channel scrolls.

## Legacy fallback: text-message slash commands

The pre-modal flow still works for backwards compatibility:

| Command | Provider | Format |
|---|---|---|
| `/edstem-key <token>` | Edstem (course discussion) | The personal API token from https://edstem.org/us/settings/api-tokens |
| `/canvas-key <token>` | Canvas LMS | Personal access token from Canvas → Account → Settings → New Access Token |
| `/gradescope-key <email>:<password>` | Gradescope | A **Gradescope-local** email + password (see "Gradescope local password" below — your UW NetID password does NOT work) |

The text-message form has the same security posture (intercepted before
LLM, encrypted server-side, never logged) BUT the message stays in your
chat history because Discord doesn't allow bots to delete user DMs.
Prefer the modal flow above when available.

## Gradescope local password (UW + most SSO schools)

Gradescope has no public API and rejects direct logins for accounts that
were created via SSO. **You need a Gradescope-local password set on the
same email as your SSO account** — this is officially supported and
independent of your school's SSO password.

To set one:

1. **Open https://www.gradescope.com/reset_password in a private / incognito
   browser window.** This is critical — if you open it in your normal
   browser, your active SSO session can hijack the redirect and you'll
   land back on the dashboard without ever setting a local password.
2. Enter your school email (e.g. `vinamra1@uw.edu`).
3. Click the email Gradescope sends you, set any password.
4. Test the new password by logging in at gradescope.com (still in the
   incognito window) — confirm it lets you in without bouncing to your
   SSO IdP.
5. Now DM the bot: `/gradescope-key <your-email>:<that-new-password>`.

You will now have TWO ways to log into Gradescope: (a) via your school's
SSO, (b) via this local password. Both work and don't interfere; the
local password is what we use for API access.

## What happens when you DM `/edstem-key …`

1. **The host intercepts** — the slash command is parsed by `nanoclaw/src/provider-key-handler.ts` BEFORE the message reaches the LLM container. Your secret never enters the agent's context window.

2. **Encrypted at rest** — the bot POSTs the value to ChatCSE's
   `/api/agent/credentials/<provider>` endpoint, where it's stored in the
   `provider_credentials` table with Fernet encryption (key derived from
   `SECRET_KEY`).

3. **Audit row written** — `secret_access_log` gets one row capturing
   `(user_id, provider, action="write", actor="agent_token:user:N", accessed_at)`.
   Never the value itself.

4. **The bot replies with a confirmation** that includes:
   *"Please delete your message above for security."* Discord deletion
   from the bot side requires deeper Discord API integration (tracked as
   a follow-up); for now you should delete the message manually after
   the confirmation arrives.

5. **Next MCP call uses it** — the relevant MCP server (Edstem, Canvas,
   Gradescope) reads the new credential on its next invocation. No
   container restart required.

## Verifying it stuck

You can confirm the key was stored without revealing it via:

```bash
curl -H "Authorization: Bearer $SUPABASE_JWT" \
  https://chatcse.example.com/api/me/credentials
```

Returns `[{"provider": "edstem", "metadata": null, "created_at": "...", "updated_at": "...", "last_used_at": "..."}]` — metadata only, never plaintext.

## Updating an existing key

Just DM the slash command again with the new value. The handler's storage
layer is upsert (unique on `(user_id, provider)`), so the second call
overwrites the first. The `secret_access_log` keeps both rows so the
rotation is auditable.

## Removing a key

Web UI:
```bash
curl -X DELETE -H "Authorization: Bearer $SUPABASE_JWT" \
  https://chatcse.example.com/api/me/credentials/edstem
```

There's currently no `/edstem-key-delete` slash command — the chat UI is
write-only on purpose so a malicious chat-history scraper can't trivially
nuke a student's connections.

## Security guarantees we make

- The plaintext value is in memory at exactly two points: the HTTP request
  body when you send `/edstem-key`, and the response body when the agent
  container reads it back via `/api/agent/credentials/<provider>` to inject
  into the relevant MCP server's env.
- The plaintext value is **NOT** in:
  - Any log line on the host (verified by `tests/test_provider_key_handler` —
    `leak count: 0` after every test).
  - The agent container's session messages (intercepted before
    `writeSessionMessage`).
  - The ChatCSE DB column (Fernet ciphertext only).
  - The `secret_access_log` audit rows (metadata only).
- The plaintext IS in the Discord message you typed — that's why the
  confirmation reply tells you to delete it.

## When to use the slash commands vs. provisioning

- **At provisioning (preferred for staff):** pass `--ed-token` etc. to
  `provision-student.sh`. The keys land in `~student-assistant/.env`
  before the container ever boots, so the very first agent message can
  use them.
- **Late-binding (preferred for students):** use the slash commands. No
  staff intervention, no SSH, the student adds keys themselves. The
  container learns about them on the next MCP call.

The two paths interoperate: a key set at provisioning can be overwritten
later via slash command, and vice versa.
