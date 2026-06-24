"""
Neo4j-backed graph helpers for production ingestion and bounded queries.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _clean_identifier(value: str, kind: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe Neo4j {kind}: {value!r}")
    return value


class Neo4jGraphService:
    def __init__(self) -> None:
        self._driver = None

    async def _get_driver(self):
        settings = get_settings()
        if not settings.use_neo4j:
            raise RuntimeError("Neo4j graph backend is disabled in this deployment.")

        try:
            from neo4j import AsyncGraphDatabase
        except Exception as exc:  # pragma: no cover - dependency/environment specific
            raise RuntimeError("Neo4j Python driver is unavailable.") from exc

        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
        return self._driver

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def _run(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        driver = await self._get_driver()
        async with driver.session() as session:
            result = await session.run(query, parameters or {})
            return [record.data() async for record in result]

    async def _write(self, query: str, parameters: dict[str, Any] | None = None) -> dict[str, int]:
        driver = await self._get_driver()
        async with driver.session() as session:
            result = await session.run(query, parameters or {})
            summary = await result.consume()
        counters = summary.counters
        return {
            "nodes_created": counters.nodes_created,
            "nodes_deleted": counters.nodes_deleted,
            "relationships_created": counters.relationships_created,
            "relationships_deleted": counters.relationships_deleted,
            "properties_set": counters.properties_set,
        }

    async def upsert_node(self, node_id: str, label: str, properties: dict[str, Any] | None = None) -> None:
        safe_label = _clean_identifier(label, "label")
        payload = dict(properties or {})
        payload.setdefault("node_id", node_id)
        payload.setdefault("label", safe_label)
        query = f"""
        MERGE (n:ClinicalEntity:`{safe_label}` {{node_id: $node_id}})
        ON CREATE SET n.created_at = datetime()
        SET n.updated_at = datetime(),
            n += $properties,
            n.label = $label,
            n.node_id = $node_id
        """
        await self._write(
            query,
            {"node_id": node_id, "label": safe_label, "properties": payload},
        )

    async def upsert_edge(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        safe_relationship = _clean_identifier(relationship_type, "relationship type")
        edge_properties = dict(properties or {})
        edge_key = edge_properties.get("edge_key") or f"{safe_relationship}:{source_id}:{target_id}"
        edge_properties["edge_key"] = edge_key

        query = f"""
        MATCH (source:ClinicalEntity {{node_id: $source_id}})
        MATCH (target:ClinicalEntity {{node_id: $target_id}})
        MERGE (source)-[r:`{safe_relationship}` {{edge_key: $edge_key}}]->(target)
        ON CREATE SET r.created_at = datetime()
        SET r.updated_at = datetime(),
            r += $properties,
            r.start_date = $start_date,
            r.end_date = $end_date
        """
        await self._write(
            query,
            {
                "source_id": source_id,
                "target_id": target_id,
                "edge_key": edge_key,
                "properties": edge_properties,
                "start_date": start_date,
                "end_date": end_date,
            },
        )

    async def delete_source_artifacts(self, source_type: str, source_id: str) -> int:
        rel_result = await self._write(
            """
            MATCH ()-[r]->()
            WHERE r.source_type = $source_type AND r.source_id = $source_id
            DELETE r
            """,
            {"source_type": source_type, "source_id": source_id},
        )
        node_result = await self._write(
            """
            MATCH (n:ClinicalEntity)
            WHERE n.source_type = $source_type AND n.source_id = $source_id
            DETACH DELETE n
            """,
            {"source_type": source_type, "source_id": source_id},
        )
        return (
            rel_result["relationships_deleted"]
            + node_result["relationships_deleted"]
            + node_result["nodes_deleted"]
        )

    async def export_graph(
        self,
        *,
        limit: int,
        tenant_id: str | None = None,
        patient_id: str | None = None,
    ) -> dict[str, Any]:
        rows = await self._run(
            """
            MATCH (n:ClinicalEntity)
            WHERE ($tenant_id IS NULL OR coalesce(n.tenant_id, '') = $tenant_id)
              AND ($patient_id IS NULL OR coalesce(n.patient_id, '') = $patient_id OR coalesce(n.patient_id, '') = '')
            WITH n
            ORDER BY coalesce(n.updated_at, n.created_at) DESC
            LIMIT $limit
            WITH collect(n) AS nodes
            UNWIND nodes AS node
            OPTIONAL MATCH (node)-[r]->(other:ClinicalEntity)
            WHERE other IN nodes
            WITH nodes, collect(DISTINCT {
                source: startNode(r).node_id,
                target: endNode(r).node_id,
                type: type(r),
                properties: properties(r)
            }) AS raw_links
            RETURN [n IN nodes | {
                id: n.node_id,
                label: coalesce(n.label, head(labels(n))),
                name: coalesce(n.name, n.canonical_label, n.node_id),
                properties: properties(n)
            }] AS nodes,
            [link IN raw_links WHERE link.source IS NOT NULL] AS links
            """,
            {
                "limit": limit,
                "tenant_id": tenant_id,
                "patient_id": patient_id,
            },
        )
        if not rows:
            return {"nodes": [], "links": [], "source": "neo4j"}
        payload = rows[0]
        return {
            "nodes": payload.get("nodes", []),
            "links": payload.get("links", []),
            "source": "neo4j",
        }

    async def query_temporal_state(
        self,
        entity: str,
        target_date: str,
        *,
        tenant_id: str | None = None,
        patient_id: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        entity_key = entity.strip().lower()
        rows = await self._run(
            """
            MATCH (n:ClinicalEntity)
            WHERE ($tenant_id IS NULL OR coalesce(n.tenant_id, '') = $tenant_id)
              AND (
                toLower(n.node_id) = $entity
                OR toLower(coalesce(n.name, '')) = $entity
                OR toLower(coalesce(n.canonical_label, '')) = $entity
                OR toLower(coalesce(n.patient_id, '')) = $entity
              )
            RETURN {
                id: n.node_id,
                label: coalesce(n.label, head(labels(n))),
                name: coalesce(n.name, n.canonical_label, n.node_id)
            } AS node
            LIMIT 1
            """,
            {"entity": entity_key, "tenant_id": tenant_id},
        )
        if not rows:
            return {"error": f"Entity '{entity}' not found in the knowledge graph."}

        node = rows[0]["node"]
        rel_rows = await self._run(
            """
            MATCH (n:ClinicalEntity {node_id: $node_id})-[r]-(other:ClinicalEntity)
            WHERE ($patient_id IS NULL OR coalesce(r.patient_id, other.patient_id, n.patient_id, '') = $patient_id)
              AND (r.start_date IS NULL OR r.start_date <= $target_date)
              AND (r.end_date IS NULL OR r.end_date >= $target_date)
            RETURN {
                relationship: CASE
                    WHEN startNode(r).node_id = n.node_id THEN type(r)
                    ELSE 'IS_' + type(r) + '_OF'
                END,
                target_entity: CASE
                    WHEN startNode(r).node_id = n.node_id THEN other.node_id
                    ELSE startNode(r).node_id
                END,
                target_label: CASE
                    WHEN startNode(r).node_id = n.node_id THEN coalesce(other.label, head(labels(other)))
                    ELSE coalesce(startNode(r).label, head(labels(startNode(r))))
                END,
                start_date: r.start_date,
                end_date: r.end_date,
                properties: properties(r)
            } AS relationship
            LIMIT $limit
            """,
            {
                "node_id": node["id"],
                "target_date": target_date,
                "patient_id": patient_id,
                "limit": limit,
            },
        )
        relationships = [row["relationship"] for row in rel_rows]
        return {
            "entity": node["id"],
            "entity_label": node["label"],
            "target_date": target_date,
            "active_relationships": relationships,
            "total_active": len(relationships),
            "source": "neo4j",
        }

    async def safe_text_query(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
        patient_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        effective_limit = limit or settings.graph_query_default_limit
        effective_limit = max(1, min(effective_limit, settings.graph_query_max_limit))

        target_date_match = _DATE_PATTERN.search(query or "")
        target_date = target_date_match.group(0) if target_date_match else None
        search_term = (query or "").strip().lower()
        if target_date:
            search_term = search_term.replace(target_date.lower(), "").strip(" ,.?")

        if not search_term:
            return {"error": "Provide a graph entity or question containing a graph entity."}

        rows = await self._run(
            """
            MATCH (n:ClinicalEntity)
            WHERE ($tenant_id IS NULL OR coalesce(n.tenant_id, '') = $tenant_id)
              AND ($patient_id IS NULL OR coalesce(n.patient_id, '') = $patient_id OR coalesce(n.patient_id, '') = '')
              AND (
                toLower(n.node_id) CONTAINS $query
                OR toLower(coalesce(n.name, '')) CONTAINS $query
                OR toLower(coalesce(n.canonical_label, '')) CONTAINS $query
              )
            RETURN {
                id: n.node_id,
                label: coalesce(n.label, head(labels(n))),
                name: coalesce(n.name, n.canonical_label, n.node_id)
            } AS node
            LIMIT $limit
            """,
            {
                "tenant_id": tenant_id,
                "patient_id": patient_id,
                "query": search_term,
                "limit": min(effective_limit, 5),
            },
        )
        matches = [row["node"] for row in rows]
        if not matches:
            return {"error": f"No graph entities matched '{query}'."}

        if len(matches) == 1:
            return await self.query_temporal_state(
                matches[0]["id"],
                target_date or "9999-12-31",
                tenant_id=tenant_id,
                patient_id=patient_id,
                limit=effective_limit,
            )

        return {
            "answer": "Multiple graph entities matched the query. Narrow the term or pass a patient/date scope.",
            "matches": matches,
            "source": "neo4j",
        }

    async def get_stats(self) -> dict[str, Any]:
        rows = await self._run(
            """
            MATCH (n:ClinicalEntity)
            OPTIONAL MATCH ()-[r]->()
            RETURN count(DISTINCT n) AS nodes, count(DISTINCT r) AS edges
            """
        )
        if not rows:
            return {"nodes": 0, "edges": 0, "status": "neo4j", "source": "neo4j"}
        return {
            "nodes": rows[0]["nodes"],
            "edges": rows[0]["edges"],
            "status": "neo4j",
            "source": "neo4j",
        }


neo4j_graph_service = Neo4jGraphService()


async def query_neo4j_graph_async(
    query: str,
    *,
    tenant_id: str | None = None,
    patient_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Execute a bounded natural-language lookup against the Neo4j graph."""
    import time
    from app.core.metrics import observe_graph_query
    started = time.perf_counter()
    try:
        try:
            return await neo4j_graph_service.safe_text_query(
                query,
                tenant_id=tenant_id,
                patient_id=patient_id,
                limit=limit,
            )
        except Exception as exc:
            logger.error("Error querying Neo4j Clinical Graph: %s", exc)
            return {"error": str(exc)}
    finally:
        observe_graph_query((time.perf_counter() - started) * 1000)


async def check_neo4j_health() -> dict:
    """Check raw Neo4j connectivity when the deployment enables it."""
    settings = get_settings()
    if not settings.use_neo4j:
        return {"status": "disabled"}

    try:
        driver = await neo4j_graph_service._get_driver()
    except Exception as exc:  # pragma: no cover - environment specific
        return {"status": "unhealthy", "error": str(exc)}

    try:
        async with driver.session() as session:
            result = await session.run("RETURN 1 AS ok")
            await result.single()
        return {"status": "healthy"}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}
