# Model Card

## Status

Clinical GraphRAG Pro is a portfolio and synthetic-data demonstration project. It is not a standalone trained clinical model, not a medical device, not clinically validated, and not intended for real patient data or autonomous medical reasoning.

## Base Models and Providers

The backend supports provider-backed generation through configured LLM providers and a `retrieval-only` mode for deterministic local checks. Live provider behavior depends on credentials and model availability. Normal tests and CI must not require live provider keys.

Fine-tuning is implemented as a durable workflow scaffold with a real PEFT/LoRA training path, but it is disabled by default and unavailable without the required dependencies, GPU runtime, dataset validation, adapter reload verification, evaluation gate, and inference integration verification.

## Intended Use

- Demonstrate engineering patterns for RAG, scoped retrieval, citations, safe streaming, red-team tests, and observability.
- Run synthetic regression benchmarks and local demos.
- Support code review and architecture discussion.

## Out-of-Scope Use

- Diagnosis, treatment, triage, medication decisions, or patient care.
- Processing real patient data without independent legal, security, clinical, and infrastructure review.
- Claims of HIPAA compliance, GDPR compliance, clinical validation, SOTA performance, or production readiness.

## Evaluation

Evaluation artifacts are synthetic engineering regression artifacts. See [EVALUATION_STATUS.md](EVALUATION_STATUS.md) and [results/retrieval_evaluation_results_20260605T223340Z.md](results/retrieval_evaluation_results_20260605T223340Z.md).

## Safety Controls

The current code includes scoped retrieval, citation validation, safe streaming after full-answer validation, untrusted-evidence formatting, prompt-injection red-team tests, metadata-only observability mode, and DICOM/image upload boundaries. These controls reduce specific engineering risks but do not establish clinical safety.
