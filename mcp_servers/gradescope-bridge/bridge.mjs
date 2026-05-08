#!/usr/bin/env node
/**
 * MCP stdio-to-HTTP bridge for the personal Gradescope MCP server.
 *
 * Mirrors edstem-bridge / canvas-bridge — the host runs the python
 * Gradescope MCP server in HTTP mode (port 8767 by default), the agent
 * container reaches it via host.docker.internal.
 */

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

const GS_HTTP_URL =
  process.env.GRADESCOPE_HTTP_URL || 'http://host.docker.internal:8767/mcp';

// Gradescope login + page fetches can be slow (HTML scraping). 60s ceiling.
const TOOL_CALL_TIMEOUT_MS =
  Number(process.env.GRADESCOPE_TOOL_TIMEOUT_MS) || 60_000;

let remoteClient = null;

const localServer = new Server(
  { name: 'gradescope', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

let remoteTools = [];

// Re-establish the upstream MCP session — see edstem-bridge for rationale.
async function connectUpstream() {
  if (remoteClient) {
    try { await remoteClient.close(); } catch {}
  }
  const transport = new StreamableHTTPClientTransport(new URL(GS_HTTP_URL));
  remoteClient = new Client({ name: 'gradescope-bridge', version: '1.0.0' });
  await remoteClient.connect(transport);
}

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
    const t = await remoteClient.listTools();
    remoteTools = t.tools || [];
    console.error(`[gradescope-bridge] Connected. ${remoteTools.length} tools available.`);
  } catch (err) {
    console.error(
      `[gradescope-bridge] Failed to connect to Gradescope MCP at ${GS_HTTP_URL}: ${err.message}`
    );
    remoteTools = [
      {
        name: 'list_gradescope_courses',
        description:
          'List Gradescope courses (OFFLINE — host Gradescope MCP unreachable; ask staff to start it or DM /gradescope-key <email>:<password> after configuring it).',
        inputSchema: { type: 'object', properties: {} },
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
          content: [{ type: 'text', text: `Error calling Gradescope: ${err.message}` }],
          isError: true,
        };
      }
      console.error(
        `[gradescope-bridge] Upstream session lost (${err.message}); reconnecting and retrying once.`
      );
      try {
        await connectUpstream();
        const t = await remoteClient.listTools();
        remoteTools = t.tools || [];
        return await callOnce();
      } catch (retryErr) {
        return {
          content: [{ type: 'text', text: `Error calling Gradescope after reconnect: ${retryErr.message}` }],
          isError: true,
        };
      }
    }
  });

  await localServer.connect(new StdioServerTransport());
  console.error('[gradescope-bridge] Stdio server running. Ready for tool calls.');
}

init().catch((err) => {
  console.error(`[gradescope-bridge] Fatal: ${err.message}`);
  process.exit(1);
});
