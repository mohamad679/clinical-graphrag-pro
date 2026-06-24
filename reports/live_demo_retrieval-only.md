# Clinical GraphRAG Pro - Live Demo Report
**LLM Provider:** `retrieval-only`
**Model Name:** `default`
**Date Generated:** 2026-05-27 15:05:49

---

## Case Query [1]: FACTUAL
**Query:** *"Has patient John Doe (ID: pat-100) been diagnosed with Essential Hypertension?"*
**Answer:**
Retrieval-only mode: LLM answer generation is bypassed.

Retrieved Grounded Evidence:
[GRAPH1] (Document: Clinical Knowledge Graph): [STRUCTURED CLINICAL KNOWLEDGE GRAPH CONTEXT]
Patient ID: pat-100

Conditions:
- SYNTHETIC: Chronic Obstructive Pulmonar...

**Confidence Score:** `1.0`
**Execution Latency:** `183 ms`
**Abstention Triggered:** `False`
**Validation Status:** `PASSED`

### Citations & Grounded References:
- **[GRAPH1]** (Graph) in `Clinical Knowledge Graph` (Chunk: `graph-patient-profile-pat-100`)

### Retrieved Excerpts:
- **[GRAPH1]** (Relevance: `1.00`): *"[STRUCTURED CLINICAL KNOWLEDGE GRAPH CONTEXT]
Patient ID: pat-100

Conditions:
- SYNTHETIC: Chronic Obstructive Pulmonary Disease: active since 2025-1..."*

---

## Case Query [2]: ABSTENTION
**Query:** *"What is patient John Doe's orbital space telemetry reading?"*
**Answer:**
I do not have enough evidence in the provided documents to answer this safely.

Clinical GraphRAG Pro provides decision support only. It does not replace clinician judgment, primary literature review, or institution-specific protocols.

**Confidence Score:** `0.0`
**Execution Latency:** `102 ms`
**Abstention Triggered:** `True`
**Validation Status:** `PASSED`

---

## Case Query [3]: MEDICATION_TEMPORAL
**Query:** *"List the vital signs and active medications recorded for patient John Doe (ID: pat-100)."*
**Answer:**
Retrieval-only mode: LLM answer generation is bypassed.

Retrieved Grounded Evidence:
[GRAPH1] (Document: Clinical Knowledge Graph): [STRUCTURED CLINICAL KNOWLEDGE GRAPH CONTEXT]
Patient ID: pat-100

Conditions:
- SYNTHETIC: Chronic Obstructive Pulmonar...

**Confidence Score:** `1.0`
**Execution Latency:** `123 ms`
**Abstention Triggered:** `False`
**Validation Status:** `PASSED`

### Citations & Grounded References:
- **[GRAPH1]** (Graph) in `Clinical Knowledge Graph` (Chunk: `graph-patient-profile-pat-100`)

### Retrieved Excerpts:
- **[GRAPH1]** (Relevance: `1.00`): *"[STRUCTURED CLINICAL KNOWLEDGE GRAPH CONTEXT]
Patient ID: pat-100

Conditions:
- SYNTHETIC: Chronic Obstructive Pulmonary Disease: active since 2025-1..."*

---

### Safety & Compliance Notice
⚠️ **Disclaimer:** Clinical GraphRAG Pro provides decision support only. It does not replace clinician judgment, primary literature review, or institution-specific protocols.