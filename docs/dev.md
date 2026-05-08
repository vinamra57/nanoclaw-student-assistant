# Developer guide

Architecture, code map, and the operator runbook for this project.

## Three repos

| Repo | Role |
|---|---|
| **ChatCSE** (`chughtapan/ChatCSE`, branch `vinamra/per-user-auth`) | Web backend (FastAPI + SQLAlchemy). Owns auth, the Virtual TA pipeline (course content), per-user `provider_credentials` (encrypted), `agent_tokens`, and the spawn endpoint. |
| **nanoclaw-student-assistant** (this repo) | Per-student MCP servers (Edstem, Canvas, Gradescope) + their stdio→HTTP bridges. The python `_shared/credentials.py` helper is the load-bearing piece that fetches secrets from ChatCSE on demand. |
| **nanoclaw fork** (`vinamra57/nanoclaw`, branch `student-assistant-patches`, vendored as `nanoclaw/` submodule here) | NanoClaw daemon — Discord channel adapter, agent-group routing, the new `/api/agent-groups/wirings` control plane, log redaction, slash commands + modals. |

## Trust zones and credentials

```
[ChatCSE backend]                       [shared VM]
  Supabase JWT (web users)                NanoClaw daemon (one process)
  AGENT_TOKEN_SIGNING_KEY                 ANTHROPIC_API_KEY (one shared)
  SECRET_KEY (Fernet)                     DISCORD_BOT_TOKEN (one shared bot)
  provider_credentials (encrypted)        NANOCLAW_CONTROL_TOKEN
                                          ↓ spawns
        ↓ HTTPS, Bearer agent_token       per-student container
  /api/agent/credentials/<provider> ───── only sees CHATCSE_AGENT_TOKEN
                                          ↓
                                          host MCP servers (edstem/canvas/gradescope)
                                          fetch creds on demand via the helper
```

- **`CHATCSE_AGENT_TOKEN`**: HS256 JWT signed by ChatCSE. The only
  per-student secret in a container. 30-day default TTL.
- **`provider_credentials`**: per-(user, provider) Fernet-encrypted
  rows in ChatCSE. Read by the host MCP servers (5 min cache),
  written by Discord slash commands (`/edstem-key`, `/canvas-key`,
  `/gradescope-key`).
- **`NANOCLAW_CONTROL_TOKEN`**: bearer credential for ChatCSE → daemon
  RPC. Set in both repos' env. Fail-closed: if unset on the daemon
  side, every `/api/*` returns 503.

## Self-service spawn flow

```
[student in browser]               [ChatCSE backend]                  [NanoClaw daemon]
  POST /api/me/spawn-assistant ──→ verify Supabase JWT
                                   issue_agent_token
                                   POST /api/agent-groups/wirings ──→ insert messaging_group
                                                                     + messaging_group_agent
                                   ←── { messaging_group_id, ... }
  ←── { agent_token, wired:true } 
  
[student DMs the shared bot]  ──→ Discord → daemon adapter
                                   getMessagingGroupWithAgentCount
                                   ("discord", "@me:<student_id>")
                                   →   route to wired agent_group
                                   →   wake the student's container
```

Settings on each side:

- **ChatCSE**: `AGENT_TOKEN_SIGNING_KEY`, `NANOCLAW_CONTROL_URL`,
  `NANOCLAW_CONTROL_TOKEN`, `NANOCLAW_DEFAULT_AGENT_GROUP_ID`.
- **NanoClaw daemon**: `NANOCLAW_CONTROL_TOKEN` (must match), plus
  the standard `DISCORD_BOT_TOKEN`, `ANTHROPIC_API_KEY`.
- **Each container**: `CHATCSE_AGENT_TOKEN`, `CHATCSE_BASE_URL`. No
  per-provider secrets.

## NanoClaw control API

Single endpoint today; auth via `Authorization: Bearer <NANOCLAW_CONTROL_TOKEN>`.

