# Security model

This system is split across three trust zones with distinct credentials in each:

```
                  ┌───────────────────────────────────────┐
                  │ Zone 1: ChatCSE backend (multi-tenant)│
                  │  - Supabase JWTs (web users)          │
                  │  - agent_token signing key            │
                  │  - Fernet encryption key (SECRET_KEY) │
                  │  - Composio admin API key (M3)        │
                  └─────────────────┬─────────────────────┘
                                    │ HTTPS, bearer-token auth
                  ┌─────────────────▼─────────────────────┐
                  │ Zone 2: per-student VM (single-tenant)│
                  │  - Anthropic API key                  │
                  │  - Discord bot token                  │
                  │  - CHATCSE_AGENT_TOKEN                │
                  │  - per-provider keys (edstem, canvas, │
                  │    gradescope) — late-bindable        │
                  └─────────────────┬─────────────────────┘
                                    │ Docker bridge
                  ┌─────────────────▼─────────────────────┐
                  │ Zone 3: agent container (sandboxed)   │
                  │  - sees mcpServers env (R/W)          │
                  │  - mounts /workspace/agent/* RW       │
                  │  - 2 GB memory cap                    │
                  └───────────────────────────────────────┘
```

## Per-secret blast radius

| Secret | Stored where | Compromise gives attacker | Mitigations |
|---|---|---|---|
| `SECRET_KEY` (Fernet/HMAC) | ChatCSE backend env | Decrypt every provider credential AND forge signed media URLs | Refuse to boot non-DEV with default; rotate via `Base.metadata.drop_all/create_all` (re-encryption is one-shot) |
| `AGENT_TOKEN_SIGNING_KEY` (HS256) | ChatCSE backend env | Forge agent_tokens for any user_id | Refuse to boot non-DEV when empty; rotate by setting new key + revoking all live tokens (next bounce kills them) |
| `SUPABASE_JWT_SECRET` | Supabase project settings | Forge web-user JWTs | Rotate via Supabase dashboard; backend re-fetches JWKS automatically |
| `COMPOSIO_API_KEY` (admin) | per-student VM `~/student-assistant/.env` (chmod 600) AND ChatCSE for ops scripts | Issue/revoke connections for any user_id under our org | Rotate quarterly via Composio dashboard; one key per env (dev/prod) |
| `CHATCSE_AGENT_TOKEN` | per-student VM `~/student-assistant/.env` AND `groups/<id>/container.json` | Call ChatCSE MCP **as that one student** for the token's TTL | Per-token revocation via `DELETE /api/admin/agent-tokens/{id}`; default 30-day TTL; one token per (user, container) |
| Per-provider keys (Edstem / Canvas / Gradescope) | ChatCSE `provider_credentials` (Fernet) AND container memory at call-time | Read/write the student's own Edstem / Canvas / Gradescope account | Student can rotate from Edstem/Canvas dashboard; `DELETE /api/me/credentials/{provider}` removes our copy. **Gradescope: SSO accounts must set a local password via https://www.gradescope.com/reset_password opened in an INCOGNITO browser** (regular browser will hijack the redirect via the active SSO session). |
| Discord bot token | per-student VM `~/nanoclaw/.env` | Speak as the student's bot in Discord | One bot per student (provisioning); regenerate via Discord developer portal |
| Anthropic API key | per-student VM `~/nanoclaw/.env` | Charge inference to our account | Per-student key (preferred) or shared key with rate-limit; rotate from `console.anthropic.com` |

## Defense-in-depth layers

1. **Secrets never logged.** `app/log_redaction.py` installs a global filter on the root logger that regex-replaces JWTs, Bearer tokens, Composio keys, Edstem `prefix.body` tokens, and any `KNOWN_KEY=value` env-var-style strings. Tests assert the filter's behavior in `tests/backend/unit/test_log_redaction.py`.

2. **Secrets never entered the LLM context.** `provider-key-handler.ts` intercepts `/edstem-key`, `/canvas-key`, `/gradescope-key` BEFORE `writeSessionMessage`. Verified by `nanoclaw/src/provider-key-handler.test.ts` (10 tests, including "leak count == 0" assertions on log output).

3. **Secrets stored encrypted at rest.** `provider_credentials.ciphertext` uses the SQLAlchemy `EncryptedString` type which Fernet-encrypts/decrypts via `SECRET_KEY`. Same for the legacy `User.ed_api_token` (now removed, but the column existed for the same reason).

4. **Audit trail.** Every credential read/write/delete writes one row to `secret_access_log` with `(user_id, provider, action, actor, accessed_at)`. NO secret values in the audit columns (verified by `test_audit_log_never_contains_the_secret_value`).

