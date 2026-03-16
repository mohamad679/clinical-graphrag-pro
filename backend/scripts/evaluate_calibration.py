"""
Calibration Error Evaluation Pipeline.
Calculates Expected Calibration Error (ECE) by comparing the AI's stated
confidence against its actual factual accuracy on the golden dataset.
"""

import os
import re
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import numpy as np

load_dotenv()

from app.services.rag import rag_service
from app.services.llm import llm_service
from app.services.evaluation_storage import EvaluationStorageService
from app.core.database import async_session_factory

async def grade_answer(question: str, ground_truth: str, ai_answer: str) -> int:
    """Use LLM-as-a-judge to evaluate correctness. Returns 1 for Correct, 0 for Incorrect."""
    prompt = f"""
You are an expert medical grader.
Question: {question}
Correct Answer (Ground Truth): {ground_truth}
AI Answer: {ai_answer}

Is the AI Answer factually correct and does it capture the essence of the Ground Truth?
Reply with exactly "1" for Yes/Correct or "0" for No/Incorrect.
"""
    try:
        response = await llm_service.generate(user_message=prompt)
        # Extract 1 or 0
        match = re.search(r'\b(0|1)\b', response)
        if match:
            return int(match.group(1))
        return 0
    except Exception as e:
        print(f"Error during grading: {e}")
        return 0

async def run_calibration_eval():
    print("Initiating Calibration Error Evaluation...")
    
    dataset_path = Path("data/golden_evaluation_dataset.jsonl")
    if not dataset_path.exists():
        print(f"Golden dataset not found at {dataset_path}.")
        return

    data_records = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            data_records.append(json.loads(line))

    # Taking a subset for evaluation speed (max 20 questions)
    data_records = data_records[:15]
    total_cases = len(data_records)
    print(f"Loaded {total_cases} cases for testing.")

    results = []
    
    for i, record in enumerate(data_records):
        print(f"Processing question {i+1}/{total_cases}...")
        question = record["question"]
        ground_truth = record.get("ground_truth", "")

        rag_output = await rag_service.query(question=question)
        raw_answer = rag_output.get("answer", "")
        
        # Extract confidence
        confidence = 0.8 # default high confidence if missing
        clean_answer = raw_answer
        match = re.search(r'\[CONFIDENCE:\s*([\d\.]+)\]', raw_answer, re.IGNORECASE)
        if match:
            try:
                confidence = float(match.group(1))
                clean_answer = re.sub(r'\[CONFIDENCE:\s*[\d\.]+\]', '', raw_answer, flags=re.IGNORECASE).strip()
            except ValueError:
                pass
                
        # Constrain confidence bounds
        confidence = max(0.0, min(1.0, confidence))
        
        # Grade correctness
        is_correct = await grade_answer(question, ground_truth, clean_answer)
        
        results.append({
            "confidence": confidence,
            "correct": is_correct
        })

    # Calculate Expected Calibration Error (ECE)
    bins = 10
    bin_boundaries = np.linspace(0, 1, bins + 1)
    ece = 0.0
    
    confidences = np.array([r["confidence"] for r in results])
    accuracies = np.array([r["correct"] for r in results])
    
    reliability_data = [] # For plotting in the UI if needed
    
    for i in range(bins):
        lower = bin_boundaries[i]
        upper = bin_boundaries[i+1]
        
        # Include upper limit for the last bin
        if i == bins - 1:
            in_bin = (confidences >= lower) & (confidences <= upper)
        else:
            in_bin = (confidences >= lower) & (confidences < upper)
            
        bin_count = np.sum(in_bin)
        
        if bin_count > 0:
            bin_acc = np.mean(accuracies[in_bin])
            bin_conf = np.mean(confidences[in_bin])
            weight = bin_count / total_cases
            ece += weight * np.abs(bin_acc - bin_conf)
            
            rounded_lower = lower * 100
            rounded_upper = upper * 100
            
            reliability_data.append({
                "bin": f"{rounded_lower:.0f}%-{rounded_upper:.0f}%",
                "accuracy": float(bin_acc * 100),
                "confidence": float(bin_conf * 100),
                "count": int(bin_count)
            })

    ece = float(ece)
    print("\n" + "="*40)
    print("📊 CALIBRATION EVALUATION METRICS")
    print("="*40)
    print(f"Expected Calibration Error (ECE): {ece:.4f}")
    print("="*40)
    
    metrics_dict = {
        "ece": ece,
        "reliability_curve": reliability_data
    }
    
    # Store results
    try:
        storage_service = EvaluationStorageService()
        async with async_session_factory() as session:
            await storage_service.save_evaluation(
                db=session,
                evaluation_type="calibration",
                metrics=metrics_dict,
                dataset_size=total_cases,
                metadata={"test_run": "golden_dataset"}
            )
            print("Successfully logged Calibration results to DB.")
    except Exception as e:
        print(f"Database logging failed, using fallback: {e}")
        storage_service = EvaluationStorageService()
        storage_service._save_to_fallback({
            "evaluation_type": "calibration",
            "metrics": metrics_dict,
            "dataset_size": total_cases,
            "metadata": {"test_run": "golden_dataset_fallback"},
        })

if __name__ == "__main__":
    asyncio.run(run_calibration_eval())