```http
POST /api/agent-groups/wirings
{
  "channel_type": "discord",
  "platform_id": "@me:<discord_user_id>",
  "agent_group_id": "ag-...",
  "engage_mode": "pattern",       # default
  "engage_pattern": ".",           # default — match all
  "session_mode": "shared",        # default
  "sender_scope": "all"            # default
}
→ 200 { messaging_group_id, messaging_group_agent_id, created }
```

Idempotent on `(channel_type, platform_id, agent_group_id)` — re-posts
return existing IDs with `created:false`.

Implementation: `nanoclaw/src/control-api.ts` + `webhook-server.ts`.
Tests: `nanoclaw/src/control-api.test.ts`.

## Bridges and credential helper

`mcp_servers/<provider>-bridge/bridge.mjs` runs INSIDE the per-student
container and proxies stdio MCP requests to the host MCP server over
streamable-HTTP. The bridges:

- Auto-detect upstream session loss (404 / "session" / "closed" /
  ECONNRESET / connection refused) and reconnect transparently — so
  bouncing the host MCP servers does not require students to bounce
  their containers.
- Fall back to a stub tool that explains the host is offline if the
  initial connect fails.

Host MCP servers run as long-lived python processes on the shared VM:

```
edstem    127.0.0.1:8765
canvas    127.0.0.1:8766
gradescope 127.0.0.1:8767
```

Each server's `_get_client()` calls `mcp_servers._shared.credentials.
get_provider_credential(name)` on every tool invocation. The helper
holds a 5-minute per-process cache, so a `/edstem-key` rotation
propagates within that window without restart.

## Local development

```bash
# Python deps (host MCP servers + tests)
cd nanoclaw-student-assistant
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# Tests
.venv/bin/pytest                            # 62 tests
.venv/bin/ruff check .
.venv/bin/mypy mcp_servers/

# Bridges + daemon (TypeScript)
cd nanoclaw
pnpm install
node_modules/.bin/vitest run                 # 314 tests
node_modules/.bin/tsc --noEmit
```

To run the host MCP servers locally (they fetch creds from a running
ChatCSE):

```bash
export CHATCSE_AGENT_TOKEN="<from /api/me/spawn-assistant>"
export CHATCSE_BASE_URL="http://localhost:8000"

EDSTEM_TRANSPORT=streamable-http EDSTEM_PORT=8765 \
  .venv/bin/python -m mcp_servers.edstem.server &
CANVAS_TRANSPORT=streamable-http CANVAS_PORT=8766 \
  .venv/bin/python -m mcp_servers.canvas.server &
GRADESCOPE_TRANSPORT=streamable-http GRADESCOPE_PORT=8767 \
  .venv/bin/python -m mcp_servers.gradescope.server &
```

## Operator runbook

- **Rotate a student's agent_token**: `POST /api/me/spawn-assistant`
  again from their account. The old token is NOT auto-revoked
  (D4 hazard); revoke explicitly via `POST /api/admin/agent-tokens/<id>/revoke`
  if it leaked.
- **Rotate `AGENT_TOKEN_SIGNING_KEY`**: invalidates ALL outstanding
  agent_tokens; every container needs a re-spawn afterward.
- **Bounce a host MCP server**: just restart it. Bridges reconnect
  on the next tool call (verified end-to-end).
- **Audit a credential read**: query `secret_access_log` in ChatCSE.

## Open follow-ups

- **Per-student container spawn**: today everyone wires against
  `NANOCLAW_DEFAULT_AGENT_GROUP_ID`; needs `POST /api/agent-groups`
  on the daemon to create a fresh agent_group + container per student.
- **Discord OAuth**: replace the manual user_id paste with an OAuth
  round-trip in the spawn flow.
- **Webhook persona**: outbound display name is the shared bot's
  today; per-student "Vinamra's agent" personas via Discord webhooks
  are tracked but unimplemented.
- **Auto-revoke prior agent_token on re-spawn**: bound the blast
  radius of leaked one-time-view tokens.
