# Synthetic Clinical Data Generator

The synthetic data generator produces deterministic clinical datasets for demoing, debugging, and testing safety overrides.

---

## 1. Running the Data Generator

Execute the script from the repository root:

```bash
python3 scripts/generate_synthetic_clinical_data.py --seed 42 --output_dir sample_data/synthetic
```

---

## 2. Generated Outputs

All generated records are stored under the target output directory and are prefixed/tagged as `SYNTHETIC / DEMO DATA`:
- **`patients.json`**: An array of mock patients.
- **`fhir_bundle.json`**: A transaction bundle of Patient, Condition, MedicationRequest, and Observation records.
- **`patient_clinical_notes.txt`**: Plain text clinical notes summarizing mock history.
- **`adversarial_safety_test.txt`**: A special document containing system prompt injection payloads to test safety gates.

---

## 3. Usage inside the Stack

These synthetic notes and FHIR bundles can be uploaded via the browser UI to verify:
- Semantic search retrieval bounds.
- Critic prompt injection safety triggers (specifically via the `adversarial_safety_test.txt` note).
- Graph entity normalization ingestion flows.
