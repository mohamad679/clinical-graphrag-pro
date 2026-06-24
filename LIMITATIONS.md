# Limitations

Clinical GraphRAG Pro is a clinical AI systems portfolio project, not a clinical product.

This project is for educational and portfolio demonstration purposes only. It is not a medical device, not clinically validated, and must not be used for diagnosis, treatment, triage, medication decisions, or real patient care. All outputs require review by qualified clinical professionals.

## Clinical Scope

- No prospective clinical validation study is included.
- No claim is made that outputs improve outcomes, reduce errors, or are safe for clinical use.
- Sample documents and benchmark questions are synthetic/demo materials.
- The workflow orchestration layer is for inspectable tool execution, not autonomous clinical decision-making.

## Evaluation Scope

- The committed MedQA-style benchmark run did not complete because provider authentication failed.
- No MedQA accuracy, RAG improvement, or clinical quality score is claimed.
- Retrieval benchmark numbers come from small internal datasets and should be treated as regression/demo signals only.
- RAGAS evaluation requires valid LLM credentials and should be rerun in the target environment before citing results.

## Security and Compliance Scope

- The repository includes authentication, RBAC, audit logging, file validation, and configuration checks.
- These controls do not constitute HIPAA compliance, SOC 2 readiness, or a regulated production security program.
- Production use would require external controls such as managed secrets, TLS, network isolation, backups, retention policy, incident response, formal access reviews, and legal/compliance review.

## Operational Scope

- Local FAISS indexes, uploads, caches, local databases, and coverage files are generated artifacts and are not intended to be committed.
- Docker Compose examples are development and production-inspired references, not a fully managed production deployment.
- The default deployment is single-node and not designed for high availability.
