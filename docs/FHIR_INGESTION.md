# FHIR Ingestion Documentation

This document describes the lightweight FHIR ingestion layer of Clinical GraphRAG Pro, outlining the supported resource subset, data mapping rules, and architectural limitations.

## Supported FHIR Resources

The ingestion layer supports a practical subset of FHIR resources:
1. **Patient**: Maps to `Patient` node. Stores birthdate, gender, name.
2. **Condition**: Maps to `Condition` node. Links Patient via `HAS_CONDITION`. Extracts codes, onset date, abatement date, and clinical status.
3. **Observation**: Maps to `LabResult` (if categorized under laboratory) or `Observation` (otherwise). Links Patient via `HAS_LAB_RESULT` or `HAS_FINDING`. Links Encounter via `OCCURRED_DURING`. Extracts numeric values, units, and timestamps.
4. **MedicationRequest**: Maps to `Medication` node. Links Patient via `TOOK_MEDICATION`. Extracts RxNorm code, status, authored date, and validity period.
5. **Encounter**: Maps to `Encounter` node. Links Patient via `RELATED_TO`. Extracts status, class, start/end dates.
6. **DiagnosticReport**: Maps to `ImagingStudy` (if radiology) or `Document` (otherwise). Links Patient via `HAS_DOCUMENT` / `RELATED_TO`. Links Encounter via `OCCURRED_DURING`.
7. **DocumentReference**: Maps to `Document` node. Links Patient via `HAS_DOCUMENT`. Extracts title and date.

---

## Data Mapping & Provenance Rules

- **Source ID Preservation**: The FHIR resource `id` is directly preserved as part of the internal graph node ID (e.g., `tenant:{tenant}:condition:{fhir_id}`).
- **Patient Reference Preservation**: References (e.g., `subject.reference = "Patient/pat-1"`) are stripped and mapped to the patient's internal node `tenant:{tenant}:patient:pat-1`.
- **Date Conversion**: All resource dates (`onsetDateTime`, `effectiveDateTime`, `authoredOn`, etc.) are processed through the robust date parser and stored as ISO 8601 UTC timestamps.
- **Provenance Properties**: All ingested FHIR resources are marked with `"extraction_method": "fhir"` and `"confidence": "High"` inside the properties payload.

---

## How to Ingest FHIR Data

You can upload FHIR resources (single or Bundle) using the POST API endpoint:

```bash
curl -X POST http://localhost:8000/api/graph/fhir/ingest \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d @backend/data/fhir_samples/bundle_sample.json
```

---

## Interoperability & Compliance Disclaimer

> [!WARNING]
> **THIS IS NOT AN HL7 FHIR COMPLIANT SERVER.**
> 1. This system does not support full FHIR operations (no FHIR REST Search, no patch, no validation schemas).
> 2. It accepts valid FHIR JSON payloads and maps them to a simplified relational/property graph model.
> 3. Payload validation is basic and does not check profile compliance (e.g., US Core profiles).
