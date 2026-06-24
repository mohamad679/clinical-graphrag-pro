# Clinical Graph Schema Documentation

This document describes the standardized schema of the Clinical GraphRAG knowledge graph, including the node types, edge types, provenance tracking fields, and temporal reasoning model.

## Supported Node Types

The knowledge graph standardizes clinical entities into the following node labels:
- **Patient**: Represents a patient entity. Node ID: `tenant:{tenant}:patient:{id}`.
- **Encounter**: Represents a healthcare encounter/visit. Node ID: `tenant:{tenant}:encounter:{id}`.
- **Document**: Represents a source clinical document. Node ID: `document:{id}`.
- **Chunk**: Represents a specific text chunk of a clinical document. Node ID: `chunk:{chunk_id}`.
- **Condition**: Represents a diagnosed condition, disease, or disorder (e.g., SNOMED CT, ICD-10 mapped).
- **Medication**: Represents prescribed or administered drugs (e.g., RxNorm mapped).
- **LabResult**: Represents laboratory values and test results.
- **ImagingStudy**: Represents radiology imaging studies (e.g., CT, MRI, X-ray).
- **Finding**: Represents symptoms, signs, and physical findings.
- **Procedure**: Represents surgical or diagnostic procedures.
- **Observation**: Represents clinical measurements, vital signs, or other diagnostic observations.

## Supported Edge Types

Relationships between nodes use the following standardized types:
- **HAS_DOCUMENT**: Links a `Patient` node to a `Document` node.
- **HAS_CHUNK**: Links a `Document` node to its constituent `Chunk` nodes.
- **MENTIONS_CONDITION**: Links a `Chunk` node to a `Condition` node.
- **MENTIONS_MEDICATION**: Links a `Chunk` node to a `Medication` node.
- **HAS_LAB_RESULT**: Links a `Patient` (or `Encounter` or `Chunk`) node to a `LabResult` node.
- **HAS_FINDING**: Links a `Patient` (or `Encounter` or `Chunk`) node to a `Finding` node.
- **OCCURRED_DURING**: Links an `Observation`, `LabResult`, or `DiagnosticReport` node to an `Encounter`.
- **EVIDENCED_BY**: Links a `Condition` node to an `Observation` or `LabResult` supporting the diagnosis.
- **RELATED_TO**: A general relationship (e.g., Medication to Condition) containing specific confidence levels and text evidence attributes.

---

## Provenance Model

Every ingested or extracted entity and relationship contains deep provenance properties in the SQL or Neo4j database properties payload:
- **patient_id**: The patient identifier (for strict multi-tenancy scoping).
- **tenant_id**: The organization or tenant scope.
- **source_document_id**: The unique UUID of the source document.
- **source_chunk_id**: The specific chunk identifier where the entity/relationship was found.
- **source_text_span**: The character offset boundaries `{"start": offset_start, "end": offset_end}` of the entity in the document text.
- **extraction_method**: The pipeline stage that extracted the data (e.g., `"scispacy"`, `"curated"`, `"llm"`, `"fhir"`).
- **confidence**: Extraction or link confidence level (e.g., `"High"`, `"Medium"`, `"Low"` or float between `0.0` and `1.0`).
- **created_at**: Ingestion run timestamp.

---

## Temporal Reasoning Model

The clinical graph implements a robust temporal tracking model:
1. **Date Parsing**: Date strings (in ISO 8601, timezone-aware, or date-only formats) are parsed using a robust parser that prevents defaults to active on formatting errors.
2. **Status Classification**: Each edge and temporal relationship is classified into one of the following statuses relative to a query target date:
   - `active`: The condition/medication is current (start date <= query date, and end date is null or >= query date).
   - `resolved`: The condition has ended (end date is before query date).
   - `future`: The condition starts after the query date.
   - `unknown`: Missing start date prevents determining active status. Unknown dates do not default to active.
3. **Temporal Confidence**:
   - `High`: Both start and end dates are fully known.
   - `Medium`: Only the start date is known.
   - `Low`: Dates are missing or invalid.

---

## Non-Clinical Disclaimer

> [!CAUTION]
> **THIS IS NOT CLINICAL-GRADE INTEROPERABILITY SOFTWARE.**
> This schema and its associated parsers are designed strictly for portfolio demonstration purposes:
> 1. It lacks validation against standard vocabularies (no live SNOMED/RxNorm terminology server integration).
> 2. It does not enforce complete HIPAA or HL7 conformance rules.
> 3. It utilizes simplified heuristic NLP extractions which can hallucinate relations.
> **DO NOT USE THIS SYSTEM FOR REAL-WORLD CLINICAL DECISION SUPPORT OR INPATIENT CARE.**
