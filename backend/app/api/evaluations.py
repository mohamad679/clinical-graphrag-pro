"""
API endpoints for retrieving evaluation metrics.
Supports fetching from PostgreSQL DB with fallback to JSONL.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.models.evaluation import EvaluationRun
from app.models.user_feedback import UserFeedback
from sqlalchemy import func

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/evaluations", tags=["Evaluations"])

FALLBACK_FILE = Path("data/eval_results_fallback.jsonl")


async def _read_fallback() -> List[Dict[str, Any]]:
    """Helper to read from JSONL fallback if DB is empty or fails."""
    results = []
    if FALLBACK_FILE.exists():
        try:
            with open(FALLBACK_FILE, "r", encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    try:
                        data = json.loads(line)
                        # Add mock timestamp and id if missing for UI
                        if "timestamp" not in data:
                            data["timestamp"] = datetime.utcnow().isoformat()
                        if "id" not in data:
                            data["id"] = f"fallback_{idx}"
                        results.append(data)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to read fallback file: {e}")
    return results


@router.get("/metrics")
async def get_evaluation_metrics(
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """
    Get time-series history of evaluation metrics (RAGAS and Adjudicator runs).
    Returns a unified list of runs formatted for chart plotting.
    """
    try:
        query = select(EvaluationRun).order_by(desc(EvaluationRun.timestamp)).limit(limit)
        result = await db.execute(query)
        runs = result.scalars().all()
        
        if not runs:
            # Try fallback
            fallback_runs = await _read_fallback()
            # Sort fallback by timestamp descending
            fallback_runs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return {"source": "jsonl_fallback", "data": fallback_runs[:limit]}

        formatted_runs = []
        for run in runs:
            formatted_runs.append({
                "id": str(run.id),
                "timestamp": run.timestamp.isoformat(),
                "evaluation_type": run.evaluation_type,
                "dataset_size": run.dataset_size,
                "metrics": run.metrics,
                "metadata": run.metadata_
            })
            
        return {"source": "database", "data": formatted_runs}

    except Exception as e:
        logger.error(f"Error fetching evaluation metrics: {e}")
        # Fallback completely if DB is not configured right
        fallback_runs = await _read_fallback()
        return {"source": "jsonl_fallback_post_error", "data": fallback_runs[:limit]}


@router.get("/latest")
async def get_latest_evaluations(db: AsyncSession = Depends(get_db)):
    """
    Get the single most recent execution for each evaluation type 
    to populate KPI cards.
    """
    latest = {"ragas": None, "adjudicator": None}
    
    try:
        # Get latest RAGAS
        query_ragas = select(EvaluationRun).where(EvaluationRun.evaluation_type == "ragas").order_by(desc(EvaluationRun.timestamp)).limit(1)
        res_ragas = await db.execute(query_ragas)
        latest_ragas = res_ragas.scalar_one_or_none()
        
        # Get latest Adjudicator
        query_adj = select(EvaluationRun).where(EvaluationRun.evaluation_type == "adjudicator").order_by(desc(EvaluationRun.timestamp)).limit(1)
        res_adj = await db.execute(query_adj)
        latest_adj = res_adj.scalar_one_or_none()
        
        if latest_ragas:
            latest["ragas"] = {
                "timestamp": latest_ragas.timestamp.isoformat(),
                "metrics": latest_ragas.metrics,
            }
        
        if latest_adj:
            latest["adjudicator"] = {
                "timestamp": latest_adj.timestamp.isoformat(),
                "metrics": latest_adj.metrics,
            }
            
        # If DB returned *no* data for either, try fallback to fill gaps
        if not latest_ragas or not latest_adj:
            fallback_data = await _read_fallback()
            
            if not latest_ragas:
                # Find most recent ragas in list
                rag_list = [r for r in fallback_data if r.get("evaluation_type") == "ragas"]
                if rag_list:
                    latest_r = sorted(rag_list, key=lambda x: x.get("timestamp", ""), reverse=True)[0]
                    latest["ragas"] = {"timestamp": latest_r.get("timestamp"), "metrics": latest_r.get("metrics")}
                    
            if not latest_adj:
                # Find most recent adjudicator in list
                adj_list = [r for r in fallback_data if r.get("evaluation_type") == "adjudicator"]
                if adj_list:
                    latest_a = sorted(adj_list, key=lambda x: x.get("timestamp", ""), reverse=True)[0]
                    latest["adjudicator"] = {"timestamp": latest_a.get("timestamp"), "metrics": latest_a.get("metrics")}

        # ── CSAT Calculation ──
        # Let's count total positive ratings / total ratings in the DB
        csat_query = select(
            func.count(UserFeedback.id).label("total"),
            func.sum(UserFeedback.rating).label("sum_ratings") # Since ratings are mostly intended to be +1 or -1, but let's assume 1-5 scale per schema or +1/-1 per logic. 
            # Wait, our schema says ge=1, le=5 for rating. Let's assume rating >= 4 is positive.
        )
        
        # ACTUALLY: The Pydantic schema in chat.py enforces `ge=1, le=5`. 
        # So it's a 1-5 star rating. 
        # CSAT = % of 4 or 5 star ratings.
        csat_total_res = await db.execute(select(func.count(UserFeedback.id)))
        total_feedback = csat_total_res.scalar() or 0
        
        csat_pct = None
        if total_feedback > 0:
            csat_pos_res = await db.execute(select(func.count(UserFeedback.id)).where(UserFeedback.rating >= 4))
            pos_feedback = csat_pos_res.scalar() or 0
            csat_pct = pos_feedback / total_feedback
            
        latest["csat"] = {
            "score": csat_pct,
            "total_ratings": total_feedback
        }

        return latest

    except Exception as e:
        logger.error(f"Error fetching latest evaluations: {e}")
        # Complete fallback
        fallback_data = await _read_fallback()
        rag_list = [r for r in fallback_data if r.get("evaluation_type") == "ragas"]
        adj_list = [r for r in fallback_data if r.get("evaluation_type") == "adjudicator"]
        
        if rag_list:
            latest_r = sorted(rag_list, key=lambda x: x.get("timestamp", ""), reverse=True)[0]
            latest["ragas"] = {"timestamp": latest_r.get("timestamp"), "metrics": latest_r.get("metrics")}
        if adj_list:
            latest_a = sorted(adj_list, key=lambda x: x.get("timestamp", ""), reverse=True)[0]
            latest["adjudicator"] = {"timestamp": latest_a.get("timestamp"), "metrics": latest_a.get("metrics")}
            
        return latest
