#!/usr/bin/env node
/**
 * MCP stdio-to-HTTP bridge for the personal Canvas LMS MCP server.
 *
 * Mirrors mcp_servers/edstem-bridge/bridge.mjs — the host runs the python
 * Canvas MCP server in HTTP mode (port 8766 by default), the agent
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

const CANVAS_HTTP_URL =
  process.env.CANVAS_HTTP_URL || 'http://host.docker.internal:8766/mcp';

const TOOL_CALL_TIMEOUT_MS =
  Number(process.env.CANVAS_TOOL_TIMEOUT_MS) || 30_000;

const remoteTransport = new StreamableHTTPClientTransport(new URL(CANVAS_HTTP_URL));
const remoteClient = new Client({ name: 'canvas-bridge', version: '1.0.0' });

const localServer = new Server(
  { name: 'canvas', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

let remoteTools = [];

async function init() {
  try {
    await remoteClient.connect(remoteTransport);
    const t = await remoteClient.listTools();
    remoteTools = t.tools || [];
    console.error(`[canvas-bridge] Connected. ${remoteTools.length} tools available.`);
  } catch (err) {
    console.error(
      `[canvas-bridge] Failed to connect to Canvas MCP at ${CANVAS_HTTP_URL}: ${err.message}`
    );
    remoteTools = [
      {
        name: 'list_canvas_courses',
        description:
          'List Canvas courses (OFFLINE — host Canvas MCP unreachable; ask staff to start it or DM /canvas-key <token> after configuring CANVAS_BASE_URL).',
        inputSchema: { type: 'object', properties: {} },
      },
    ];
  }

  localServer.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: remoteTools,
  }));

  localServer.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    try {
      return await remoteClient.callTool(
        { name, arguments: args },
        undefined,
        { timeout: TOOL_CALL_TIMEOUT_MS }
      );
    } catch (err) {
      return {
        content: [{ type: 'text', text: `Error calling Canvas: ${err.message}` }],
        isError: true,
      };
    }
  });

  await localServer.connect(new StdioServerTransport());
  console.error('[canvas-bridge] Stdio server running. Ready for tool calls.');
}

init().catch((err) => {
  console.error(`[canvas-bridge] Fatal: ${err.message}`);
  process.exit(1);
});
