"""
RAGAS Evaluation Pipeline for Clinical GraphRAG Pro.
Evaluates the core RAG system based on Faithfulness, Answer Relevancy, and Context Precision.
"""

import os
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
)

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

load_dotenv()


def get_llm_and_embeddings():
    """Initialize Langchain LLM and Embeddings based on env vars."""
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    
    # Needs to return standard Langchain models that RAGAS accepts
    if provider == "groq":
        from langchain_groq import ChatGroq
        from langchain_community.embeddings import HuggingFaceEmbeddings
        llm = ChatGroq(model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")
        return llm, embeddings
    else:
        # Default to Gemini
        from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
        from langchain_community.embeddings import HuggingFaceEmbeddings
        # RAGAS standard compatibility wrapper for chat models
        llm = ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))
        # You can use Google embeddings or a local HuggingFace embedding for evaluation
        # We will use HuggingFace (matching our GraphRAG standard) to avoid api quota issues
        embeddings = HuggingFaceEmbeddings(model_name=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2"))
        return llm, embeddings


# Simulated RAG system
async def get_rag_response(query: str) -> dict:
    """
    Mock RAG pipeline for the sake of setting up the evaluation harness.
    In real usage, this imports your GraphRAG query function.
    """
    # Simply mocking response
    return {
        "answer": "The patient was prescribed Ceftriaxone and Azithromycin.",
        "contexts": ["The 78-year-old patient was admitted for community-acquired pneumonia. Chest X-ray revealed a right lower lobe consolidation. He was started on IV Ceftriaxone and Azithromycin."]
    }


async def run_evaluation():
    print("Initializing RAGAS Evaluation Pipeline...")
    
    llm, embeddings = get_llm_and_embeddings()
    
    # 1. Load the Golden Dataset
    dataset_path = Path("backend/data/golden_evaluation_dataset.jsonl")
    if not dataset_path.exists():
        print(f"Golden dataset not found at {dataset_path}. Please run generate_golden_dataset.py first.")
        # We'll use mocked data for execution demonstration
        data_records = [
            {
                "question": "What medications was the patient started on for pneumonia?",
                "ground_truth": "IV Ceftriaxone and Azithromycin",
                "contexts": ["The 78-year-old patient was admitted for community-acquired pneumonia. Chest X-ray revealed a right lower lobe consolidation. He was started on IV Ceftriaxone and Azithromycin."],
                "answer": "The patient was prescribed Ceftriaxone and Azithromycin."
            },
            {
                 "question": "What did the urine dipstick show for the 29-year-old pregnant female?",
                 "ground_truth": "3+ protein",
                 "contexts": ["Patient is a 29-year-old pregnant female at 32 weeks gestation presenting with elevated blood pressure (160/110 mmHg), headache, and visual disturbances. Urine dipstick shows 3+ protein. She is diagnosed with severe preeclampsia and started on a Magnesium Sulfate drip for seizure prophylaxis."],
                 "answer": "Urine dipstick showed 3+ protein."
            }
        ]
        dataset_size = len(data_records)
    else:
        # Load from file
        data_records = []
        with open(dataset_path, "r", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                # Ensure the 'answer' field is generated so Ragas can evaluate it
                # In a real batch pipeline, you'd generate these on the fly or beforehand
                rag_output = await get_rag_response(record["question"]) 
                record["answer"] = rag_output["answer"]
                # In reality Ragas uses the actual retrieved contexts, not the true contexts
                # We will just pass the ground truth context here for simplicity in dummy run
                record["contexts"] = record.get("contexts", list(rag_output["contexts"]))
                data_records.append(record)
        dataset_size = len(data_records)

    print(f"Evaluating {dataset_size} cases...")

    # RAGAS requires HuggingFace Dataset format
    eval_dataset = Dataset.from_list(data_records)
    
    # 2. Run Evaluation
    # Note: Using subset of metrics for performance and reliability
    try:
        result = evaluate(
            eval_dataset,
            metrics=[
                faithfulness,
                answer_relevancy,
                context_precision,
            ],
            llm=llm,
            embeddings=embeddings,
            raise_exceptions=False,
        )
        scores = result.copy()
        print("\n" + "="*40)
        print("📊 RAGAS EVALUATION METRICS")
        print("="*40)
        # Ragas result is a pandas dict-like object
        for metric_name, value in scores.items():
            # Format nicely, print warnings if below threshold
            warning = ""
            if metric_name == "faithfulness" and value < 0.95:
                warning = "⚠️ (Target: >0.95)"
            elif metric_name == "answer_relevancy" and value < 0.85:
                warning = "⚠️ (Target: >0.85)"
            print(f"{metric_name.capitalize():<20}: {value:.4f} {warning}")
        print("="*40)

        # 3. Store Results in Database / Fallback
        metrics_dict = {k: float(v) for k, v in scores.items()}
        
        try:
            from app.core.database import async_session_maker
            from app.services.evaluation_storage import EvaluationStorageService
            
            storage_service = EvaluationStorageService()
            async with async_session_maker() as session:
                await storage_service.save_evaluation(
                    db=session,
                    evaluation_type="ragas",
                    metrics=metrics_dict,
                    dataset_size=dataset_size,
                    metadata={"test_run": "golden_dataset"}
                )
                print("Successfully logged RAGAS results to storage service.")
        except Exception as e:
            print(f"Database logging failed (DB might not be running), using fallback: {e}")
            from app.services.evaluation_storage import EvaluationStorageService
            storage_service = EvaluationStorageService()
            storage_service._save_to_fallback({
                "evaluation_type": "ragas",
                "metrics": metrics_dict,
                "dataset_size": dataset_size,
                "metadata": {"test_run": "golden_dataset_fallback"},
            })

    except Exception as e:
        print(f"RAGAS evaluation failed: {e}")
        # Could be missing api keys or rate limits during dummy run


if __name__ == "__main__":
    asyncio.run(run_evaluation())
