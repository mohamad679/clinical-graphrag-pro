# ADR-004: Vanilla JS Web Components

## Status
Accepted

## Context

The frontend needed to stay easy to inspect, easy to serve statically, and free from a Node-based build pipeline. At the same time, the UI still had to support routed views, streaming chat updates, and stateful feature panels.

## Decision

We use vanilla JavaScript Web Components in `frontend/public/js/components/` and serve the frontend as static assets behind nginx. We avoid a React or Vue build toolchain in the mainline application.

## Alternatives Considered

- **React**: rejected because it would add a build step and more framework overhead than this frontend requires.
- **Vue**: rejected for the same reason; the project benefits more from a transparent static asset pipeline than from framework abstractions.

## Consequences

**Positive:**
- No frontend build step is required to inspect or serve the UI.
- The browser layer stays close to platform APIs such as custom elements, fetch, and SSE.
- The frontend remains lightweight and deployment-friendly.

**Negative:**
- State management and component ergonomics are more manual.
- There are fewer off-the-shelf patterns for complex interactions.
- Some UI logic that frameworks would structure automatically has to be organized by hand.

## Date
2026-03-24