5. **Per-user isolation at the MCP layer.** `mcp_server.py::_resolve_user` refuses to fall through to a shared `agent:default` user when `SUPABASE_URL` is set. `get_playback` enforces `Question.user_id == current_user.id` before serving signed URLs.

6. **Container-side blast radius.** Each agent container is capped at 2 GB; the `~student-assistant/.env` is chmod 600 (file perms enforced by setup-student.sh).

## Auto-rotation: NOT enabled

This codebase has **no automated key rotation**. Every rotation in the
runbook below is a manual operator action. Do not introduce auto-rotation
(e.g. a cron that re-issues `AGENT_TOKEN_SIGNING_KEY`) without explicit
sign-off — auto-rotation that runs while a study is live can lock students
out mid-conversation, and the staged "issue new + grace period + revoke
old" pattern needed to do it safely is non-trivial. For now: rotate
manually, document each rotation in your incident log.

## Rotation runbook

### Rotate `AGENT_TOKEN_SIGNING_KEY`

1. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Update `backend/.env` AGENT_TOKEN_SIGNING_KEY to the new value.
3. Bounce backend: `pkill -f "uvicorn app.main"; cd backend && PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000 &`.
4. Every existing agent_token is now invalid (different signing key). Re-issue:
   ```bash
   for token_id in $(curl -sS -H "Authorization: Bearer $SUPABASE_JWT" 'https://chatcse.example.com/api/admin/agent-tokens' | jq -r '.[].id'); do
     # Get user_id + container_id from each, re-issue, re-deploy to VM
     ...
   done
   ```

### Rotate Composio admin API key

1. Composio dashboard → API Keys → Create new.
2. Update each per-student `~/student-assistant/.env` (script across VMs).
3. Bounce nanoclaw daemons: `ssh <vm> 'pkill -f "node.*dist/index.js"; cd nanoclaw && node dist/index.js &'`.
4. Revoke old key in Composio dashboard.

### Rotate `SECRET_KEY` (heaviest)

1. **Read every existing `provider_credentials` ciphertext WITH the old key, re-encrypt with the new key.**
2. Same for the audit log (no plaintext, but the encryption envelope has the key version).
3. Set new `SECRET_KEY`, bounce backend.
4. (No safe shortcut. `drop_all/create_all` works only if you're OK losing all stored credentials and asking students to re-enter.)

### Per-student lockout (e.g. compromised laptop)

```bash
# 1. Revoke the agent token for that container
curl -X DELETE -H "Authorization: Bearer $SUPABASE_JWT" \
  https://chatcse.example.com/api/admin/agent-tokens/<TOKEN_ID>

# 2. Revoke Composio connections for that user
COMPOSIO_API_KEY=... composio link gmail --user-id <CHATCSE_USER_ID> --revoke

# 3. Tear down the VM
gcloud compute instances delete nanoclaw-<STUDENT> --project=... --zone=...

# 4. Tell the student to rotate their Edstem token from edstem.org/us/settings
```

Within ~60 seconds of step 1, the container's MCP calls 401. The other steps are belt-and-suspenders.

## What this model does NOT defend against

- **A student leaking their own keys deliberately.** We can't stop a student from copy-pasting their `CHATCSE_AGENT_TOKEN` into a public Slack. We can detect (audit log shows unusual call patterns) and remediate (revoke), but not prevent.
- **Compromise of the ChatCSE backend host.** The Fernet key is in env, so root on that host == decrypt every credential. Mitigations: cloud KMS for `SECRET_KEY` is the path forward (the code is structured to swap `crypto.py` cleanly). Until then: hardened OS, separated network, audited access.
- **Compromise of Composio's hosted MCP.** We trust Composio's TLS/auth boundary for the per-app OAuth tokens. Their security review is on us to verify before scaling beyond a small study.

## Production VM topology (for the real study with students)

The `provisioning/provision-student.sh` script already targets GCP VMs (one
per student). For the study:

- One VM per student (gcloud compute instances create), e2-medium, 20 GB disk.
- VM has no public IP unless Discord requires it (the bot is gateway-pull).
- Per-VM secret material in `~student-assistant/.env` (chmod 600).
- ChatCSE backend on a separate hardened VM behind a load balancer.
- Composio admin key in our centralized secrets store, distributed at provisioning.
- Audit logs aggregated to a central log sink (Cloud Logging) with a
  redaction transform on the receiving side as well as ours.

This local-Docker setup mirrors that exactly — same `mcpServers` shape,
same env files, same bridge code. The migration is "swap localhost for
the real backend URL and ship the same `.env`."
