"""
FHIR Ingestion Service for Clinical GraphRAG Pro.
Maps FHIR JSON resources to internal clinical graph nodes and edges with provenance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.services.graph import (
    temporal_graph_service,
    GraphNodeSpec,
    GraphEdgeSpec,
    _tenant_scope,
    _iso_timestamp,
)

logger = logging.getLogger(__name__)


def _clean_ref_id(ref: str | None) -> str | None:
    if not ref:
        return None
    cleaned = ref.strip()
    if cleaned.startswith("Patient/"):
        return cleaned[len("Patient/"):]
    if cleaned.startswith("Encounter/"):
        return cleaned[len("Encounter/"):]
    if cleaned.startswith("Observation/"):
        return cleaned[len("Observation/"):]
    if cleaned.startswith("Condition/"):
        return cleaned[len("Condition/"):]
    if cleaned.startswith("MedicationRequest/"):
        return cleaned[len("MedicationRequest/"):]
    if cleaned.startswith("urn:uuid:"):
        return cleaned[len("urn:uuid:"):]
    return cleaned


class FHIRIngestionService:
    async def ingest_fhir_bundle(self, bundle_json: dict, tenant_id: str | None = None) -> dict[str, int]:
        """
        Accepts a FHIR Bundle or single FHIR Resource, maps to nodes/edges, and persists.
        """
        tenant = _tenant_scope(tenant_id)
        resources: list[dict] = []

        resource_type = bundle_json.get("resourceType")
        if resource_type == "Bundle":
            for entry in bundle_json.get("entry", []):
                res = entry.get("resource")
                if res:
                    resources.append(res)
        elif resource_type:
            resources.append(bundle_json)
        else:
            raise ValueError("Input JSON does not appear to be a valid FHIR resource or Bundle.")

        nodes: list[GraphNodeSpec] = []
        edges: list[GraphEdgeSpec] = []
        created_time_iso = datetime.now(timezone.utc).isoformat()

        for res in resources:
            try:
                res_type = res.get("resourceType")
                res_id = res.get("id")
                if not res_id:
                    continue

                if res_type == "Patient":
                    # Parse Patient
                    patient_node_id = f"tenant:{tenant}:patient:{res_id}"
                    names = res.get("name", [])
                    name_str = ""
                    if names:
                        n = names[0]
                        given = " ".join(n.get("given", []))
                        family = n.get("family", "")
                        name_str = f"{given} {family}".strip() or n.get("text", "")
                    if not name_str:
                        name_str = f"Patient {res_id}"

                    nodes.append(
                        GraphNodeSpec(
                            node_id=patient_node_id,
                            label="Patient",
                            properties={
                                "id": patient_node_id,
                                "name": name_str,
                                "patient_id": res_id,
                                "gender": res.get("gender"),
                                "birth_date": res.get("birthDate"),
                                "tenant_id": tenant,
                                "extraction_method": "fhir",
                                "created_at": created_time_iso,
                            },
                        )
                    )

                elif res_type == "Condition":
                    # Parse Condition
                    cond_node_id = f"tenant:{tenant}:condition:{res_id}"
                    code_data = res.get("code", {})
                    codings = code_data.get("coding", [])
                    name_str = ""
                    concept_id = ""
                    ontology = ""
                    if codings:
                        name_str = codings[0].get("display", "")
                        concept_id = codings[0].get("code", "")
                        ontology = codings[0].get("system", "")
                    if not name_str:
                        name_str = code_data.get("text", f"Condition {res_id}")

                    subj_ref = _clean_ref_id(res.get("subject", {}).get("reference"))
                    onset_date = res.get("onsetDateTime") or res.get("recordedDate") or res.get("onsetPeriod", {}).get("start")
                    abatement_date = res.get("abatementDateTime") or res.get("abatementPeriod", {}).get("end")

                    clinical_status = ""
                    c_status_codings = res.get("clinicalStatus", {}).get("coding", [])
                    if c_status_codings:
                        clinical_status = c_status_codings[0].get("code", "")

                    nodes.append(
                        GraphNodeSpec(
                            node_id=cond_node_id,
                            label="Condition",
                            properties={
                                "id": cond_node_id,
                                "name": name_str,
                                "normalized_name": name_str,
                                "concept_id": concept_id,
                                "ontology": ontology,
                                "clinical_status": clinical_status,
                                "patient_id": subj_ref,
                                "tenant_id": tenant,
                                "start_date": _iso_timestamp(onset_date),
                                "end_date": _iso_timestamp(abatement_date),
                                "extraction_method": "fhir",
                                "created_at": created_time_iso,
                            },
                        )
                    )

                    if subj_ref:
                        pat_node_id = f"tenant:{tenant}:patient:{subj_ref}"
                        edges.append(
                            GraphEdgeSpec(
                                source_id=pat_node_id,
                                target_id=cond_node_id,
                                relationship_type="HAS_CONDITION",
                                start_date=_iso_timestamp(onset_date),
                                end_date=_iso_timestamp(abatement_date),
                                properties={
                                    "edge_key": f"patient:{subj_ref}:has_condition:{res_id}",
                                    "tenant_id": tenant,
                                    "patient_id": subj_ref,
                                    "extraction_method": "fhir",
                                    "created_at": created_time_iso,
                                },
                            )
                        )

                elif res_type == "Observation":
                    # Parse Observation
                    code_data = res.get("code", {})
                    codings = code_data.get("coding", [])
                    name_str = ""
                    concept_id = ""
                    ontology = ""
                    if codings:
                        name_str = codings[0].get("display", "")
                        concept_id = codings[0].get("code", "")
                        ontology = codings[0].get("system", "")
                    if not name_str:
                        name_str = code_data.get("text", f"Observation {res_id}")

                    # Determine if LabResult or Observation
                    is_lab = False
                    categories = res.get("category", [])
                    for cat in categories:
                        for coding in cat.get("coding", []):
                            if coding.get("code") == "laboratory" or "lab" in str(coding.get("display", "")).lower():
                                is_lab = True

                    label = "LabResult" if is_lab else "Observation"
                    obs_node_id = f"tenant:{tenant}:{label.lower()}:{res_id}"

                    val_qty = res.get("valueQuantity", {})
                    val_str = res.get("valueString")
                    val_cc = res.get("valueCodeableConcept", {}).get("text")
                    value_val = val_qty.get("value") if val_qty else val_str or val_cc
                    value_numeric = float(val_qty.get("value")) if val_qty and val_qty.get("value") is not None else None
                    unit_val = val_qty.get("unit") if val_qty else None

                    subj_ref = _clean_ref_id(res.get("subject", {}).get("reference"))
                    obs_date = res.get("effectiveDateTime") or res.get("effectivePeriod", {}).get("start") or res.get("issued")
                    enc_ref = _clean_ref_id(res.get("encounter", {}).get("reference"))

                    nodes.append(
                        GraphNodeSpec(
                            node_id=obs_node_id,
                            label=label,
                            properties={
                                "id": obs_node_id,
                                "name": name_str,
                                "normalized_name": name_str,
                                "concept_id": concept_id,
                                "ontology": ontology,
                                "value": value_val,
                                "value_numeric": value_numeric,
                                "unit": unit_val,
                                "status": res.get("status"),
                                "patient_id": subj_ref,
                                "tenant_id": tenant,
                                "start_date": _iso_timestamp(obs_date),
                                "extraction_method": "fhir",
                                "created_at": created_time_iso,
                            },
                        )
                    )

                    if subj_ref:
                        pat_node_id = f"tenant:{tenant}:patient:{subj_ref}"
                        rel_type = "HAS_LAB_RESULT" if is_lab else "HAS_FINDING"
                        edges.append(
                            GraphEdgeSpec(
                                source_id=pat_node_id,
                                target_id=obs_node_id,
                                relationship_type=rel_type,
                                start_date=_iso_timestamp(obs_date),
                                end_date=None,
                                properties={
                                    "edge_key": f"patient:{subj_ref}:has_obs:{res_id}",
                                    "tenant_id": tenant,
                                    "patient_id": subj_ref,
                                    "extraction_method": "fhir",
                                    "created_at": created_time_iso,
                                },
                            )
                        )

                    if enc_ref:
                        enc_node_id = f"tenant:{tenant}:encounter:{enc_ref}"
                        edges.append(
                            GraphEdgeSpec(
                                source_id=obs_node_id,
                                target_id=enc_node_id,
                                relationship_type="OCCURRED_DURING",
                                start_date=_iso_timestamp(obs_date),
                                end_date=None,
                                properties={
                                    "edge_key": f"obs:{res_id}:occurred_during:encounter:{enc_ref}",
                                    "tenant_id": tenant,
                                    "patient_id": subj_ref,
                                    "extraction_method": "fhir",
                                    "created_at": created_time_iso,
                                },
                            )
                        )

                elif res_type == "MedicationRequest":
                    # Parse MedicationRequest
                    med_node_id = f"tenant:{tenant}:medication:{res_id}"
                    med_cc = res.get("medicationCodeableConcept", {})
                    codings = med_cc.get("coding", [])
                    name_str = ""
                    concept_id = ""
                    ontology = ""
                    if codings:
                        name_str = codings[0].get("display", "")
                        concept_id = codings[0].get("code", "")
                        ontology = codings[0].get("system", "")
                    if not name_str:
                        name_str = med_cc.get("text") or _clean_ref_id(res.get("medicationReference", {}).get("reference")) or f"Medication {res_id}"

                    subj_ref = _clean_ref_id(res.get("subject", {}).get("reference"))
                    authored_on = res.get("authoredOn")
                    valid_period_start = res.get("dispenseRequest", {}).get("validityPeriod", {}).get("start")
                    valid_period_end = res.get("dispenseRequest", {}).get("validityPeriod", {}).get("end")
                    start_date = authored_on or valid_period_start

                    nodes.append(
                        GraphNodeSpec(
                            node_id=med_node_id,
                            label="Medication",
                            properties={
                                "id": med_node_id,
                                "name": name_str,
                                "normalized_name": name_str,
                                "concept_id": concept_id,
                                "ontology": ontology,
                                "status": res.get("status"),
                                "patient_id": subj_ref,
                                "tenant_id": tenant,
                                "start_date": _iso_timestamp(start_date),
                                "end_date": _iso_timestamp(valid_period_end),
                                "extraction_method": "fhir",
                                "created_at": created_time_iso,
                            },
                        )
                    )

                    if subj_ref:
                        pat_node_id = f"tenant:{tenant}:patient:{subj_ref}"
                        edges.append(
                            GraphEdgeSpec(
                                source_id=pat_node_id,
                                target_id=med_node_id,
                                relationship_type="TOOK_MEDICATION",
                                start_date=_iso_timestamp(start_date),
                                end_date=_iso_timestamp(valid_period_end),
                                properties={
                                    "edge_key": f"patient:{subj_ref}:took_med:{res_id}",
                                    "tenant_id": tenant,
                                    "patient_id": subj_ref,
                                    "extraction_method": "fhir",
                                    "created_at": created_time_iso,
                                },
                            )
                        )

                elif res_type == "Encounter":
                    # Parse Encounter
                    enc_node_id = f"tenant:{tenant}:encounter:{res_id}"
                    class_data = res.get("class", {})
                    name_str = class_data.get("display") or res.get("type", [{}])[0].get("text") or f"Encounter {res_id}"
                    
                    subj_ref = _clean_ref_id(res.get("subject", {}).get("reference"))
                    period_start = res.get("period", {}).get("start")
                    period_end = res.get("period", {}).get("end")

                    nodes.append(
                        GraphNodeSpec(
                            node_id=enc_node_id,
                            label="Encounter",
                            properties={
                                "id": enc_node_id,
                                "name": name_str,
                                "status": res.get("status"),
                                "patient_id": subj_ref,
                                "tenant_id": tenant,
                                "start_date": _iso_timestamp(period_start),
                                "end_date": _iso_timestamp(period_end),
                                "extraction_method": "fhir",
                                "created_at": created_time_iso,
                            },
                        )
                    )

                    if subj_ref:
                        pat_node_id = f"tenant:{tenant}:patient:{subj_ref}"
                        edges.append(
                            GraphEdgeSpec(
                                source_id=pat_node_id,
                                target_id=enc_node_id,
                                relationship_type="RELATED_TO",
                                start_date=_iso_timestamp(period_start),
                                end_date=_iso_timestamp(period_end),
                                properties={
                                    "edge_key": f"patient:{subj_ref}:encounter:{res_id}",
                                    "tenant_id": tenant,
                                    "patient_id": subj_ref,
                                    "extraction_method": "fhir",
                                    "created_at": created_time_iso,
                                },
                            )
                        )

                elif res_type == "DiagnosticReport":
                    # Parse DiagnosticReport
                    code_data = res.get("code", {})
                    codings = code_data.get("coding", [])
                    name_str = ""
                    if codings:
                        name_str = codings[0].get("display", "")
                    if not name_str:
                        name_str = code_data.get("text", f"DiagnosticReport {res_id}")

                    # RAD indicates ImagingStudy
                    categories = res.get("category", [])
                    is_rad = False
                    for cat in categories:
                        for coding in cat.get("coding", []):
                            if coding.get("code") == "RAD":
                                is_rad = True

                    label = "ImagingStudy" if is_rad else "Document"
                    diag_node_id = f"tenant:{tenant}:{label.lower()}:{res_id}"

                    subj_ref = _clean_ref_id(res.get("subject", {}).get("reference"))
                    report_date = res.get("effectiveDateTime") or res.get("issued")
                    enc_ref = _clean_ref_id(res.get("encounter", {}).get("reference"))

                    nodes.append(
                        GraphNodeSpec(
                            node_id=diag_node_id,
                            label=label,
                            properties={
                                "id": diag_node_id,
                                "name": name_str,
                                "status": res.get("status"),
                                "patient_id": subj_ref,
                                "tenant_id": tenant,
                                "start_date": _iso_timestamp(report_date),
                                "extraction_method": "fhir",
                                "created_at": created_time_iso,
                            },
                        )
                    )

                    if subj_ref:
                        pat_node_id = f"tenant:{tenant}:patient:{subj_ref}"
                        rel_type = "RELATED_TO"
                        if label == "Document":
                            rel_type = "HAS_DOCUMENT"
                        edges.append(
                            GraphEdgeSpec(
                                source_id=pat_node_id,
                                target_id=diag_node_id,
                                relationship_type=rel_type,
                                start_date=_iso_timestamp(report_date),
                                end_date=None,
                                properties={
                                    "edge_key": f"patient:{subj_ref}:diagnosticreport:{res_id}",
                                    "tenant_id": tenant,
                                    "patient_id": subj_ref,
                                    "extraction_method": "fhir",
                                    "created_at": created_time_iso,
                                },
                            )
                        )

                    if enc_ref:
                        enc_node_id = f"tenant:{tenant}:encounter:{enc_ref}"
                        edges.append(
                            GraphEdgeSpec(
                                source_id=diag_node_id,
                                target_id=enc_node_id,
                                relationship_type="OCCURRED_DURING",
                                start_date=_iso_timestamp(report_date),
                                end_date=None,
                                properties={
                                    "edge_key": f"diag_report:{res_id}:occurred_during:encounter:{enc_ref}",
                                    "tenant_id": tenant,
                                    "patient_id": subj_ref,
                                    "extraction_method": "fhir",
                                    "created_at": created_time_iso,
                                },
                            )
                        )

                elif res_type == "DocumentReference":
                    # Parse DocumentReference
                    doc_node_id = f"document:{res_id}"
                    name_str = res.get("description")
                    contents = res.get("content", [])
                    if not name_str and contents:
                        name_str = contents[0].get("attachment", {}).get("title")
                    if not name_str:
                        name_str = f"Document {res_id}"

                    subj_ref = _clean_ref_id(res.get("subject", {}).get("reference"))
                    doc_date = res.get("date")

                    nodes.append(
                        GraphNodeSpec(
                            node_id=doc_node_id,
                            label="Document",
                            properties={
                                "id": doc_node_id,
                                "name": name_str,
                                "document_id": res_id,
                                "status": res.get("status"),
                                "patient_id": subj_ref,
                                "tenant_id": tenant,
                                "start_date": _iso_timestamp(doc_date),
                                "extraction_method": "fhir",
                                "created_at": created_time_iso,
                            },
                        )
                    )

                    if subj_ref:
                        pat_node_id = f"tenant:{tenant}:patient:{subj_ref}"
                        edges.append(
                            GraphEdgeSpec(
                                source_id=pat_node_id,
                                target_id=doc_node_id,
                                relationship_type="HAS_DOCUMENT",
                                start_date=_iso_timestamp(doc_date),
                                end_date=None,
                                properties={
                                    "edge_key": f"patient:{subj_ref}:docref:{res_id}",
                                    "tenant_id": tenant,
                                    "patient_id": subj_ref,
                                    "extraction_method": "fhir",
                                    "created_at": created_time_iso,
                                },
                            )
                        )

            except Exception as e:
                logger.error(f"Error parsing FHIR resource: {e}", exc_info=True)
                continue

        # Persist the collected subgraph nodes and edges
        result = await temporal_graph_service._persist_subgraph(nodes=nodes, edges=edges)
        return result


fhir_ingestion_service = FHIRIngestionService()
