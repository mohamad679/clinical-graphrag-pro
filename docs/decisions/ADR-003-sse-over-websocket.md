# ADR-003: SSE Over WebSocket

## Status
Accepted

## Context

The main chat interaction is a server-to-browser stream of reasoning steps, sources, token chunks, traces, and completion events. The frontend does not need a fully bidirectional real-time protocol for the primary chat path.

## Decision

We use Server-Sent Events as the main streaming transport in `backend/app/api/chat.py` and `frontend/public/js/api.js`. A lightweight WebSocket endpoint still exists, but it is not the primary browser path.

## Alternatives Considered

- **WebSocket as the only transport**: rejected because it adds more operational complexity than the main one-way streaming use case needs.
- **Polling**: rejected because it would degrade latency and complicate incremental rendering.

## Consequences

**Positive:**
- Streaming works cleanly through nginx with minimal protocol complexity.
- The browser client can parse a simple event stream and render partial state incrementally.
- The transport matches the one-way nature of grounded answer delivery.

**Negative:**
- SSE is unidirectional, so it is not a complete replacement for richer real-time protocols.
- The current implementation streams finalized answer chunks rather than raw provider tokens.
- Browser reconnection behavior must be handled at the application level if needed later.

## Date
2026-03-24
