# NanoClaw Student Assistant

A personal AI agent system for university students, built on [NanoClaw](https://github.com/qwibitai/nanoclaw) and integrated with the [ChatCSE](https://chatcse.vercel.app) Virtual TA.

Each student gets their own NanoClaw agent instance, accessible via Discord DM, that serves as a unified interface to all their academic tools and resources.

## Architecture

```
Student (Discord DM)
       |
       v
NanoClaw Agent (per-student VM)
  |-- Virtual TA (shared, via MCP)     → Course content Q&A, lecture slides, admin questions
  |-- Canvas LMS (via Composio)        → Grades, assignments, calendar
  |-- Google Workspace (via Composio)  → Docs, Calendar, Drive, Gmail
  |-- Notion (via Composio)            → Notes, databases
  |-- EdStem (custom MCP server)       → Discussion threads, announcements
  |-- Gradescope (via Canvas LTI)      → Grades (best-effort)
       |
       v
Shared Virtual TA (one per course)
  FastAPI + fastapi-mcp endpoint
```

## Repository Structure

```
├── mcp_servers/          # Custom MCP servers (Python)
│   ├── edstem/           # EdStem personal MCP server
│   └── gradescope/       # Gradescope MCP server (best-effort)
├── config/               # NanoClaw and mcporter configuration templates
├── provisioning/         # GCP VM provisioning and setup scripts
├── tests/                # Test suite
└── docs/                 # Documentation
```

## Prerequisites

- Python 3.13+
- Google Cloud SDK (`gcloud`)
- An Anthropic API key
- A Discord bot token (per student)

## Quick Start

See [docs/onboarding.md](docs/onboarding.md) for the full setup guide.

## Related Repositories

- **[ChatCSE](https://chatcse.vercel.app)** — Shared Virtual TA backend (FastAPI + RAG pipelines)
- **[NanoClaw](https://github.com/qwibitai/nanoclaw)** — Personal AI agent framework
