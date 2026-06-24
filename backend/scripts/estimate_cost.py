#!/usr/bin/env python3
"""
Cost Estimation Modeller for Clinical GraphRAG Pro.
Simulates LLM api charges across 100, 1k, and 10k query volumes.
"""

import sys
import os

# Align python path to backend root
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.cost_estimator import calculate_llm_cost, PRICING_TABLE


def print_estimate_report():
    print("=" * 70)
    print("           CLINICAL GRAPHRAG PRO - COST ESTIMATION REPORT")
    print("=" * 70)
    print("\n[Pricing Table (USD per 1,000,000 tokens)]:")
    for model, rates in PRICING_TABLE.items():
        print(f"  - {model:<30}: Input: ${rates[0]:.3f} | Output: ${rates[1]:.3f}")

    # Standard model assumptions
    rag_prompt_tokens = 1500
    rag_completion_tokens = 300

    scenarios = [100, 1000, 10000]

    print("\n" + "=" * 70)
    print(f"{'Scenario':<25} | {'100 Qs':<12} | {'1,000 Qs':<12} | {'10,000 Qs':<12}")
    print("-" * 70)

    # 1. Retrieval Only (no LLM)
    print(f"{'Retrieval Only':<25} | {'$0.00':<12} | {'$0.00':<12} | {'$0.00':<12}")

    # 2. Local LLM Mode (Ollama, llama_cpp, local_hf)
    print(f"{'Local LLM Mode (Ollama/HF)':<25} | {'$0.00':<12} | {'$0.00':<12} | {'$0.00':<12}")

    # 3. RAG with Groq Llama 3.3-70b
    groq_model = "llama-3.3-70b-versatile"
    groq_cost_1 = calculate_llm_cost("groq", groq_model, rag_prompt_tokens, rag_completion_tokens)
    groq_c = float(groq_cost_1) if isinstance(groq_cost_1, float) else 0.0
    print(f"{'RAG with Groq (70B)':<25} | ${groq_c*100:<11.2f} | ${groq_c*1000:<11.2f} | ${groq_c*10000:<11.2f}")

    # 4. RAG with Gemini 2.0 Flash
    gemini_model = "gemini-2.0-flash"
    gemini_cost_1 = calculate_llm_cost("gemini", gemini_model, rag_prompt_tokens, rag_completion_tokens)
    gemini_c = float(gemini_cost_1) if isinstance(gemini_cost_1, float) else 0.0
    print(f"{'RAG with Gemini Flash':<25} | ${gemini_c*100:<11.2f} | ${gemini_c*1000:<11.2f} | ${gemini_c*10000:<11.2f}")

    # 5. RAG with Gemini Pro
    gemini_pro_model = "gemini-1.5-pro"
    gemini_pro_cost_1 = calculate_llm_cost("gemini", gemini_pro_model, rag_prompt_tokens, rag_completion_tokens)
    gemini_pro_c = float(gemini_pro_cost_1) if isinstance(gemini_pro_cost_1, float) else 0.0
    print(f"{'RAG with Gemini Pro':<25} | ${gemini_pro_c*100:<11.2f} | ${gemini_pro_c*1000:<11.2f} | ${gemini_pro_c*10000:<11.2f}")

    # 6. RAG with Reranking (costs same as normal RAG as local reranker is CPU-based MiniLM)
    print(f"{'RAG with Local Reranking':<25} | (Same as selected cloud LLM since reranker runs locally)")

    print("=" * 70)
    print("\nAssumptions:")
    print(f"  - RAG prompt size: {rag_prompt_tokens} tokens (context + system rules)")
    print(f"  - RAG completion size: {rag_completion_tokens} tokens")
    print("  - Reranker runs on local MiniLM model (no direct external API charges)")
    print("  - Local LLM runs via Ollama/llama.cpp (no external API charges)")
    print("=" * 70)


if __name__ == "__main__":
    print_estimate_report()
