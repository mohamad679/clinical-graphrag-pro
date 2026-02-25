"""
Entity normalization API endpoints.
Maps extracted clinical entities to canonical concepts in standard ontologies.
"""

from fastapi import APIRouter

from app.schemas.entity_normalization import (
    NormalizationRequest,
    NormalizationResponse,
    OntologiesResponse,
    OntologyInfo,
)
from app.services.entity_normalization import entity_normalization_service

router = APIRouter(prefix="/entity-normalization", tags=["Entity Normalization"])


@router.post("/normalize", response_model=NormalizationResponse)
async def normalize_entities(request: NormalizationRequest):
    """
    Normalize a batch of extracted medical entities to canonical concepts.

    Each entity is mapped to its canonical label, preferred ontology (UMLS,
    SNOMED CT, RxNorm, ICD-10), concept identifier, and semantic type.
    Synonyms are collapsed to the same canonical concept.
    """
    return await entity_normalization_service.normalize(request.entities)


@router.get("/ontologies", response_model=OntologiesResponse)
async def list_ontologies():
    """Return metadata about supported medical ontologies."""
    raw = entity_normalization_service.get_supported_ontologies()
    return OntologiesResponse(
        ontologies=[OntologyInfo(**o) for o in raw]
    )
