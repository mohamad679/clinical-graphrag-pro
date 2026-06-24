# Cost Estimation and Pricing

This document details how LLM usage costs are tracked and projected across various models in Clinical GraphRAG Pro.

---

## 1. Cost Estimator Service

Costs are calculated programmatically inside `backend/app/services/cost_estimator.py` using prompt and completion token parameters returned by LLM responses.

### Pricing Structure (per 1,000,000 tokens)
- **Groq Llama 3.3 (70B)**: Input $0.59 | Output $0.79
- **Gemini 2.0 Flash**: Input $0.075 | Output $0.30
- **Gemini 1.5 Pro**: Input $1.25 | Output $5.00
- **Local Models (Ollama, llama.cpp, HF)**: $0.00 (Free)

---

## 2. Projecting Scenarios

To view estimated pricing projections across 100, 1k, and 10k query volumes, run:

```bash
python3 backend/scripts/estimate_cost.py
```

### Estimated Scenarios Table (USD)

| Model Scenario | 100 Queries | 1,000 Queries | 10,000 Queries |
| :--- | :--- | :--- | :--- |
| **Retrieval-Only** | $0.00 | $0.00 | $0.00 |
| **Local LLM Mode** | $0.00 | $0.00 | $0.00 |
| **Groq Llama 3.3** | $1.12 | $11.22 | $112.20 |
| **Gemini 2.0 Flash** | $0.20 | $2.03 | $20.25 |
| **Gemini 1.5 Pro** | $3.38 | $33.75 | $337.50 |

*Assumptions: RAG prompts average 1,500 tokens (grounded document context + safety rules); answers average 300 tokens.*
