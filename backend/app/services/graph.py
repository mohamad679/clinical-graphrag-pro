"""
Clinical knowledge graph service with durable DB storage and optional Neo4j sync.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.persistence import GraphEdge, GraphNode
from app.services.neo4j_graph import neo4j_graph_service

logger = logging.getLogger(__name__)
GRAPH_DATA_FILE = "database://graph_nodes_edges"
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")

FORMAL_GRAPH_SCHEMA = {
    "node_labels": [
        "Patient",
        "Encounter",
        "Document",
        "Chunk",
        "Condition",
        "Medication",
        "LabResult",
        "ImagingStudy",
        "Finding",
        "Procedure",
        "Observation",
        "Lab",
        "Symptom",
    ],
    "relationship_types": [
        "HAS_DOCUMENT",
        "HAS_CHUNK",
        "MENTIONS_CONDITION",
        "MENTIONS_MEDICATION",
        "HAS_LAB_RESULT",
        "HAS_FINDING",
        "OCCURRED_DURING",
        "EVIDENCED_BY",
        "RELATED_TO",
        "MENTIONED_IN",
        "HAS_CONDITION",
        "HAS_LAB",
        "TOOK_MEDICATION",
        "LAB_RESULT",
        "OCCURRED_AT",
    ],
}

SEMANTIC_TYPE_TO_LABEL = {
    "condition": "Condition",
    "disease": "Condition",
    "disorder": "Condition",
    "diagnosis": "Condition",
    "symptom": "Finding",
    "sign": "Finding",
    "drug": "Medication",
    "medication": "Medication",
    "therapy": "Medication",
    "lab": "LabResult",
    "laboratory": "LabResult",
    "test": "LabResult",
    "finding": "Finding",
    "procedure": "Procedure",
    "imagingstudy": "ImagingStudy",
    "imaging": "ImagingStudy",
    "observation": "Observation",
}
IMAGING_HINTS = ("ct", "mri", "ultrasound", "x-ray", "xray", "echocardiography", "echo", "pet")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slug(value: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", value.strip().lower()).strip("-")
    return normalized or "unknown"


def _iso_timestamp(value: Any) -> str | None:
    dt = parse_date_robust(value)
    if dt:
        return dt.isoformat()
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    text = str(value).strip()
    return text or None



def parse_date_robust(date_val: Any) -> datetime | None:
    if date_val is None:
        return None
    if isinstance(date_val, datetime):
        if date_val.tzinfo is None:
            return date_val.replace(tzinfo=timezone.utc)
        return date_val.astimezone(timezone.utc)
    text = str(date_val).strip()
    if not text:
        return None
    cleaned = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    match_year = re.match(r"^(\d{4})$", text)
    if match_year:
        try:
            return datetime(int(match_year.group(1)), 1, 1, tzinfo=timezone.utc)
        except ValueError:
            pass
    match = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})", text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def classify_temporal_status(
    start_date: str | None,
    end_date: str | None,
    target_date_str: str,
) -> tuple[str, str]:
    target_dt = parse_date_robust(target_date_str)
    if not target_dt:
        return "unknown", "Low"
    start_dt = parse_date_robust(start_date)
    end_dt = parse_date_robust(end_date)
    if not start_dt:
        return "unknown", "Low"
    confidence = "High" if end_dt else "Medium"
    if target_dt < start_dt:
        return "future", confidence
    if end_dt and target_dt > end_dt:
        return "resolved", confidence
    return "active", confidence


def _tenant_scope(tenant_id: str | None) -> str:
    return (tenant_id or "public").strip() or "public"


def _scope_matches(properties: dict[str, Any] | None, *, tenant_id: str | None, patient_id: str | None) -> bool:
    props = properties or {}
    if tenant_id is not None and props.get("tenant_id") != tenant_id:
        return False
    if patient_id is not None and props.get("patient_id") != patient_id:
        return False
    return True


def _label_for_entity(entity: dict[str, Any]) -> str:
    semantic_type = str(entity.get("semantic_type") or "").strip().lower().replace(" ", "")
    if semantic_type in SEMANTIC_TYPE_TO_LABEL:
        return SEMANTIC_TYPE_TO_LABEL[semantic_type]

    semantic_words = str(entity.get("semantic_type") or "").strip().lower()
    for key, label in SEMANTIC_TYPE_TO_LABEL.items():
        if key in semantic_words:
            return label

    canonical = str(entity.get("canonical_label") or entity.get("surface_form") or "").strip().lower()
    if any(hint in canonical for hint in IMAGING_HINTS):
        return "ImagingStudy"
    return "Finding"


def _entity_node_id(tenant_id: str, entity: dict[str, Any]) -> str:
    label = _label_for_entity(entity).lower()
    concept_id = str(entity.get("concept_id") or "").strip()
    base = concept_id or _slug(str(entity.get("canonical_label") or entity.get("surface_form") or "entity"))
    return f"tenant:{tenant_id}:{label}:{base}"


@dataclass(slots=True)
class GraphNodeSpec:
    node_id: str
    label: str
    properties: dict[str, Any]


@dataclass(slots=True)
class GraphEdgeSpec:
    source_id: str
    target_id: str
    relationship_type: str
    start_date: str | None
    end_date: str | None
    properties: dict[str, Any]

    @property
    def edge_key(self) -> str:
        value = self.properties.get("edge_key")
        return str(value) if value else f"{self.relationship_type}:{self.source_id}:{self.target_id}"


@dataclass(slots=True)
class GraphEvidenceFact:
    """One independently citable graph fact with source provenance."""

    fact_id: str
    fact_type: str
    normalized_subject: str
    normalized_predicate: str
    normalized_object: str
    source_document_id: str | None
    source_chunk_id: str | None
    tenant_id: str | None
    patient_id: str | None
    extracted_at: str | None
    extractor_version: str
    extraction_confidence: Any
    verification_status: str
    start_date: str | None = None
    end_date: str | None = None
    temporal_status: str | None = None
    value: Any = None
    unit: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "graph_fact": {
                "fact_id": self.fact_id,
                "fact_type": self.fact_type,
                "normalized_subject": self.normalized_subject,
                "normalized_predicate": self.normalized_predicate,
                "normalized_object": self.normalized_object,
                "source_document_id": self.source_document_id,
                "source_chunk_id": self.source_chunk_id,
                "tenant_id": self.tenant_id,
                "patient_id": self.patient_id,
                "extracted_at": self.extracted_at,
                "extractor_version": self.extractor_version,
                "extraction_confidence": self.extraction_confidence,
                "verification_status": self.verification_status,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "temporal_status": self.temporal_status,
                "value": self.value,
                "unit": self.unit,
            },
            "tenant_id": self.tenant_id,
            "patient_id": self.patient_id,
            "source_document_id": self.source_document_id,
            "source_chunk_id": self.source_chunk_id,
        }

    def to_context_text(self) -> str:
        parts = [
            f"Fact ID: {self.fact_id}",
            f"Type: {self.fact_type}",
            f"Patient ID: {self.patient_id}",
            f"Subject: {self.normalized_subject}",
            f"Predicate: {self.normalized_predicate}",
            f"Object: {self.normalized_object}",
        ]
        if self.value is not None:
            parts.append(f"Value: {self.value}")
        if self.unit:
            parts.append(f"Unit: {self.unit}")
        if self.temporal_status:
            parts.append(f"Status: {self.temporal_status}")
        if self.start_date:
            parts.append(f"Start date: {self.start_date}")
        if self.end_date:
            parts.append(f"End date: {self.end_date}")
        parts.extend(
            [
                f"Tenant ID: {self.tenant_id}",
                f"Source document ID: {self.source_document_id}",
                f"Source chunk ID: {self.source_chunk_id}",
                f"Verification status: {self.verification_status}",
            ]
        )
        return "\n".join(parts)


class ClinicalGraphService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _bounded_limit(self, limit: int | None) -> int:
        if limit is None:
            limit = self.settings.graph_query_default_limit
        return max(1, min(int(limit), self.settings.graph_query_max_limit))

    async def _upsert_node_db(self, session, spec: GraphNodeSpec) -> None:
        node = await session.get(GraphNode, spec.node_id)
        if node is None:
            session.add(
                GraphNode(
                    node_id=spec.node_id,
                    label=spec.label,
                    properties=dict(spec.properties),
                )
            )
            return

        merged_properties = dict(node.properties or {})
        merged_properties.update(spec.properties)
        if not node.label or node.label == "Unknown" or node.label == spec.label:
            node.label = spec.label
        node.properties = merged_properties

    async def _upsert_edge_db(self, session, spec: GraphEdgeSpec) -> None:
        result = await session.execute(
            select(GraphEdge).where(
                GraphEdge.source_id == spec.source_id,
                GraphEdge.target_id == spec.target_id,
                GraphEdge.relationship_type == spec.relationship_type,
            )
        )
        existing = None
        for candidate in result.scalars().all():
            properties = candidate.properties or {}
            if properties.get("edge_key") == spec.edge_key:
                existing = candidate
                break
            if "edge_key" not in properties and spec.start_date == candidate.start_date and spec.end_date == candidate.end_date:
                existing = candidate
                break

        if existing is None:
            session.add(
                GraphEdge(
                    source_id=spec.source_id,
                    target_id=spec.target_id,
                    relationship_type=spec.relationship_type,
                    start_date=spec.start_date,
                    end_date=spec.end_date,
                    properties=dict(spec.properties),
                )
            )
            return

        merged_properties = dict(existing.properties or {})
        merged_properties.update(spec.properties)
        existing.start_date = spec.start_date
        existing.end_date = spec.end_date
        existing.properties = merged_properties

    async def _persist_subgraph(
        self,
        *,
        nodes: list[GraphNodeSpec],
        edges: list[GraphEdgeSpec],
    ) -> dict[str, int]:
        deduped_nodes: dict[str, GraphNodeSpec] = {node.node_id: node for node in nodes}
        deduped_edges: dict[tuple[str, str, str, str], GraphEdgeSpec] = {
            (edge.source_id, edge.target_id, edge.relationship_type, edge.edge_key): edge
            for edge in edges
        }

        async with async_session_factory() as session:
            for node in deduped_nodes.values():
                await self._upsert_node_db(session, node)
            for edge in deduped_edges.values():
                await self._upsert_edge_db(session, edge)
            await session.commit()
        try:
            from app.core.caching import CacheManager

            await CacheManager.invalidate_prefix_async("cgrag:graph:")
        except Exception:
            logger.warning("Graph cache invalidation failed after graph update")

        if self.settings.use_neo4j:
            for node in deduped_nodes.values():
                await neo4j_graph_service.upsert_node(node.node_id, node.label, node.properties)
            for edge in deduped_edges.values():
                await neo4j_graph_service.upsert_edge(
                    edge.source_id,
                    edge.target_id,
                    edge.relationship_type,
                    start_date=edge.start_date,
                    end_date=edge.end_date,
                    properties=edge.properties,
                )

        return {"nodes": len(deduped_nodes), "edges": len(deduped_edges)}

    async def add_entity(self, node_id: str, label: str, properties: dict | None = None) -> None:
        await self._persist_subgraph(
            nodes=[GraphNodeSpec(node_id=node_id, label=label, properties=dict(properties or {}))],
            edges=[],
        )

    async def add_temporal_relation(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        start_date: str,
        end_date: str | None = None,
        properties: dict | None = None,
    ) -> None:
        source_properties = dict((properties or {}).get("source_properties") or {})
        source_properties.setdefault("name", source_id)
        target_properties = dict((properties or {}).get("target_properties") or {})
        target_properties.setdefault("name", target_id)
        edge_properties = dict(properties or {})
        edge_properties.setdefault("edge_key", f"seed:{relationship_type}:{source_id}:{target_id}:{start_date}:{end_date or ''}")

        def infer_label(node_id: str, default_label: str) -> str:
            parts = node_id.split(":")
            if len(parts) >= 4 and parts[0] == "tenant":
                lbl = parts[2].lower()
                if lbl in SEMANTIC_TYPE_TO_LABEL:
                    return SEMANTIC_TYPE_TO_LABEL[lbl]
                for candidate in ["Patient", "Condition", "Medication", "LabResult", "Observation", "Finding", "Encounter", "Procedure"]:
                    if candidate.lower() == lbl:
                        return candidate
            return default_label

        source_label = source_properties.pop("label", None) or infer_label(source_id, "Patient")
        target_label = target_properties.pop("label", None) or infer_label(target_id, "Finding")

        if properties:
            for k in [
                "tenant_id",
                "patient_id",
                "source_document_id",
                "source_chunk_id",
                "extraction_method",
                "confidence",
            ]:
                if k in properties:
                    if k not in source_properties:
                        source_properties[k] = properties[k]
                    if k not in target_properties:
                        target_properties[k] = properties[k]

        if "start_date" not in target_properties:
            target_properties["start_date"] = start_date
        if end_date and "end_date" not in target_properties:
            target_properties["end_date"] = end_date

        await self._persist_subgraph(
            nodes=[
                GraphNodeSpec(node_id=source_id, label=source_label, properties=source_properties),
                GraphNodeSpec(node_id=target_id, label=target_label, properties=target_properties),
            ],
            edges=[
                GraphEdgeSpec(
                    source_id=source_id,
                    target_id=target_id,
                    relationship_type=relationship_type,
                    start_date=start_date,
                    end_date=end_date,
                    properties=edge_properties,
                )
            ],
        )


    async def ingest_document_entities(
        self,
        *,
        document_id: str,
        tenant_id: str | None,
        document_name: str,
        entities: list[dict[str, Any]],
        uploaded_at: datetime | str | None = None,
        patient_id: str | None = None,
        chunks: list[dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        tenant = _tenant_scope(tenant_id)
        source_ref = f"document:{document_id}"
        start_date = _iso_timestamp(uploaded_at)
        created_time_iso = datetime.now(timezone.utc).isoformat()

        await self.delete_source_artifacts("document", document_id)

        document_node = GraphNodeSpec(
            node_id=f"document:{document_id}",
            label="Document",
            properties={
                "id": f"document:{document_id}",
                "name": document_name,
                "document_id": document_id,
                "tenant_id": tenant,
                "patient_id": patient_id,
                "source_type": "document",
                "source_id": document_id,
                "source_ref": source_ref,
                "uploaded_at": start_date,
                "created_at": created_time_iso,
            },
        )
        nodes: list[GraphNodeSpec] = [document_node]
        edges: list[GraphEdgeSpec] = []

        if patient_id:
            patient_node_id = f"tenant:{tenant}:patient:{patient_id}"
            nodes.append(
                GraphNodeSpec(
                    node_id=patient_node_id,
                    label="Patient",
                    properties={
                        "id": patient_node_id,
                        "name": patient_id,
                        "patient_id": patient_id,
                        "tenant_id": tenant,
                        "created_at": created_time_iso,
                    },
                )
            )
            edges.append(
                GraphEdgeSpec(
                    source_id=patient_node_id,
                    target_id=document_node.node_id,
                    relationship_type="HAS_DOCUMENT",
                    start_date=start_date,
                    end_date=None,
                    properties={
                        "edge_key": f"patient:{patient_id}:has_doc:{document_id}",
                        "tenant_id": tenant,
                        "patient_id": patient_id,
                        "source_document_id": document_id,
                        "created_at": created_time_iso,
                    },
                )
            )

        if chunks:
            for chunk in chunks:
                chunk_node_id = f"chunk:{chunk['chunk_id']}"
                nodes.append(
                    GraphNodeSpec(
                        node_id=chunk_node_id,
                        label="Chunk",
                        properties={
                            "id": chunk_node_id,
                            "name": chunk["chunk_id"],
                            "chunk_id": chunk["chunk_id"],
                            "document_id": document_id,
                            "patient_id": patient_id,
                            "tenant_id": tenant,
                            "chunk_text": chunk["chunk_text"],
                            "chunk_index": chunk["chunk_index"],
                            "page_start": chunk["page_start"],
                            "page_end": chunk["page_end"],
                            "source_offset_start": chunk["source_offset_start"],
                            "source_offset_end": chunk["source_offset_end"],
                            "created_at": created_time_iso,
                        },
                    )
                )
                edges.append(
                    GraphEdgeSpec(
                        source_id=document_node.node_id,
                        target_id=chunk_node_id,
                        relationship_type="HAS_CHUNK",
                        start_date=start_date,
                        end_date=None,
                        properties={
                            "edge_key": f"doc:{document_id}:has_chunk:{chunk['chunk_id']}",
                            "tenant_id": tenant,
                            "patient_id": patient_id,
                            "source_document_id": document_id,
                            "source_chunk_id": chunk["chunk_id"],
                            "created_at": created_time_iso,
                        },
                    )
                )

        chunk_to_entities: dict[str, list[tuple[str, str]]] = {}

        for entity in entities[:100]:
            if not entity or entity.get("is_ungrounded"):
                continue
            label = _label_for_entity(entity)
            entity_node_id = _entity_node_id(tenant, entity)
            entity_name = str(entity.get("canonical_label") or entity.get("surface_form") or entity_node_id)

            chunk_id = entity.get("source_chunk_id")
            if chunk_id:
                chunk_to_entities.setdefault(chunk_id, []).append((entity_node_id, label))

            nodes.append(
                GraphNodeSpec(
                    node_id=entity_node_id,
                    label=label,
                    properties={
                        "id": entity_node_id,
                        "name": entity_name,
                        "normalized_name": entity_name,
                        "canonical_label": entity.get("canonical_label"),
                        "surface_form": entity.get("surface_form"),
                        "raw_text": entity.get("surface_form"),
                        "ontology": entity.get("ontology"),
                        "concept_id": entity.get("concept_id"),
                        "semantic_type": entity.get("semantic_type"),
                        "tenant_id": tenant,
                        "patient_id": patient_id,
                        "source_document_id": document_id,
                        "source_chunk_id": chunk_id,
                        "extraction_method": entity.get("extraction_method") or "scispacy",
                        "confidence": entity.get("confidence") or "High",
                        "created_at": created_time_iso,
                    },
                )
            )

            # Standard relationship linking from Chunk (or Document) to the Entity
            source_ref_id = f"chunk:{chunk_id}" if chunk_id else document_node.node_id
            rel_type = "RELATED_TO"
            if label == "Condition":
                rel_type = "MENTIONS_CONDITION"
            elif label == "Medication":
                rel_type = "MENTIONS_MEDICATION"
            elif label in ("LabResult", "Lab"):
                rel_type = "HAS_LAB_RESULT"
            elif label in ("Finding", "Symptom"):
                rel_type = "HAS_FINDING"

            edges.append(
                GraphEdgeSpec(
                    source_id=source_ref_id,
                    target_id=entity_node_id,
                    relationship_type=rel_type,
                    start_date=start_date,
                    end_date=None,
                    properties={
                        "edge_key": f"{source_ref_id}:mentions:{entity.get('concept_id') or entity_name}",
                        "tenant_id": tenant,
                        "patient_id": patient_id,
                        "source_document_id": document_id,
                        "source_chunk_id": chunk_id,
                        "extraction_method": entity.get("extraction_method") or "scispacy",
                        "confidence": entity.get("confidence") or "High",
                        "raw_text": entity.get("surface_form"),
                        "created_at": created_time_iso,
                    },
                )
            )

            # Legacy edge for backward compatibility with existing tests
            edges.append(
                GraphEdgeSpec(
                    source_id=entity_node_id,
                    target_id=document_node.node_id,
                    relationship_type="MENTIONED_IN",
                    start_date=start_date,
                    end_date=None,
                    properties={
                        "edge_key": f"{source_ref}:mentioned:{entity.get('concept_id') or entity_name}",
                        "tenant_id": tenant,
                        "patient_id": patient_id,
                        "source_type": "document",
                        "source_id": document_id,
                        "source_ref": source_ref,
                        "document_id": document_id,
                        "concept_id": entity.get("concept_id"),
                        "created_at": created_time_iso,
                    },
                )
            )

        if chunk_to_entities:
            for chunk_id, ent_list in chunk_to_entities.items():
                meds = [node_id for node_id, label in ent_list if label == "Medication"]
                targets = [node_id for node_id, label in ent_list if label in ("Condition", "Finding", "LabResult", "Symptom")]
                for medication_id in meds[:10]:
                    for related_id in targets[:10]:
                        edges.append(
                            GraphEdgeSpec(
                                source_id=medication_id,
                                target_id=related_id,
                                relationship_type="RELATED_TO",
                                start_date=start_date,
                                end_date=None,
                                properties={
                                    "edge_key": f"chunk:{chunk_id}:related:{medication_id}:{related_id}",
                                    "tenant_id": tenant,
                                    "patient_id": patient_id,
                                    "source_document_id": document_id,
                                    "source_chunk_id": chunk_id,
                                    "extraction_method": "co-occurrence",
                                    "confidence": 0.7,
                                    "evidence": f"Co-occurrence in chunk {chunk_id}",
                                    "created_at": created_time_iso,
                                },
                            )
                        )
        else:
            # Fallback document-level co-occurrence
            meds = []
            targets = []
            for entity in entities[:50]:
                if not entity or entity.get("is_ungrounded"):
                    continue
                label = _label_for_entity(entity)
                entity_node_id = _entity_node_id(tenant, entity)
                if label == "Medication":
                    meds.append(entity_node_id)
                elif label in ("Condition", "Symptom", "Finding", "LabResult"):
                    targets.append(entity_node_id)
            for medication_id in meds[:10]:
                for related_id in targets[:10]:
                    edges.append(
                        GraphEdgeSpec(
                            source_id=medication_id,
                            target_id=related_id,
                            relationship_type="RELATED_TO",
                            start_date=start_date,
                            end_date=None,
                            properties={
                                "edge_key": f"{source_ref}:related:{medication_id}:{related_id}",
                                "tenant_id": tenant,
                                "patient_id": patient_id,
                                "source_type": "document",
                                "source_id": document_id,
                                "source_ref": source_ref,
                                "extraction_method": "co-occurrence",
                                "confidence": 0.7,
                                "evidence": f"Co-occurrence in document {document_id}",
                                "created_at": created_time_iso,
                            },
                        )
                    )

        return await self._persist_subgraph(nodes=nodes, edges=edges)

    async def ingest_image_analysis(
        self,
        *,
        image_id: str,
        tenant_id: str | None,
        image_name: str,
        analysis: dict[str, Any],
        patient_id: str | None = None,
        study_date: datetime | str | None = None,
        uploaded_at: datetime | str | None = None,
        modality: str | None = None,
        body_part: str | None = None,
    ) -> dict[str, int]:
        tenant = _tenant_scope(tenant_id)
        source_ref = f"image:{image_id}"
        start_date = _iso_timestamp(study_date) or _iso_timestamp(uploaded_at)

        await self.delete_source_artifacts("image", image_id)

        imaging_node = GraphNodeSpec(
            node_id=f"imaging-study:{image_id}",
            label="ImagingStudy",
            properties={
                "name": image_name,
                "image_id": image_id,
                "tenant_id": tenant,
                "patient_id": patient_id,
                "modality": modality or analysis.get("modality_detected"),
                "body_part": body_part or analysis.get("body_part_detected"),
                "source_type": "image",
                "source_id": image_id,
                "source_ref": source_ref,
                "uploaded_at": _iso_timestamp(uploaded_at),
                "study_date": _iso_timestamp(study_date),
            },
        )
        nodes: list[GraphNodeSpec] = [imaging_node]
        edges: list[GraphEdgeSpec] = []
        patient_node_id = None
        encounter_node_id = f"encounter:image:{image_id}"

        nodes.append(
            GraphNodeSpec(
                node_id=encounter_node_id,
                label="Encounter",
                properties={
                    "name": f"Encounter {image_name}",
                    "encounter_id": encounter_node_id,
                    "tenant_id": tenant,
                    "patient_id": patient_id,
                    "occurred_at": start_date,
                    "source_type": "image",
                    "source_id": image_id,
                    "source_ref": source_ref,
                },
            )
        )
        edges.append(
            GraphEdgeSpec(
                source_id=imaging_node.node_id,
                target_id=encounter_node_id,
                relationship_type="OCCURRED_AT",
                start_date=start_date,
                end_date=None,
                properties={
                    "edge_key": f"{source_ref}:study-encounter",
                    "tenant_id": tenant,
                    "patient_id": patient_id,
                    "source_type": "image",
                    "source_id": image_id,
                    "source_ref": source_ref,
                },
            )
        )

        if patient_id:
            patient_node_id = f"tenant:{tenant}:patient:{patient_id}"
            nodes.append(
                GraphNodeSpec(
                    node_id=patient_node_id,
                    label="Patient",
                    properties={
                        "name": patient_id,
                        "patient_id": patient_id,
                        "tenant_id": tenant,
                    },
                )
            )
            edges.append(
                GraphEdgeSpec(
                    source_id=patient_node_id,
                    target_id=encounter_node_id,
                    relationship_type="RELATED_TO",
                    start_date=start_date,
                    end_date=None,
                    properties={
                        "edge_key": f"{source_ref}:patient-encounter",
                        "tenant_id": tenant,
                        "patient_id": patient_id,
                        "source_type": "image",
                        "source_id": image_id,
                        "source_ref": source_ref,
                    },
                )
            )

        findings = analysis.get("findings") or []
        finding_node_ids: list[str] = []
        for index, finding in enumerate(findings[:25], start=1):
            if not isinstance(finding, dict):
                continue
            finding_id = f"finding:{image_id}:{index}"
            finding_node_ids.append(finding_id)
            nodes.append(
                GraphNodeSpec(
                    node_id=finding_id,
                    label="Finding",
                    properties={
                        "name": finding.get("description") or f"Finding {index}",
                        "location": finding.get("location"),
                        "severity": finding.get("severity"),
                        "confidence": finding.get("confidence"),
                        "tenant_id": tenant,
                        "patient_id": patient_id,
                        "source_type": "image",
                        "source_id": image_id,
                        "source_ref": source_ref,
                    },
                )
            )
            edges.append(
                GraphEdgeSpec(
                    source_id=imaging_node.node_id,
                    target_id=finding_id,
                    relationship_type="HAS_FINDING",
                    start_date=start_date,
                    end_date=None,
                    properties={
                        "edge_key": f"{source_ref}:finding:{index}",
                        "tenant_id": tenant,
                        "patient_id": patient_id,
                        "source_type": "image",
                        "source_id": image_id,
                        "source_ref": source_ref,
                    },
                )
            )
            if patient_node_id:
                edges.append(
                    GraphEdgeSpec(
                        source_id=patient_node_id,
                        target_id=finding_id,
                        relationship_type="HAS_FINDING",
                        start_date=start_date,
                        end_date=None,
                        properties={
                            "edge_key": f"{source_ref}:patient-finding:{index}",
                            "tenant_id": tenant,
                            "patient_id": patient_id,
                            "source_type": "image",
                            "source_id": image_id,
                            "source_ref": source_ref,
                        },
                    )
                )

        normalized_entities = analysis.get("normalized_entities") or []
        for index, entity in enumerate(normalized_entities[:25], start=1):
            if not isinstance(entity, dict) or entity.get("is_ungrounded"):
                continue
            label = _label_for_entity(entity)
            entity_node_id = _entity_node_id(tenant, entity)
            entity_name = str(entity.get("canonical_label") or entity.get("surface_form") or entity_node_id)
            nodes.append(
                GraphNodeSpec(
                    node_id=entity_node_id,
                    label=label,
                    properties={
                        "name": entity_name,
                        "canonical_label": entity.get("canonical_label"),
                        "surface_form": entity.get("surface_form"),
                        "ontology": entity.get("ontology"),
                        "concept_id": entity.get("concept_id"),
                        "semantic_type": entity.get("semantic_type"),
                        "tenant_id": tenant,
                        "patient_id": patient_id,
                    },
                )
            )
            relation_source = finding_node_ids[min(index - 1, len(finding_node_ids) - 1)] if finding_node_ids else imaging_node.node_id
            edges.append(
                GraphEdgeSpec(
                    source_id=relation_source,
                    target_id=entity_node_id,
                    relationship_type="RELATED_TO",
                    start_date=start_date,
                    end_date=None,
                    properties={
                        "edge_key": f"{source_ref}:entity:{entity.get('concept_id') or entity_name}:{index}",
                        "tenant_id": tenant,
                        "patient_id": patient_id,
                        "source_type": "image",
                        "source_id": image_id,
                        "source_ref": source_ref,
                    },
                )
            )
            if patient_node_id and label == "Condition":
                edges.append(
                    GraphEdgeSpec(
                        source_id=patient_node_id,
                        target_id=entity_node_id,
                        relationship_type="HAS_CONDITION",
                        start_date=start_date,
                        end_date=None,
                        properties={
                            "edge_key": f"{source_ref}:patient-condition:{entity.get('concept_id') or entity_name}",
                            "tenant_id": tenant,
                            "patient_id": patient_id,
                            "source_type": "image",
                            "source_id": image_id,
                            "source_ref": source_ref,
                        },
                    )
                )
            if patient_node_id and label == "Medication":
                edges.append(
                    GraphEdgeSpec(
                        source_id=patient_node_id,
                        target_id=entity_node_id,
                        relationship_type="TOOK_MEDICATION",
                        start_date=start_date,
                        end_date=None,
                        properties={
                            "edge_key": f"{source_ref}:patient-medication:{entity.get('concept_id') or entity_name}",
                            "tenant_id": tenant,
                            "patient_id": patient_id,
                            "source_type": "image",
                            "source_id": image_id,
                            "source_ref": source_ref,
                        },
                    )
                )

        return await self._persist_subgraph(nodes=nodes, edges=edges)

    def _references_source(self, properties: dict[str, Any] | None, source_type: str, source_id: str) -> bool:
        props = properties or {}
        source_match = props.get("source_type") == source_type and str(props.get("source_id")) == str(source_id)
        if source_match:
            return True
        if source_type == "document" and str(props.get("document_id")) == str(source_id):
            return True
        if source_type == "image" and str(props.get("image_id")) == str(source_id):
            return True
        return False

    async def delete_source_artifacts(self, source_type: str, source_id: str) -> int:
        removed = 0
        orphan_candidates: set[str] = set()
        async with async_session_factory() as session:
            edge_result = await session.execute(select(GraphEdge))
            for edge in edge_result.scalars().all():
                if not self._references_source(edge.properties, source_type, source_id):
                    continue
                orphan_candidates.add(edge.source_id)
                orphan_candidates.add(edge.target_id)
                await session.delete(edge)
                removed += 1

            node_result = await session.execute(select(GraphNode))
            for node in node_result.scalars().all():
                if not self._references_source(node.properties, source_type, source_id):
                    continue
                orphan_candidates.add(node.node_id)

            await session.flush()

            remaining_edge_result = await session.execute(select(GraphEdge))
            remaining_references = {
                edge.source_id for edge in remaining_edge_result.scalars().all()
            }
            remaining_edge_result = await session.execute(select(GraphEdge))
            remaining_references |= {
                edge.target_id for edge in remaining_edge_result.scalars().all()
            }

            for node_id in orphan_candidates:
                if node_id in remaining_references:
                    continue
                node = await session.get(GraphNode, node_id)
                if node is None:
                    continue
                if self._references_source(node.properties, source_type, source_id):
                    await session.delete(node)
                    removed += 1

            await session.commit()
        try:
            from app.core.caching import CacheManager

            await CacheManager.invalidate_prefix_async("cgrag:graph:")
        except Exception:
            logger.warning("Graph cache invalidation failed after source artifact deletion")

        if self.settings.use_neo4j:
            removed += await neo4j_graph_service.delete_source_artifacts(source_type, source_id)
        return removed

    async def delete_document_artifacts(self, document_id: str) -> int:
        return await self.delete_source_artifacts("document", document_id)

    async def delete_image_artifacts(self, image_id: str) -> int:
        return await self.delete_source_artifacts("image", image_id)

    async def query_temporal_state(
        self,
        entity_id: str,
        target_date_str: str,
        *,
        tenant_id: str | None = None,
        patient_id: str | None = None,
        limit: int | None = None,
        current_only: bool = False,
    ) -> dict[str, Any]:
        import time
        from app.core.metrics import observe_graph_query
        started = time.perf_counter()
        try:
            effective_limit = self._bounded_limit(limit)
            if self.settings.use_neo4j:
                try:
                    # Align Neo4j query parameters if needed
                    return await neo4j_graph_service.query_temporal_state(
                        entity_id,
                        target_date_str,
                        tenant_id=tenant_id,
                        patient_id=patient_id,
                        limit=effective_limit,
                    )
                except Exception as exc:
                    logger.warning("Neo4j graph query failed, falling back to DB graph: %s", exc)

            try:
                datetime.fromisoformat(target_date_str.replace("Z", "+00:00"))
            except ValueError:
                return {"error": "target_date must be in ISO format (YYYY-MM-DD)."}

            entity_key = entity_id.strip().lower()
            async with async_session_factory() as session:
                nodes = (await session.execute(select(GraphNode))).scalars().all()
                matched_node = None
                for node in nodes:
                    if not _scope_matches(node.properties, tenant_id=tenant_id, patient_id=patient_id):
                        continue
                    props = node.properties or {}
                    candidates = {
                        node.node_id.lower(),
                        str(props.get("name") or "").lower(),
                        str(props.get("canonical_label") or "").lower(),
                        str(props.get("patient_id") or "").lower(),
                        str(props.get("document_id") or "").lower(),
                        str(props.get("image_id") or "").lower(),
                    }
                    if entity_key in candidates:
                        matched_node = node
                        break

                if matched_node is None:
                    return {"error": f"Entity '{entity_id}' not found in the knowledge graph."}

                edge_result = await session.execute(
                    select(GraphEdge).where(
                        or_(
                            GraphEdge.source_id == matched_node.node_id,
                            GraphEdge.target_id == matched_node.node_id,
                        )
                    )
                )
                edges = edge_result.scalars().all()

                active_edges: list[dict[str, Any]] = []
                for edge in edges:
                    if not _scope_matches(edge.properties, tenant_id=tenant_id, patient_id=patient_id):
                        continue

                    status, temp_conf = classify_temporal_status(edge.start_date, edge.end_date, target_date_str)
                    if current_only and status != "active":
                        continue

                    if edge.source_id == matched_node.node_id:
                        target_node = await session.get(GraphNode, edge.target_id)
                        active_edges.append(
                            {
                                "relationship": edge.relationship_type,
                                "target_entity": edge.target_id,
                                "target_label": target_node.label if target_node else "Unknown",
                                "start_date": edge.start_date,
                                "end_date": edge.end_date,
                                "status": status,
                                "temporal_confidence": temp_conf,
                                "properties": edge.properties or {},
                            }
                        )
                    else:
                        source_node = await session.get(GraphNode, edge.source_id)
                        active_edges.append(
                            {
                                "relationship": f"IS_{edge.relationship_type}_OF",
                                "source_entity": edge.source_id,
                                "source_label": source_node.label if source_node else "Unknown",
                                "start_date": edge.start_date,
                                "end_date": edge.end_date,
                                "status": status,
                                "temporal_confidence": temp_conf,
                                "properties": edge.properties or {},
                            }
                        )

                active_edges = active_edges[:effective_limit]
                return {
                    "entity": matched_node.node_id,
                    "entity_label": matched_node.label,
                    "target_date": target_date_str,
                    "active_relationships": active_edges,
                    "total_active": len(active_edges),
                    "source": "temporal_graph",
                }
        finally:
            observe_graph_query((time.perf_counter() - started) * 1000)

    async def safe_text_query(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
        patient_id: str | None = None,
        limit: int | None = None,
        current_only: bool = False,
    ) -> dict[str, Any]:
        if self.settings.use_neo4j:
            try:
                return await neo4j_graph_service.safe_text_query(
                    query,
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                    limit=limit,
                )
            except Exception as exc:
                logger.warning("Neo4j safe_text_query failed, falling back to DB graph: %s", exc)

        effective_limit = self._bounded_limit(limit)
        target_date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", query or "")
        target_date = target_date_match.group(0) if target_date_match else None
        search_term = (query or "").strip().lower()
        if target_date:
            search_term = search_term.replace(target_date.lower(), "").strip(" ,.?")

        if not search_term:
            return {"error": "Provide a graph entity or question containing a graph entity."}

        async with async_session_factory() as session:
            nodes = (await session.execute(select(GraphNode))).scalars().all()
            matches = []
            for node in nodes:
                if not _scope_matches(node.properties, tenant_id=tenant_id, patient_id=patient_id):
                    continue
                props = node.properties or {}
                candidates = {
                    node.node_id.lower(),
                    str(props.get("name") or "").lower(),
                    str(props.get("canonical_label") or "").lower(),
                }
                if any(search_term in c for c in candidates if c):
                    matches.append({
                        "id": node.node_id,
                        "label": node.label,
                        "name": props.get("name") or node.node_id,
                    })

        if not matches:
            return {"error": f"No graph entities matched '{query}'."}

        if len(matches) == 1:
            return await self.query_temporal_state(
                matches[0]["id"],
                target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                tenant_id=tenant_id,
                patient_id=patient_id,
                limit=effective_limit,
                current_only=current_only,
            )

        return {
            "answer": "Multiple graph entities matched the query. Narrow the term or pass a patient/date scope.",
            "matches": matches[:5],
            "source": "temporal_graph",
        }

    async def get_evidence_facts(
        self,
        *,
        tenant_id: str | None,
        patient_id: str,
        target_date: str | None = None,
        limit: int | None = None,
        verified_only: bool = True,
        latest_only: bool = True,
    ) -> list[GraphEvidenceFact]:
        """Return fact-level graph evidence for RAG, separate from visualization export."""
        effective_limit = self._bounded_limit(limit)
        scoped_tenant = tenant_id
        labels = {"Condition", "Medication", "LabResult", "Lab", "Observation", "Finding", "Encounter"}
        target_date = target_date or datetime.now(timezone.utc).date().isoformat()

        async with async_session_factory() as session:
            nodes = (await session.execute(select(GraphNode))).scalars().all()

        raw_facts: list[dict[str, Any]] = []
        for node in nodes:
            if node.label not in labels:
                continue
            props = node.properties or {}
            if not _scope_matches(props, tenant_id=scoped_tenant, patient_id=patient_id):
                continue

            source_document_id = props.get("source_document_id") or props.get("document_id")
            source_chunk_id = props.get("source_chunk_id") or props.get("chunk_id")
            verification_status = "verified" if source_document_id and source_chunk_id else "unverified"
            if verified_only and verification_status != "verified":
                continue

            start_date = props.get("start_date") or props.get("date") or props.get("observed_at")
            end_date = props.get("end_date")
            temporal_status, _ = classify_temporal_status(start_date, end_date, target_date)
            name = str(
                props.get("normalized_name")
                or props.get("canonical_label")
                or props.get("name")
                or node.node_id
            )
            fact_type = {
                "Condition": "condition",
                "Medication": "medication",
                "LabResult": "lab",
                "Lab": "lab",
                "Observation": "observation",
                "Finding": "finding",
                "Encounter": "encounter",
            }[node.label]
            if fact_type == "medication":
                predicate = "medication_status"
            elif fact_type == "condition":
                predicate = "condition_status"
            elif fact_type == "lab":
                predicate = "lab_result"
            else:
                predicate = fact_type

            raw_facts.append(
                {
                    "fact_type": fact_type,
                    "normalized_subject": str(patient_id),
                    "normalized_predicate": predicate,
                    "normalized_object": name,
                    "source_document_id": str(source_document_id) if source_document_id else None,
                    "source_chunk_id": str(source_chunk_id) if source_chunk_id else None,
                    "tenant_id": props.get("tenant_id"),
                    "patient_id": props.get("patient_id"),
                    "extracted_at": props.get("created_at"),
                    "extractor_version": str(props.get("extractor_version") or props.get("extraction_method") or "graph-v1"),
                    "extraction_confidence": props.get("extraction_confidence", props.get("confidence")),
                    "verification_status": verification_status,
                    "start_date": str(start_date) if start_date else None,
                    "end_date": str(end_date) if end_date else None,
                    "temporal_status": temporal_status,
                    "value": props.get("value", props.get("value_numeric")),
                    "unit": props.get("unit") or props.get("value_unit"),
                }
            )

        if latest_only:
            latest: dict[tuple[str, str, str], dict[str, Any]] = {}
            for fact in raw_facts:
                key = (
                    str(fact["fact_type"]).lower(),
                    str(fact["normalized_predicate"]).lower(),
                    str(fact["normalized_object"]).lower(),
                )
                current = latest.get(key)
                if current is None:
                    latest[key] = fact
                    continue
                current_dt = parse_date_robust(current.get("start_date"))
                candidate_dt = parse_date_robust(fact.get("start_date"))
                if candidate_dt and (current_dt is None or candidate_dt >= current_dt):
                    latest[key] = fact
            raw_facts = list(latest.values())

        raw_facts.sort(
            key=lambda fact: (
                str(fact["fact_type"]),
                str(fact["normalized_object"]).lower(),
                str(fact.get("start_date") or ""),
                str(fact.get("source_chunk_id") or ""),
            )
        )

        counters: dict[str, int] = {}
        prefixes = {
            "condition": "COND",
            "medication": "MED",
            "lab": "LAB",
            "observation": "OBS",
            "finding": "FIND",
            "encounter": "ENC",
        }
        facts: list[GraphEvidenceFact] = []
        for fact in raw_facts[:effective_limit]:
            prefix = prefixes.get(str(fact["fact_type"]), "FACT")
            counters[prefix] = counters.get(prefix, 0) + 1
            facts.append(GraphEvidenceFact(fact_id=f"GRAPH-{prefix}-{counters[prefix]:03d}", **fact))
        return facts

    async def get_lab_trends(
        self,
        patient_id: str,
        lab_name: str | None = None,
        *,
        tenant_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        effective_limit = max(1, min(int(limit), 200))
        normalized_patient_id = patient_id.strip()
        normalized_lab_name = (lab_name or "").strip()
        patient_key = normalized_patient_id.lower()
        lab_key = normalized_lab_name.lower()

        if not normalized_patient_id:
            return {
                "patient_id": patient_id,
                "lab_name_filter": lab_name,
                "data_points": [],
                "total": 0,
                "date_range": {"earliest": None, "latest": None},
                "available_labs": [],
            }

        edge_types = ("HAS_LAB", "HAS_FINDING", "MENTIONED_IN", "LAB_RESULT")
        patient_pattern = f"%{normalized_patient_id}%"
        source_node = aliased(GraphNode)
        target_node = aliased(GraphNode)

        def _normalize_date(value: Any) -> str | None:
            text = str(value or "").strip()
            if not text:
                return None
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                return text[:10] if len(text) >= 10 else text

        def _node_name(node: GraphNode) -> str:
            props = node.properties or {}
            return str(props.get("name") or props.get("canonical_label") or node.node_id)

        def _node_matches_patient(node: GraphNode) -> bool:
            props = node.properties or {}
            candidates = (
                node.node_id,
                props.get("name"),
                props.get("patient_id"),
                props.get("source_id"),
            )
            return any(patient_key in str(value).lower() for value in candidates if value)

        def _edge_matches_patient(edge: GraphEdge) -> bool:
            props = edge.properties or {}
            candidates = (
                edge.source_id,
                edge.target_id,
                props.get("patient_id"),
                props.get("source_id"),
                props.get("source_ref"),
                props.get("document_id"),
                props.get("image_id"),
            )
            return any(patient_key in str(value).lower() for value in candidates if value)

        def _resolve_lab_node(source: GraphNode, target: GraphNode) -> GraphNode | None:
            if source.label == "Lab":
                return source
            if target.label == "Lab":
                return target
            return None

        base_stmt = (
            select(GraphEdge, source_node, target_node)
            .join(source_node, GraphEdge.source_id == source_node.node_id)
            .join(target_node, GraphEdge.target_id == target_node.node_id)
            .where(GraphEdge.relationship_type.in_(edge_types))
            .order_by(GraphEdge.start_date.asc(), GraphEdge.created_at.asc())
        )
        id_match_stmt = base_stmt.where(
            or_(
                GraphEdge.source_id.ilike(patient_pattern),
                GraphEdge.target_id.ilike(patient_pattern),
            )
        )

        async with async_session_factory() as session:
            prioritized_rows = (await session.execute(id_match_stmt)).all()
            fallback_rows = (await session.execute(base_stmt)).all()

        merged_rows: list[tuple[GraphEdge, GraphNode, GraphNode]] = []
        seen_edge_ids: set[str] = set()
        for edge, source, target in [*prioritized_rows, *fallback_rows]:
            edge_id = str(edge.id)
            if edge_id in seen_edge_ids:
                continue
            seen_edge_ids.add(edge_id)
            merged_rows.append((edge, source, target))

        filtered_points: list[dict[str, Any]] = []
        available_labs: set[str] = set()

        for edge, source, target in merged_rows:
            if not _scope_matches(edge.properties, tenant_id=tenant_id, patient_id=normalized_patient_id):
                continue
            if not _scope_matches(source.properties, tenant_id=tenant_id, patient_id=normalized_patient_id):
                continue
            if not _scope_matches(target.properties, tenant_id=tenant_id, patient_id=normalized_patient_id):
                continue
            if not (_edge_matches_patient(edge) or _node_matches_patient(source) or _node_matches_patient(target)):
                continue

            lab_node = _resolve_lab_node(source, target)
            if lab_node is None:
                continue

            lab_props = lab_node.properties or {}
            edge_props = edge.properties or {}
            lab_label = _node_name(lab_node).strip() or lab_node.node_id
            available_labs.add(lab_label)

            if lab_key and lab_key not in lab_label.lower():
                continue

            value = lab_props.get("value")
            if value is None:
                value = lab_props.get("value_numeric")
            if value is None:
                value = edge_props.get("value_numeric")
            if value is None:
                value = edge_props.get("value")

            value_unit = lab_props.get("unit")
            if value_unit is None:
                value_unit = edge_props.get("unit")

            point_date = _normalize_date(
                edge_props.get("start_date")
                or edge_props.get("date")
                or edge_props.get("observed_at")
                or edge.start_date
                or edge.end_date
            )

            filtered_points.append(
                {
                    "date": point_date,
                    "lab": lab_label,
                    "value": value,
                    "value_unit": value_unit,
                    "node_id": lab_node.node_id,
                    "source_type": edge_props.get("source_type") or lab_props.get("source_type"),
                    "source_id": edge_props.get("source_id")
                    or edge_props.get("document_id")
                    or edge_props.get("image_id")
                    or lab_props.get("source_id"),
                }
            )

        filtered_points.sort(
            key=lambda item: (
                item.get("date") or "",
                item.get("lab") or "",
                item.get("node_id") or "",
            )
        )
        data_points = filtered_points[:effective_limit]
        dates = [item["date"] for item in data_points if item.get("date")]

        return {
            "patient_id": normalized_patient_id,
            "lab_name_filter": normalized_lab_name or None,
            "data_points": data_points,
            "total": len(data_points),
            "date_range": {
                "earliest": dates[0] if dates else None,
                "latest": dates[-1] if dates else None,
            },
            "available_labs": sorted(available_labs),
        }

    @staticmethod
    def _is_active_on_date(start_date: str | None, end_date: str | None, target_date_str: str) -> bool:
        status, _ = classify_temporal_status(start_date, end_date, target_date_str)
        return status == "active"


    async def export_for_visualization(
        self,
        limit: int = 500,
        *,
        tenant_id: str | None = None,
        patient_id: str | None = None,
    ) -> dict[str, Any]:
        effective_limit = self._bounded_limit(limit)
        if self.settings.use_neo4j:
            try:
                return await neo4j_graph_service.export_graph(
                    limit=effective_limit,
                    tenant_id=tenant_id,
                    patient_id=patient_id,
                )
            except Exception as exc:
                logger.warning("Neo4j graph export failed, falling back to DB graph: %s", exc)

        async with async_session_factory() as session:
            nodes = (await session.execute(select(GraphNode))).scalars().all()
            scoped_nodes = [
                node
                for node in nodes
                if _scope_matches(node.properties, tenant_id=tenant_id, patient_id=patient_id)
            ][:effective_limit]
            allowed_ids = {node.node_id for node in scoped_nodes}
            edges = (
                await session.execute(
                    select(GraphEdge).where(
                        and_(GraphEdge.source_id.in_(allowed_ids), GraphEdge.target_id.in_(allowed_ids))
                    )
                )
            ).scalars().all()

        return {
            "nodes": [
                {
                    "id": node.node_id,
                    "name": (node.properties or {}).get("name") or node.node_id,
                    "label": node.label,
                    "properties": node.properties or {},
                }
                for node in scoped_nodes
            ],
            "links": [
                {
                    "source": edge.source_id,
                    "target": edge.target_id,
                    "type": edge.relationship_type,
                    "properties": edge.properties or {},
                    "start_date": edge.start_date,
                    "end_date": edge.end_date,
                }
                for edge in edges
                if _scope_matches(edge.properties, tenant_id=tenant_id, patient_id=patient_id)
            ],
            "source": "temporal_graph",
        }

    async def get_stats(self) -> dict[str, Any]:
        async with async_session_factory() as session:
            nodes = (await session.execute(select(GraphNode))).scalars().all()
            edges = (await session.execute(select(GraphEdge))).scalars().all()

        payload: dict[str, Any] = {
            "nodes": len(nodes),
            "edges": len(edges),
            "status": "active_temporal",
            "backend": "neo4j" if self.settings.use_neo4j else "database",
            "schema": FORMAL_GRAPH_SCHEMA,
            "last_updated": datetime.utcnow().isoformat(),
        }
        if self.settings.use_neo4j:
            try:
                payload["neo4j"] = await neo4j_graph_service.get_stats()
            except Exception as exc:
                payload["neo4j"] = {"status": "unhealthy", "error": str(exc)}
        return payload


temporal_graph_service = ClinicalGraphService()
