"""
LLM cost calculation service for Clinical GraphRAG Pro.
Allows estimating pricing dynamically based on model usage.
"""

import logging

logger = logging.getLogger(__name__)

# Configurable price mapping per 1,000,000 tokens.
# Structure: { model_name: (input_price_per_million, output_price_per_million) }
PRICING_TABLE = {
    # Groq Models
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama3-70b-8192": (0.59, 0.79),
    "llama3-8b-8192": (0.05, 0.08),
    
    # Gemini Models
    "gemini-2.0-flash": (0.075, 0.30),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    
    # Local Models (always free)
    "ollama": (0.0, 0.0),
    "llama_cpp": (0.0, 0.0),
    "local_hf": (0.0, 0.0),
}


def calculate_llm_cost(
    provider: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | str:
    """
    Computes the estimated cost of an LLM invocation in USD.
    Returns:
        - float: The cost in USD if pricing is available.
        - str: "unknown" if usage or pricing info is missing.
    """
    if prompt_tokens is None or completion_tokens is None:
        return "unknown"

    provider_clean = provider.strip().lower()
    model_clean = model.strip()

    # Local models are free
    if provider_clean in {"ollama", "llama_cpp", "local_hf"} or "local" in model_clean.lower():
        return 0.0

    # Retrieve pricing rates
    pricing = PRICING_TABLE.get(model_clean)
    if not pricing:
        # Fallback to provider default if exact model not found
        if provider_clean == "groq":
            pricing = PRICING_TABLE["llama-3.3-70b-versatile"]
        elif provider_clean == "gemini":
            pricing = PRICING_TABLE["gemini-2.0-flash"]
        else:
            return "unknown"

    input_rate, output_rate = pricing
    cost = (prompt_tokens / 1_000_000.0 * input_rate) + (completion_tokens / 1_000_000.0 * output_rate)
    return round(cost, 6)
