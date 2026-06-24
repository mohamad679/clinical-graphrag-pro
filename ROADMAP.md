# Clinical GraphRAG Pro Roadmap

This document outlines the multi-horizon development roadmap for Clinical GraphRAG Pro. It establishes priority, complexity, impact, dependencies, and acceptance criteria for features across three execution horizons.

---

## Horizon 1: Short-Term (1 - 2 Months)

### 1. Robust Agent Safety Routing & Guardrails
*   **Description**: Implement deterministic input/output guardrail checks (such as NeMo Guardrails or Llama Guard) to filter non-clinical queries or toxic/adversarial prompt injections before they reach the agent system.
*   **Priority**: High
*   **Impact**: High
*   **Complexity**: Medium
*   **Dependencies**: Backend configuration system, LLM service.
*   **Acceptance Criteria**:
    - Programmatic rejection of non-medical prompts with a custom status code.
    - Zero leakage of system instructions or retrieval prompts when tested with standard jailbreak datasets.

### 2. Local GPU Model Workloads & Quantization
*   **Description**: Extend the local LLM engine support to automatically run GGUF quantized models (e.g., Llama-3-8B-Instruct-Q4_K_M) on local GPU hardware via unified llama.cpp/Ollama integrations.
*   **Priority**: Medium
*   **Impact**: Medium
*   **Complexity**: Medium
*   **Dependencies**: Local llama.cpp/Ollama environment.
*   **Acceptance Criteria**:
    - Automated detection of Apple Silicon (Metal) or NVIDIA CUDA acceleration in `/api/health/detailed`.
    - Token generation speeds exceeding 15 tokens/sec for local 8B models.

---

## Horizon 2: Medium-Term (3 - 6 Months)

### 3. Interactive Cost Visibility & Telemetry Dashboards
*   **Description**: Expose token utilization, query costs, and cache hit rate telemetry in an interactive React/HTML dashboard on the frontend, retrieving data from Prometheus metrics.
*   **Priority**: High
*   **Impact**: High
*   **Complexity**: Medium
*   **Dependencies**: Prometheus API, frontend metrics collector.
*   **Acceptance Criteria**:
    - Visual rendering of query counts, total cost (in USD), and cache hit ratios.
    - Exportable metrics reports in CSV or JSON formats.

### 4. Advanced Evaluation Tooling & Synthetic Benchmarks
*   **Description**: Expand the evaluation harness with automated generation of synthetic patient cases and clinical Q&A pairs (leveraging clinical guidelines and mock EHRs) to evaluate new model iterations.
*   **Priority**: Medium
*   **Impact**: Medium
*   **Complexity**: High
*   **Dependencies**: Synthetic clinical data generators, evaluation runner service.
*   **Acceptance Criteria**:
    - Automated creation of 100+ multi-turn clinical test cases.
    - Execution of regression metrics (Recall, MRR, Citation coverage) with statistical variance reporting.

---

## Horizon 3: Long-Term (6 - 12+ Months)

### 5. FHIR-Compliant Bundle Export & Data Interoperability
*   **Description**: Implement full support for exporting clinical graphs and patient profiles into HL7 FHIR (JSON/XML) bundles conforming to standard US Core Profiles.
*   **Priority**: Medium
*   **Impact**: High
*   **Complexity**: High
*   **Dependencies**: PostgreSQL database schema, FHIR ingestion service.
*   **Acceptance Criteria**:
    - Successful validation of exported JSON bundles using the official HL7 FHIR validator tool.
    - Coverage of key resources: Patient, Encounter, Condition, MedicationRequest, Observation, DiagnosticReport.

### 6. Horizontal Retrieval Scaling & Distributed Vector Search
*   **Description**: Migrate from local FAISS/in-memory search to a distributed Qdrant or Milvus cluster, establishing horizontal scaling of clinical text chunks and indices.
*   **Priority**: Low
*   **Impact**: High
*   **Complexity**: High
*   **Dependencies**: Production hosting environment.
*   **Acceptance Criteria**:
    - Search latencies under 20ms across a corpus of 10,000,000+ clinical document chunks.
    - Zero data loss or query downtime during cluster node scaling.
