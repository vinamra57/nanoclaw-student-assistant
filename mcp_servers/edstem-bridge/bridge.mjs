#!/usr/bin/env node
/**
 * MCP stdio-to-HTTP bridge for the personal EdStem MCP server.
 *
 * NanoClaw's agent-runner only spawns stdio MCP servers (see
 * agent-runner/src/config.ts: McpServerConfig is { command, args, env }).
 * The EdStem MCP server runs as a long-lived HTTP service on the host
 * (see mcp_servers/edstem/server.py with EDSTEM_TRANSPORT=streamable-http),
 * so the agent reaches it through this bridge.
 *
 * Mirrors mcp_servers/virtual-ta-bridge/bridge.mjs intentionally.
 *
 * Usage (inside the agent container):
 *   EDSTEM_HTTP_URL=http://host.docker.internal:8765/mcp node bridge.mjs
 */

// Bypass OneCLI proxy — same reason as virtual-ta-bridge: the proxy injects
// credentials for outbound LLM/API traffic, but the EdStem MCP is on the host
// loopback and doesn't need it.
delete process.env.HTTP_PROXY;
delete process.env.HTTPS_PROXY;
delete process.env.http_proxy;
delete process.env.https_proxy;

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

const EDSTEM_HTTP_URL =
  process.env.EDSTEM_HTTP_URL || 'http://host.docker.internal:8765/mcp';

// EdStem API calls are fast (Ed REST API), so 30s is a generous ceiling that
// still surfaces hung calls.
const TOOL_CALL_TIMEOUT_MS =
  Number(process.env.EDSTEM_TOOL_TIMEOUT_MS) || 30_000;

let remoteClient = null;

const localServer = new Server(
  { name: 'edstem', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

let remoteTools = [];

// Re-establish the upstream MCP session — used both at startup and after
// session-loss errors (host MCP server restarts, network blip, etc.).
async function connectUpstream() {
  if (remoteClient) {
    try { await remoteClient.close(); } catch {}
  }
  const transport = new StreamableHTTPClientTransport(new URL(EDSTEM_HTTP_URL));
  remoteClient = new Client({ name: 'edstem-bridge', version: '1.0.0' });
  await remoteClient.connect(transport);
}

// True for errors that mean "your session is gone, reconnect and retry".
// Streamable-HTTP MCP returns 404 on stale session ids; we also catch
// closed-transport variants seen when the upstream process restarted.
function isSessionLoss(err) {
  const m = String(err?.message || '').toLowerCase();
  return (
    m.includes('session') ||
    m.includes('404') ||
    m.includes('not found') ||
    m.includes('closed') ||
    m.includes('econnreset') ||
    m.includes('connection refused')
  );
}

async function init() {
  try {
    await connectUpstream();
    const toolsResult = await remoteClient.listTools();
    remoteTools = toolsResult.tools || [];
    console.error(
      `[edstem-bridge] Connected to EdStem MCP. ${remoteTools.length} tools available.`
    );
  } catch (err) {
    console.error(
      `[edstem-bridge] Failed to connect to EdStem MCP at ${EDSTEM_HTTP_URL}: ${err.message}`
    );
    console.error(`[edstem-bridge] Will expose a single offline-stub tool.`);
    remoteTools = [
      {
        name: 'search_ed',
        description:
          'Search Ed Discussion (OFFLINE — host EdStem MCP unreachable; the host process needs to be restarted, or the student needs to set their Edstem token via Discord `/edstem-key`).',
        inputSchema: {
          type: 'object',
          properties: {
            query: { type: 'string', description: 'Search keywords' },
          },
          required: ['query'],
        },
      },
    ];
  }

  localServer.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: remoteTools,
  }));

  localServer.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    const callOnce = () => remoteClient.callTool(
      { name, arguments: args },
      undefined,
      { timeout: TOOL_CALL_TIMEOUT_MS }
    );
    try {
      return await callOnce();
    } catch (err) {
      if (!isSessionLoss(err)) {
        return {
          content: [{ type: 'text', text: `Error calling EdStem: ${err.message}` }],
          isError: true,
        };
      }
      console.error(
        `[edstem-bridge] Upstream session lost (${err.message}); reconnecting and retrying once.`
      );
      try {
        await connectUpstream();
        const toolsResult = await remoteClient.listTools();
        remoteTools = toolsResult.tools || [];
        return await callOnce();
      } catch (retryErr) {
        return {
          content: [{ type: 'text', text: `Error calling EdStem after reconnect: ${retryErr.message}` }],
          isError: true,
        };
      }
    }
  });

  const transport = new StdioServerTransport();
  await localServer.connect(transport);
  console.error('[edstem-bridge] Stdio server running. Ready for tool calls.');
}

init().catch((err) => {
  console.error(`[edstem-bridge] Fatal: ${err.message}`);
  process.exit(1);
});
