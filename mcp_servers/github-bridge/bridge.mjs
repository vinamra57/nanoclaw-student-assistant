#!/usr/bin/env node
/**
 * MCP stdio-to-HTTP bridge for the personal GitHub MCP server.
 *
 * Mirrors edstem-bridge / canvas-bridge / gradescope-bridge — the host runs
 * mcp_servers/github/server.py as a streamable-HTTP MCP, the agent container
 * sees it through this stdio shim.
 *
 * Usage (inside the agent container):
 *   GITHUB_HTTP_URL=http://host.docker.internal:8768/mcp node bridge.mjs
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

const UPSTREAM_URL = process.env.GITHUB_HTTP_URL || 'http://host.docker.internal:8768/mcp';

let upstreamClient = null;
async function connectUpstream() {
  if (upstreamClient) return upstreamClient;
  const transport = new StreamableHTTPClientTransport(new URL(UPSTREAM_URL));
  const client = new Client(
    { name: 'github-bridge', version: '1.0.0' },
    { capabilities: { tools: {} } },
  );
  await client.connect(transport);
  upstreamClient = client;
  return client;
}

async function disconnectAndReconnect() {
  if (upstreamClient) {
    try { await upstreamClient.close(); } catch { /* ignore */ }
    upstreamClient = null;
  }
  return connectUpstream();
}

function looksLikeDisconnect(err) {
  const msg = String(err?.message || err || '');
  return (
    msg.includes('session') ||
    msg.includes('closed') ||
    msg.includes('404') ||
    msg.includes('ECONNRESET') ||
    msg.includes('ECONNREFUSED')
  );
}

const server = new Server(
  { name: 'github', version: '1.0.0' },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  try {
    const client = await connectUpstream();
    return await client.listTools();
  } catch (err) {
    if (looksLikeDisconnect(err)) {
      const client = await disconnectAndReconnect();
      return await client.listTools();
    }
    throw err;
  }
});

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  try {
    const client = await connectUpstream();
    return await client.callTool({ name: req.params.name, arguments: req.params.arguments });
  } catch (err) {
    if (looksLikeDisconnect(err)) {
      const client = await disconnectAndReconnect();
      return await client.callTool({ name: req.params.name, arguments: req.params.arguments });
    }
    throw err;
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
