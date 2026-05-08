# NanoClaw control API

The NanoClaw daemon (this fork) exposes a small HTTP control plane on
the same port as the webhook server (default 3000) for external
orchestrators — primarily ChatCSE — to wire Discord users to
agent_groups without holding a CLI session.

## Auth

All `/api/*` endpoints require:

```
Authorization: Bearer <NANOCLAW_CONTROL_TOKEN>
```

The expected token comes from the `NANOCLAW_CONTROL_TOKEN` env var at
daemon startup. **If the env var is unset, every `/api/*` request
returns 503 ("control plane disabled")** — fail-closed so a
misconfigured deployment cannot accidentally accept anonymous
wirings.

Comparison is constant-time-ish (`crypto.timingSafeEqual`).

## Endpoints

### `POST /api/agent-groups/wirings`

Idempotently register a `(channel_type, platform_id) → agent_group`
routing entry. Used by ChatCSE's `/api/me/spawn-assistant` to wire
a freshly-spawned student.

**Body:**

```json
{
  "channel_type": "discord",
  "platform_id": "@me:1143424326331285504",
  "agent_group_id": "ag-1777411507061-5s85fk",
  "name": "Vinamra DM",
  "engage_mode": "pattern",
  "engage_pattern": ".",
  "session_mode": "shared",
  "sender_scope": "all",
  "is_group": false,
  "unknown_sender_policy": "public"
}
```

Required: `channel_type`, `platform_id`, `agent_group_id`. The rest
default to safe per-user-DM values (`pattern` / `.` / `shared` /
`all` / `public`).

**Response:**

```json
{
  "messaging_group_id": "mg-...",
  "messaging_group_agent_id": "mga-...",
  "created": true
}
```

`created` is `false` if the wiring already existed; the IDs are still
returned. Re-posting the same triple is a no-op aside from an info-level
log line.

## Future endpoints

- `POST /api/agent-groups` — create a new agent_group + spawn its
  container (currently agent_groups must be pre-provisioned via the
  CLI). Needed before per-student container isolation can ship.
- `DELETE /api/agent-groups/wirings` — un-wire a Discord user (e.g.
  on student account deletion in ChatCSE).

## Implementation pointers

| Concern | File |
|---|---|
| HTTP routing + auth | `nanoclaw/src/control-api.ts` |
| Server bootstrap | `nanoclaw/src/webhook-server.ts` (`ensureHttpServer`) |
| Underlying writes | `nanoclaw/src/db/messaging-groups.ts` |
| Tests | `nanoclaw/src/control-api.test.ts` |
