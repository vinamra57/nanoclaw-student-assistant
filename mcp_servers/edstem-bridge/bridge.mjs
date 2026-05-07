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

const remoteTransport = new StreamableHTTPClientTransport(new URL(EDSTEM_HTTP_URL));
const remoteClient = new Client({ name: 'edstem-bridge', version: '1.0.0' });

const localServer = new Server(
  { name: 'edstem', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

let remoteTools = [];

async function init() {
  try {
    await remoteClient.connect(remoteTransport);
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
          'Search Ed Discussion (OFFLINE — host EdStem MCP unreachable; ask the user to set ED_API_TOKEN/ED_COURSE_ID and restart the host server).',
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
    try {
      const result = await remoteClient.callTool(
        { name, arguments: args },
        undefined,
        { timeout: TOOL_CALL_TIMEOUT_MS }
      );
      return result;
    } catch (err) {
      return {
        content: [{ type: 'text', text: `Error calling EdStem: ${err.message}` }],
        isError: true,
      };
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
