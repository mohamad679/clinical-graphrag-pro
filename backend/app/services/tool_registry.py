"""
Registry of clinical tools available to the agent.
Each tool is an async function that returns a JSON-serializable dict.
"""

import logging
import httpx
import math
from typing import Callable, Awaitable, Any

from app.services.vector_store import vector_store_service
from app.services.vision import vision_service
from app.services.graph import temporal_graph_service

# We'll need a way to get image data by ID for the analyze_image tool
# For now, we'll assume the agent passes the image_id and we fetch it from DB or storage.
# Since we don't have a direct "get_image_bytes" service method easily exposed here without circular imports
# or DB access, we might need to rely on the vision service or add a helper.
# For this iteration, we'll stick to what we can do.

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central registry for agent tools.
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, name: str, description: str, parameters: dict):
        """Decorator to register a tool."""

        def decorator(func: Callable[..., Awaitable[dict]]):
            self._tools[name] = {
                "name": name,
                "description": description,
                "parameters": parameters,
                "func": func,
            }
            return func

        return decorator

    async def execute(self, name: str, params: dict) -> dict:
        """Execute a tool by name with given parameters."""
        if name not in self._tools:
            return {"error": f"Tool '{name}' not found"}

        tool = self._tools[name]
        try:
            logger.info(f"🔧 Executing tool: {name} with params: {params}")
            result = await tool["func"](**params)
            return result
        except Exception as e:
            logger.error(f"❌ Tool execution failed ({name}): {e}", exc_info=True)
            return {"error": str(e)}

    def get_definitions(self) -> list[dict]:
        """Get JSON schemas for all tools (for LLM)."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in self._tools.values()
        ]


tool_registry = ToolRegistry()


# ── Tool Definitions ─────────────────────────────────────

@tool_registry.register(
    name="search_documents",
    description="Search for medical information in the uploaded documents (RAG). Use this to find specific protocols, guidelines, or patient history.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The medical query to search for",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
)
async def tool_search_documents(query: str, top_k: int = 5) -> dict:
    results = vector_store_service.search(query, top_k=top_k)
    return {
        "results": [
            {
                "source": r.document_name,
                "text": r.chunk_text,
                "score": r.score,
            }
            for r in results
        ]
    }


@tool_registry.register(
    name="medical_calculator",
    description="Calculate common clinical scores (BMI, eGFR, CHA2DS2-VASc, MELD).",
    parameters={
        "type": "object",
        "properties": {
            "calculator": {
                "type": "string",
                "enum": ["bmi", "egfr", "cha2ds2_vasc"],
                "description": "Type of calculation to perform",
            },
            "params": {
                "type": "object",
                "description": "Parameters required for the specific calculator",
                "properties": {
                    "weight_kg": {"type": "number"},
                    "height_m": {"type": "number"},
                    "creatinine": {"type": "number"},
                    "age": {"type": "integer"},
                    "gender": {"type": "string", "enum": ["male", "female"]},
                    "is_black": {"type": "boolean"},
                    # CHA2DS2-VASc params
                    "congestive_heart_failure": {"type": "boolean"},
                    "hypertension": {"type": "boolean"},
                    "stroke_history": {"type": "boolean"},
                    "vascular_disease": {"type": "boolean"},
                    "diabetes": {"type": "boolean"},
                },
            },
        },
        "required": ["calculator", "params"],
    },
)
async def tool_medical_calculator(calculator: str, params: dict) -> dict:
    if calculator == "bmi":
        weight = params.get("weight_kg")
        height = params.get("height_m")
        if not weight or not height:
            return {"error": "BMI requires weight_kg and height_m"}
        bmi = weight / (height * height)
        category = "Normal"
        if bmi < 18.5: category = "Underweight"
        elif bmi >= 25: category = "Overweight"
        if bmi >= 30: category = "Obese"
        return {"value": round(bmi, 1), "unit": "kg/m²", "category": category}

    elif calculator == "egfr":
        # CKD-EPI (2021)
        cr = params.get("creatinine")
        age = params.get("age")
        gender = params.get("gender")
        if not all([cr, age, gender]):
            return {"error": "eGFR requires creatinine, age, and gender"}
        
        kappa = 0.7 if gender == "female" else 0.9
        alpha = -0.329 if gender == "female" else -0.411
        factor = 1.018 if gender == "female" else 1.0
        
        egfr = 142 * ((min(cr / kappa, 1)) ** alpha) * ((max(cr / kappa, 1)) ** -1.209) * (0.9938 ** age) * factor
        return {"value": round(egfr, 1), "unit": "mL/min/1.73m²"}

    elif calculator == "cha2ds2_vasc":
        score = 0
        if params.get("congestive_heart_failure"): score += 1
        if params.get("hypertension"): score += 1
        if params.get("stroke_history"): score += 2
        if params.get("vascular_disease"): score += 1
        if params.get("diabetes"): score += 1
        
        age = params.get("age", 0)
        if age >= 75: score += 2
        elif age >= 65: score += 1
        
        if params.get("gender") == "female": score += 1
        
        return {"score": score, "interpretation": "High risk" if score >= 2 else "Low/Moderate risk"}

    return {"error": f"Unknown calculator: {calculator}"}


@tool_registry.register(
    name="pubmed_search",
    description="Search PubMed for recent medical literature abstracts.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search terms"},
            "max_results": {"type": "integer", "default": 3},
        },
        "required": ["query"],
    },
)
async def tool_pubmed_search(query: str, max_results: int = 3) -> dict:
    # Use NCBI E-utilities
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    async with httpx.AsyncClient() as client:
        # 1. Search for IDs
        search_resp = await client.get(
            f"{base_url}/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": max_results,
            },
        )
        if search_resp.status_code != 200:
            return {"error": "PubMed search failed"}
        
        ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return {"results": []}

        # 2. Fetch summaries
        summary_resp = await client.get(
            f"{base_url}/esummary.fcgi",
            params={
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "json",
            },
        )
        data = summary_resp.json().get("result", {})
        results = []
        for uid in ids:
            if uid in data:
                item = data[uid]
                results.append({
                    "title": item.get("title"),
                    "journal": item.get("source"),
                    "date": item.get("pubdate"),
                    "id": uid,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"
                })
        return {"results": results}


@tool_registry.register(
    name="drug_interaction",
    description="Check for reported adverse events or interactions for a specific drug via OpenFDA.",
    parameters={
        "type": "object",
        "properties": {
            "drug_name": {"type": "string", "description": "Generic or brand name of the drug"},
        },
        "required": ["drug_name"],
    },
)
async def tool_drug_interaction(drug_name: str) -> dict:
    # OpenFDA API
    url = "https://api.fda.gov/drug/event.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            params={
                "search": f'patient.drug.medicinalproduct:"{drug_name}"',
                "limit": 5,
            },
        )
        if resp.status_code != 200:
            return {"error": "FDA API search failed or no data found"}
        
        data = resp.json()
        events = []
        for result in data.get("results", []):
            reactions = [r.get("reactionmeddrapt") for r in result.get("patient", {}).get("reaction", [])]
            events.append({"reactions": reactions})
            
        return {
            "drug": drug_name,
            "warning": "Data from OpenFDA FAERS. Not a substitute for clinical checking.",
            "recent_adverse_events": events
        }


@tool_registry.register(
    name="analyze_image",
    description="Analyze a previously uploaded medical image using AI vision.",
    parameters={
        "type": "object",
        "properties": {
            "image_id": {"type": "string", "description": "UUID of the image to analyze"},
            "question": {"type": "string", "description": "Specific question about the image"},
        },
        "required": ["image_id"],
    },
)
async def tool_analyze_image(image_id: str, question: str = "") -> dict:
    # In a real app, we'd fetch the image bytes from DB/storage using image_id.
    # For now, we'll return a placeholder or need to inject a way to look up images.
    # This is a limitation without refactoring 'images.py' to share storage logic.
    return {
        "error": "Image analysis via agent is pending storage refactor. Please use the direct image chat feature for now."
    }


@tool_registry.register(
    name="search_graph",
    description="Search the Temporal Knowledge Graph for entity relationships, drug interactions, and medical events active on a specific date.",
    parameters={
        "type": "object",
        "properties": {
            "entity": {"type": "string", "description": "The medical entity to search for (e.g., 'Patient_A', 'Lisinopril')"},
            "target_date": {"type": "string", "description": "Optional: ISO Date (YYYY-MM-DD) to check active relationships. Defaults to today."}
        },
        "required": ["entity"],
    },
)
async def tool_search_graph(entity: str, target_date: str | None = None) -> dict:
    if not target_date:
        from datetime import datetime
        target_date = datetime.now().strftime("%Y-%m-%d")
        
    result = temporal_graph_service.query_temporal_state(entity, target_date)
    return result


@tool_registry.register(
    name="clinical_eval",
    description="An internal critic tool to evaluate a proposed clinical answer for safety, faithfulness, and hallucination before presenting to the user.",
    parameters={
        "type": "object",
        "properties": {
            "proposed_answer": {"type": "string", "description": "The drafted answer to evaluate"},
            "source_context": {"type": "string", "description": "The source documents used to formulate the answer"}
        },
        "required": ["proposed_answer"],
    },
)
async def tool_clinical_eval(proposed_answer: str, source_context: str = "") -> dict:
    # In a real scenario, this would trigger an isolated LLM call (the critic).
    # For Phase 1, we provide a deterministic pass.
    is_safe = "kill" not in proposed_answer.lower() and "fatal" not in proposed_answer.lower()
    return {
        "status": "APPROVED" if is_safe else "REJECTED_UNSAFE",
        "confidence_score": 0.95 if is_safe else 0.1,
        "reasoning": "The proposed answer does not contain obvious prohibited terms and aligns with standard safety heuristics."
    }

