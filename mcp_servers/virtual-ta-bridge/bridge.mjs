#!/usr/bin/env node
/**
 * MCP stdio-to-HTTP bridge for the Virtual TA.
 *
 * NanoClaw's agent containers only support stdio MCP servers. This script
 * acts as a local stdio MCP server that forwards tool calls to the remote
 * Virtual TA's Streamable HTTP MCP endpoint.
 *
 * Usage:
 *   VIRTUAL_TA_URL=https://backend-production-45b0.up.railway.app node bridge.mjs
 *
 * The bridge exposes the same tools as the remote server to the agent.
 */

// Bypass OneCLI proxy for the Virtual TA connection — the proxy intercepts
// all HTTP traffic for credential injection, but the Virtual TA is an
// internal service that doesn't need it.
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

const VIRTUAL_TA_URL = process.env.VIRTUAL_TA_URL || 'http://host.docker.internal:8001';
const MCP_ENDPOINT = `${VIRTUAL_TA_URL}/mcp`;

// Per-user agent token. ChatCSE's combined verifier accepts EITHER a Supabase
// JWT or one of these (HS256, signed by the backend). Provisioned per
// container via the admin endpoint; absence is OK in pure-dev mode where
// the MCP falls through to the agent:default user.
const CHATCSE_AGENT_TOKEN = process.env.CHATCSE_AGENT_TOKEN || '';

// Default tool-call ceiling — the orchestrator with modality=SLIDES takes
// 90–120s. The MCP SDK default is 60s; bump to 3 minutes to leave headroom
// without burying real failures.
const TOOL_CALL_TIMEOUT_MS = Number(process.env.VIRTUAL_TA_TOOL_TIMEOUT_MS) || 180_000;

const remoteTransport = new StreamableHTTPClientTransport(new URL(MCP_ENDPOINT), {
  requestInit: CHATCSE_AGENT_TOKEN
    ? { headers: { Authorization: `Bearer ${CHATCSE_AGENT_TOKEN}` } }
    : undefined,
});
const remoteClient = new Client({ name: 'virtual-ta-bridge', version: '1.0.0' });

// Local server — exposes tools via stdio to the agent container
const localServer = new Server(
  { name: 'virtual-ta', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

let remoteTools = [];

async function init() {
  // Connect to remote Virtual TA
  try {
    await remoteClient.connect(remoteTransport);
    const toolsResult = await remoteClient.listTools();
    remoteTools = toolsResult.tools || [];
    console.error(`[bridge] Connected to Virtual TA. ${remoteTools.length} tools available.`);
  } catch (err) {
    console.error(`[bridge] Failed to connect to Virtual TA at ${MCP_ENDPOINT}: ${err.message}`);
    console.error(`[bridge] Will expose fallback tools.`);
    // Provide a single fallback tool
    remoteTools = [{
      name: 'ask_question',
      description: 'Ask the Virtual TA a question (OFFLINE - Virtual TA unreachable)',
      inputSchema: {
        type: 'object',
        properties: {
          question: { type: 'string', description: 'The question to ask' }
        },
        required: ['question']
      }
    }];
  }

  // Register tools/list handler
  localServer.setRequestHandler(ListToolsRequestSchema, async () => {
    return { tools: remoteTools };
  });

  // Register tools/call handler — proxy to remote
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
        content: [{ type: 'text', text: `Error calling Virtual TA: ${err.message}` }],
        isError: true,
      };
    }
  });

  // Start local stdio server
  const transport = new StdioServerTransport();
  await localServer.connect(transport);
  console.error('[bridge] Stdio server running. Ready for tool calls.');
}

init().catch((err) => {
  console.error(`[bridge] Fatal: ${err.message}`);
  process.exit(1);
});
