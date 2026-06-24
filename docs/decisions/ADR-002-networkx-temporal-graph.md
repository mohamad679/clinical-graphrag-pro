# ADR-002: Temporal Graph Runtime

## Status
Accepted

## Context

Early repository planning referenced a NetworkX-based temporal graph, while the deployed stack also carries optional Neo4j support. The runtime system needed a default persistence path that works in the same operational boundary as the rest of the FastAPI application.

## Decision

We keep the temporal graph in relational storage through `GraphNode` and `GraphEdge` models in `backend/app/models/persistence.py`, and we treat Neo4j as an optional backend in `backend/app/services/neo4j_graph.py`. We do not use a NetworkX object graph as the runtime system of record in the current codebase.

## Alternatives Considered

- **Pure NetworkX runtime**: rejected because an in-memory or file-backed graph is awkward for concurrent API access and durable persistence.
- **Neo4j-only persistence**: rejected because it would make a separate graph database mandatory for every local or portfolio deployment.

## Consequences

**Positive:**
- Default deployments stay self-contained inside the PostgreSQL-backed application stack.
- Temporal edges are easy to persist, scope, and expose through API endpoints.
- Neo4j remains available for graph-native queries without becoming mandatory.

**Negative:**
- Relational storage is less natural for graph traversal than a dedicated graph engine.
- The repository still contains historical references to NetworkX, which can confuse readers unless documented clearly.
- Dual-backend support increases conceptual surface area.

## Date
2026-03-24
