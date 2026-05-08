#!/usr/bin/env node
/**
 * MCP stdio-to-HTTP bridge for Composio's hosted MCP server.
 *
 * NanoClaw's agent-runner only spawns stdio MCP servers (see
 * nanoclaw/container/agent-runner/src/config.ts). Composio's MCP is HTTP-only,
 * so this bridge forwards stdio tool calls to Composio's hosted endpoint
 * with the admin api key and the per-user user_id pinned in.
 *
 * Mirrors mcp_servers/virtual-ta-bridge/bridge.mjs and edstem-bridge/bridge.mjs.
 *
 * Usage (inside the agent container):
 *   COMPOSIO_API_KEY=ak_...      # admin key, never user-facing
 *   COMPOSIO_USER_ID=8           # the ChatCSE user_id for this container
 *   COMPOSIO_SERVER_ID=2c9a...   # the MCP server id created in the dashboard
 *   node bridge.mjs
 */

// Composio is on the public internet; do NOT bypass OneCLI globally — only
// turn off the proxy for this connection. The other env-mutating bridges
// (virtual-ta, edstem) talk to host loopback; Composio is different.

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

const COMPOSIO_API_KEY = process.env.COMPOSIO_API_KEY || '';
const COMPOSIO_USER_ID = process.env.COMPOSIO_USER_ID || '';
const COMPOSIO_SERVER_ID = process.env.COMPOSIO_SERVER_ID || '';
const COMPOSIO_BACKEND =
  process.env.COMPOSIO_BACKEND || 'https://backend.composio.dev';

if (!COMPOSIO_API_KEY || !COMPOSIO_USER_ID || !COMPOSIO_SERVER_ID) {
  console.error(
    '[composio-bridge] Missing one of COMPOSIO_API_KEY / COMPOSIO_USER_ID / COMPOSIO_SERVER_ID'
  );
  console.error('[composio-bridge] Will expose a single offline-stub tool.');
}

const MCP_ENDPOINT =
  `${COMPOSIO_BACKEND.replace(/\/$/, '')}/v3/mcp/${COMPOSIO_SERVER_ID}/mcp` +
  (COMPOSIO_USER_ID ? `?user_id=${encodeURIComponent(COMPOSIO_USER_ID)}` : '');

// Most Composio tool calls are network-bound REST calls (Gmail, Sheets, etc.)
// that finish in <10s. 60s leaves comfortable headroom; longer hides hangs.
const TOOL_CALL_TIMEOUT_MS =
  Number(process.env.COMPOSIO_TOOL_TIMEOUT_MS) || 60_000;

const remoteTransport = new StreamableHTTPClientTransport(new URL(MCP_ENDPOINT), {
  requestInit: {
    headers: { 'x-api-key': COMPOSIO_API_KEY },
  },
});
const remoteClient = new Client({ name: 'composio-bridge', version: '1.0.0' });

const localServer = new Server(
  { name: 'composio', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

let remoteTools = [];

async function init() {
  if (COMPOSIO_API_KEY && COMPOSIO_USER_ID && COMPOSIO_SERVER_ID) {
    try {
      await remoteClient.connect(remoteTransport);
      const toolsResult = await remoteClient.listTools();
      remoteTools = toolsResult.tools || [];
      console.error(
        `[composio-bridge] Connected to Composio. ${remoteTools.length} tools available for user_id=${COMPOSIO_USER_ID}.`
      );
    } catch (err) {
      console.error(
        `[composio-bridge] Failed to connect to Composio at ${MCP_ENDPOINT}: ${err.message}`
      );
      remoteTools = offlineStub();
    }
  } else {
    remoteTools = offlineStub();
  }

  localServer.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: remoteTools,
  }));

  localServer.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    try {
      const result = await remoteClient.callTool(
        { name, arguments: args },
        undefined,
        { timeout: TOOL_CALL_TIMEOUT_MS }
      );
      // Composio's "no connected account" arrives as a NORMAL tool result with
      // isError=true, NOT a thrown exception. Detect it, initiate the OAuth
      // link inline, and rewrite the response to include the redirect URL.
      const augmented = await _augmentWithLinkOnAuthMissing(name, result);
      return augmented;
    } catch (err) {
      return {
        content: [{ type: 'text', text: `Error calling Composio: ${err.message}` }],
        isError: true,
      };
    }
  });

  const transport = new StdioServerTransport();
  await localServer.connect(transport);
  console.error('[composio-bridge] Stdio server running. Ready for tool calls.');
}

