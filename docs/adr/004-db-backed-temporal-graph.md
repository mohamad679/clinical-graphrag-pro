# ADR-004: Database-Backed Temporal Graph

**Date:** 2026-04-01  
**Status:** Accepted  
**Deciders:** Solo developer  

## Context
The repository contains evidence of an earlier file-backed graph path. `docs/task.md` still references local-disk graph persistence, and `backend/scripts/migrate_graph.py` reads `backend/data/temporal_graph.json` using a NetworkX-style node-link payload before migrating that data onward. The current runtime graph service is different: `backend/app/services/graph.py` declares `GRAPH_DATA_FILE = "database://graph_nodes_edges"` and persists graph state through SQLAlchemy models instead of a disk file.

The durable graph schema now lives in `backend/app/models/persistence.py` as `GraphNode` and `GraphEdge`. The service layer is `ClinicalGraphService` in `backend/app/services/graph.py`, which writes through `async_session_factory()` and optionally mirrors data to Neo4j when `settings.use_neo4j` is enabled. The ontology surface is explicit in `FORMAL_GRAPH_SCHEMA`.

## Decision
Use PostgreSQL-backed graph persistence as the system of record for the temporal graph. `ClinicalGraphService` persists nodes and edges through `GraphNodeSpec`, `GraphEdgeSpec`, `_upsert_node_db()`, `_upsert_edge_db()`, and `_persist_subgraph()`. Neo4j remains an optional secondary backend for graph-native query patterns, not the primary persistence layer.

The accepted graph contract is:
- Durable graph state in `graph_nodes` and `graph_edges`.
- Ontology labels and relationship types defined in `FORMAL_GRAPH_SCHEMA`.
- Optional dual-write to Neo4j when `settings.use_neo4j` is enabled.

## Consequences
**Positive:** The graph now participates in the same transactional persistence layer as the rest of the backend. `ClinicalGraphService` can handle concurrent async writes without depending on a shared JSON file, and graph state survives process restarts as long as the database persists. Temporal edge fields such as `start_date` and `end_date` are first-class columns on `GraphEdge`.  
**Negative:** General graph algorithms are less direct in the relational path than they would be in a native in-memory or graph-native structure. The service has to implement bounded query behavior and explicit persistence logic instead of relying on a single file snapshot.  
**Risks:** `GraphEdge.start_date` and `GraphEdge.end_date` are stored as strings, which limits temporal indexing and validation compared with typed timestamp columns. When `settings.use_neo4j` is enabled, the service becomes a dual-write system and can drift if the relational write succeeds but the Neo4j sync fails.

## Alternatives Considered
| Alternative | Why Rejected |
|-------------|--------------|
| File-backed NetworkX / node-link JSON persistence | The repository still contains migration tooling for that format in `backend/scripts/migrate_graph.py`, but the runtime implementation has already moved to database-backed persistence. Keeping the file as the source of truth would duplicate state and complicate concurrent access. |
| Neo4j-only persistence | Neo4j support exists, but the current service is explicitly written to keep the database path authoritative and make Neo4j optional. |
| Pure in-memory graph state | The current implementation requires durable graph state across requests and restarts. In-memory-only storage would not satisfy that requirement. |
