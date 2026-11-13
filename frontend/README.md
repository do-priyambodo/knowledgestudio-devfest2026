# Frontend (`knowledgestudio-devfest2026`)

Next.js 15 App Router, React 19, and Tailwind CSS v4 single-view comparison interface ([DESIGN.md](../DESIGN.md)).

## How It Works

Races `agent_1_without_kc` and `agent_2_with_kc` concurrently over Server-Sent Events (`/api/arena/stream` -> `/api/v1/agent/arena-stream`), displaying the two Ringgit (`MYR`) answers and the variance ribbon side-by-side while keeping the executed SQL queries, MCP tool trace, and Python agent source code inside collapsible inspection drawers.

## Local Development

```bash
npm ci
npm run typecheck
npm run build
BACKEND_API_URL="http://127.0.0.1:8080" npm run dev
```
