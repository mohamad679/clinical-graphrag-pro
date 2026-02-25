"""
Pydantic schemas for medical entity normalization.
Maps extracted clinical entities to canonical concepts in standard ontologies.
"""

from datetime import datetime
from pydantic import BaseModel, Field


# ── Requests ─────────────────────────────────────────────


class EntityInput(BaseModel):
    """A single extracted entity to be normalized."""
    surface_form: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The entity as it appeared in the clinical text",
    )
    context: str | None = Field(
        None,
        max_length=2000,
        description="Optional surrounding text to disambiguate the entity",
    )


class NormalizationRequest(BaseModel):
    """Batch request to normalize one or more clinical entities."""
    entities: list[EntityInput] = Field(
        ...,
        min_length=1,
        max_length=200,
        description="List of extracted entities to normalize",
    )


# ── Responses ────────────────────────────────────────────


class NormalizedEntity(BaseModel):
    """A single entity after normalization to a canonical concept."""
    surface_form: str = Field(
        ..., description="Original text as it appeared in the source"
    )
    canonical_label: str = Field(
        ..., description="Normalized/canonical concept name"
    )
    ontology: str = Field(
        ..., description="Matched ontology: UMLS | SNOMED CT | RxNorm | ICD-10"
    )
    concept_id: str = Field(
        ..., description="Concept identifier (CUI, SCTID, RxCUI, or ICD code)"
    )
    semantic_type: str = Field(
        ..., description="Semantic type, e.g. Disease, Drug, Procedure, Symptom"
    )
    confidence: str = Field(
        ..., description="Confidence level: High | Medium | Low"
    )
    is_ungrounded: bool = Field(
        False,
        description="True if no confident match was found",
    )
    closest_candidate: str | None = Field(
        None,
        description="Suggested closest concept when entity is ungrounded",
    )


class NormalizationResponse(BaseModel):
    """Full response from the normalization pipeline."""
    normalized_entities: list[NormalizedEntity]
    total: int = Field(..., description="Number of entities processed")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Processing timestamp",
    )


class OntologyInfo(BaseModel):
    """Metadata about a supported ontology."""
    name: str
    code: str
    description: str
    preferred_for: list[str]


class OntologiesResponse(BaseModel):
    """List of supported ontologies."""
    ontologies: list[OntologyInfo]