// toolkit_slug → auth_config_id, populated lazily on first auth-missing error.
//
// Hazard (D5): cache lifetime is the bridge process. New auth_configs added
// in the Composio dashboard mid-session won't be seen until the next
// container spawn. Acceptable since bridges are short-lived; if cache
// staleness ever becomes a real issue, add a TTL.
let _authConfigByToolkit = null;

async function _loadAuthConfigs() {
  if (_authConfigByToolkit !== null) return _authConfigByToolkit;
  _authConfigByToolkit = {};
  try {
    const r = await fetch(`${COMPOSIO_BACKEND}/api/v3/auth_configs?limit=200`, {
      headers: { 'x-api-key': COMPOSIO_API_KEY },
    });
    if (!r.ok) throw new Error(`auth_configs HTTP ${r.status}`);
    const j = await r.json();
    for (const ac of j.items || []) {
      const slug = ac.toolkit?.slug;
      if (slug && ac.id) _authConfigByToolkit[slug] = ac.id;
    }
    console.error(
      `[composio-bridge] loaded ${Object.keys(_authConfigByToolkit).length} auth_configs`
    );
  } catch (e) {
    console.error(`[composio-bridge] auth_configs fetch failed: ${e.message}`);
  }
  return _authConfigByToolkit;
}

async function _augmentWithLinkOnAuthMissing(toolName, result) {
  if (!result?.isError) return result;
  const text = (result.content || [])
    .map((c) => (c?.type === 'text' ? c.text : ''))
    .join(' ');
  // Composio's exact wording: "No connected account found for user ID <uid>
  // for toolkit <slug>". Match defensively.
  const match = text.match(
    /no connected account found.*?for toolkit\s+([a-z0-9_-]+)/i
  );
  if (!match) return result;
  const toolkit = match[1].toLowerCase();
  const map = await _loadAuthConfigs();
  const acId = map[toolkit];
  if (!acId) {
    return {
      content: [
        {
          type: 'text',
          text:
            `${text}\n\nThis toolkit (${toolkit}) does not have a Composio-managed ` +
            `auth_config in this project. Course staff: create one via the dashboard ` +
            `(or POST /api/v3/auth_configs with your own OAuth client credentials).`,
        },
      ],
      isError: true,
    };
  }
  try {
    const r = await fetch(
      `${COMPOSIO_BACKEND}/api/v3/connected_accounts/link`,
      {
        method: 'POST',
        headers: {
          'x-api-key': COMPOSIO_API_KEY,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          auth_config_id: acId,
          user_id: COMPOSIO_USER_ID,
        }),
      }
    );
    if (!r.ok) throw new Error(`link HTTP ${r.status}: ${await r.text()}`);
    const j = await r.json();
    const url = j.redirect_url || j.url || '';
    return {
      content: [
        {
          type: 'text',
          text:
            `AUTHORIZATION_REQUIRED for ${toolkit}.\n\n` +
            `Send the user EXACTLY this message verbatim (no paraphrasing — the ` +
            `link expires in ~30 minutes and they must click it immediately):\n\n` +
            `---\n` +
            `👉 **Click within 30 minutes** to connect ${toolkit}:\n` +
            `${url}\n\n` +
            `Once you've signed in and approved, just ask me the same thing again ` +
            `and I'll pull the data.\n` +
            `---\n\n` +
            `Then STOP. Do not call ${toolkit} tools again on this turn — wait ` +
            `for the next user message.`,
        },
      ],
      isError: false, // not really an error — actionable next step for the agent
    };
  } catch (e) {
    return {
      content: [
        { type: 'text', text: `${text}\n\nFailed to initiate auth link: ${e.message}` },
      ],
      isError: true,
    };
  }
}

function offlineStub() {
  return [
    {
      name: 'composio_unavailable',
      description:
        'Composio is not configured for this container. Ask staff to wire COMPOSIO_API_KEY/COMPOSIO_USER_ID/COMPOSIO_SERVER_ID.',
      inputSchema: { type: 'object', properties: {} },
    },
  ];
}

init().catch((err) => {
  console.error(`[composio-bridge] Fatal: ${err.message}`);
  process.exit(1);
});
