# Clinical & Technical Limitations

This document outlines the limitations of the grounding, citation, and safety mechanisms implemented in Clinical GraphRAG Pro. It is critical for developers, clinicians, and reviewers to understand these boundaries before attempting to extend or deploy the system.

> [!CAUTION]
> **No Clinical Validation**: This codebase is a demonstration of AI systems engineering architecture and has NOT undergone clinical validation. It is not approved for diagnostic use, treatment decision support, or direct patient care.

---

## 1. Technical Limitations of RAG Grounding

While the system enforces strict inline citation validation and one-time regeneration steps, several technical limitations remain:

### claim-Level vs. Sentence-Level Verification
- **Syntactic Splitting**: The validation pipeline splits text syntactically to parse citation tokens. It does not perform full semantic semantic-parsing of clinical claims. If a sentence contains two separate medical claims but only cites a source for one of them, the entire sentence is treated as cited, potentially masking an ungrounded claim.
- **Vague Citations**: An LLM can write a medically accurate sentence and cite a document chunk, but the cited chunk might only have a loose or tangential connection to the specific claim. The system validates that the citation *exists* in the context, but it does not perform deep semantic entailment checks to ensure the text *proves* the claim.

### Regeneration Failures
- **LLM Stubbornness**: During regeneration, the LLM is instructed to use stricter grounding. However, under high load or temperature, some models may continue to output ungrounded assertions or hallucinate citation markers. When this occurs, the system's fail-safe is to completely redact the response and return the safe abstention message: *"I do not have enough evidence..."*

---

## 2. Clinical Knowledge Graph Limitations

The integrated knowledge graph context enhances retrieval, but has distinct structural constraints:

### Provenance Limitations
- **Graph Facts without Provenance**: Clinical facts ingested from structured FHIR transactions or legacy systems may lack direct source document and source chunk links. These facts are excluded from answer context by default and cannot support cited claims until provenance is supplied. The system does not dynamically reconstruct missing source evidence.
- **Dynamic State Drift**: If a clinical document is updated or deleted, the corresponding graph nodes must be re-synced. Out-of-sync or stale nodes can lead to discrepancies between the vector database chunks and the graph topology.

---

## 3. Boundary of AI Decision Support

- **No Diagnostic Authority**: The system is designed to surface relevant documentation and summarize grounded facts for a qualified clinician. It does not replace clinical judgment, case-history reviews, or physical examinations.
- **Adversarial Safety**: Despite prompt injection hardening, highly sophisticated adversarial prompt payloads within patient files (e.g. nested instruction injections) could still influence LLM synthesis patterns. The system relies on multi-stage post-generation validation to catch and suppress these outputs before they reach the user.

---

## 4. DICOM and Image Handling Limitations

- **DICOM Disabled by Default**: DICOM upload support is off unless explicitly enabled by configuration.
- **Metadata Scrubbing Is Not Complete De-Identification**: The DICOM scrubber removes known metadata tags and private tags from the configured path, but this does not prove all identifiers are removed.
- **Burned-In Text Is Manual-Review-Only**: The current code does not perform OCR-based removal of names, MRNs, dates, or other identifiers burned into image pixels. DICOM-derived images are marked for manual review before downstream use.
- **Multi-Frame DICOM Is Rejected**: Multi-frame studies are rejected safely rather than decoded partially or silently flattened.
- **Image Analysis Is Not Clinical Validation**: Vision outputs are demo analysis artifacts requiring clinician review. They are not diagnostic findings.
